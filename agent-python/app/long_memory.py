# -*- coding: utf-8 -*-
"""长期记忆写入管线：候选抽取 → 规则门控 → 归一化 → Java 治理存储。

对应记忆系统设计文档 §10/§13/§18：
- 不是每轮都记：先用规则判断"这轮对话有没有可能产生记忆"，再花一次 LLM 调用抽取候选；
- 结构化优先：谓词白名单保证记忆能被 MySQL 精确查询，而不是全部塞进向量库；
- 来源分级：用户明确 > 行为证据 > Agent 推断，source/confidence 随记忆落库；
- Scope：为他人购物/特定品类必须标注作用域，防止局部信息升级成全局偏好。
"""
from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timezone

import httpx

from . import config
from .llm import get_llm

# 谓词白名单：只有落在枚举内的记忆才能进入长期存储，保证可精确查询
PREDICATES = {
    "size_top": "上装尺码（L/XL/170/175 等）",
    "size_bottom": "下装尺码（30/31/175/96A 等）",
    "size_shoes": "鞋码（40/41/42 等）",
    "body": "身材信息（身高/体重/肩宽等）",
    "budget": "购物预算（{\"min\":0,\"max\":1000}）",
    "preferred_color": "偏好颜色（黑色/白色 等）",
    "avoid_color": "排斥颜色",
    "preferred_style": "偏好风格（通勤/运动/极简/日系 等）",
    "preferred_fit": "版型偏好（宽松/修身/常规）",
    "preferred_category": "常买品类（外套/衬衫/卫衣 等）",
    "avoid": "明确排斥项（\"以后不要推荐 XX\"）",
    "scene": "常购场景（通勤/约会/户外/面试 等）",
    "brand": "偏好品牌",
}

SOURCE_EXPLICIT = "user_explicit"
SOURCE_BEHAVIOR = "user_behavior"
SOURCE_INFERENCE = "agent_inference"
VALID_SOURCES = {SOURCE_EXPLICIT, SOURCE_BEHAVIOR, SOURCE_INFERENCE}
VALID_TYPES = {"episode", "semantic", "profile"}

# 规则门控：触发词命中才调用 LLM 抽取，事务性请求（查订单/物流）直接跳过，
# 既省调用成本，也避免把"查过什么"误记成"偏好什么"。
EXTRACT_TRIGGERS = re.compile(
    r"我(平时|一般|通常|一直|总是|基本)|喜欢|不喜欢|讨厌|不要|别再|以后|偏好|"
    r"尺码|尺码|穿.{0,3}[码号]|[码号]|身高|体重|公斤|斤|预算|以内|左右|"
    r"宽松|修身|显瘦|通勤|约会|户外|面试|运动风|极简|日系|"
    r"给(我|他|她|爸|妈|男朋友|女朋友|老公|老婆|儿子|女儿|朋友)"
)
# 一眼可判定无记忆价值的消息：纯事务/寒暄，不进入抽取
SKIP_PATTERNS = re.compile(
    r"^(查|看看|帮我查|物流|订单|售后|退货|退款|你好|在吗|谢谢|嗯|好的|ok)"
)

EXTRACT_SYSTEM = """你是电商 Agent 的记忆抽取器。从对话中抽取"对未来对话有用"的长期记忆候选。

判断标准：
- 稳定事实（尺码/身材/预算）→ memory_type=semantic，source=user_explicit，confidence=1.0
- 长期偏好（颜色/风格/版型/常买品类/场景/品牌）→ memory_type=profile，用户亲口说 source=user_explicit confidence=1.0；仅从行为推断 source=agent_inference confidence<=0.6
- 一次发生的事件（这次为某人买什么/这次买了什么/这次需要什么）→ memory_type=episode，source=user_behavior，importance 0.5~0.85
- 明确排斥指令（"以后不要推荐 X"）→ memory_type=profile，predicate=avoid，importance>=0.9
- 一条查询请求、寒暄、当下即可回答完的内容 → 不要记
- 一次购买行为不能直接升级成长期偏好（"买了黑鞋"≠"喜欢黑色"）

必须遵守：
1. predicate 只能从枚举中选：size_top/size_bottom/size_shoes/body/budget/preferred_color/avoid_color/preferred_style/preferred_fit/preferred_category/avoid/scene/brand；episode 用行为动名（如 tryon_image、buy_gift）
2. value 用中文原词或数字；budget 用 {"min":0,"max":数字}
3. scope 默认 {"person":"user"}；"给我爸/朋友买"必须 scope={"person":"爸爸"} 并标 episode；限定某品类时加 "category"
4. confidence：用户明确=1.0；行为证据=0.6~0.8；推断=0.5~0.7
5. 每轮最多 3 条；没有值得记的输出 {"memories": []}
6. content 用一句话中文概括原话依据

输出 JSON：{"memories": [{"memory_type":"semantic","predicate":"size_top","value":"L","content":"用户平时上装穿 L","source":"user_explicit","confidence":1.0,"importance":0.8,"scope":{"person":"user"}}]}"""


def should_extract(message: str) -> bool:
    """规则门控：事务性/寒暄消息直接跳过，避免无意义的抽取调用。"""
    text = (message or "").strip()
    if len(text) < 3 or SKIP_PATTERNS.match(text):
        return False
    return bool(EXTRACT_TRIGGERS.search(text))


async def extract_candidates(user_message: str, context: str = "") -> list[dict]:
    """LLM 抽取候选 + 归一化门控；LLM 不可用或无候选时返回空列表。"""
    if config.MOCK_AGENT or not config.LLM_API_KEY or not should_extract(user_message):
        return []
    user = "最近对话:\n" + (context or "（无）") + f"\n\n当前用户消息: {user_message}\n\n请抽取记忆候选。"
    try:
        data = get_llm().chat_json(EXTRACT_SYSTEM, user)
    except Exception as e:
        print(f"[long-memory] extract failed: {e}", flush=True)
        return []
    return normalize_candidates(data.get("memories") or [])


def normalize_candidates(candidates: list) -> list[dict]:
    """规则门控 + 归一化：白名单外丢弃、置信度/重要性钳制、按价值排序截断。"""
    out = []
    for raw in candidates[:3]:
        if not isinstance(raw, dict):
            continue
        memory_type = str(raw.get("memory_type") or "").strip().lower()
        predicate = str(raw.get("predicate") or "").strip().lower()
        source = str(raw.get("source") or SOURCE_EXPLICIT).strip().lower()
        if memory_type not in VALID_TYPES or source not in VALID_SOURCES:
            continue
        if memory_type != "episode" and predicate not in PREDICATES:
            continue  # 结构化事实必须落在白名单内，否则无法精确查询
        if not raw.get("value") and not raw.get("content"):
            continue
        confidence = _clamp(raw.get("confidence"), 0.0, 1.0, 0.6)
        if source == SOURCE_INFERENCE:
            confidence = min(confidence, 0.7)  # 推断不得冒充确定事实
        importance = _clamp(raw.get("importance"), 0.0, 1.0, 0.5)
        if memory_type == "episode" and importance < 0.45:
            continue  # 文档 §10：低价值 episode 不进入长期记忆
        scope = raw.get("scope") if isinstance(raw.get("scope"), dict) else {"person": "user"}
        scope.setdefault("person", "user")
        out.append({
            "memory_type": memory_type,
            "predicate": predicate,
            "value": raw.get("value"),
            "content": str(raw.get("content") or "")[:200],
            "source": source,
            "confidence": round(confidence, 2),
            "importance": round(importance, 2),
            "scope": scope,
        })
    # 同谓词重复候选只保留置信度最高的一条
    best: dict[str, dict] = {}
    for item in out:
        key = (item["memory_type"], item["predicate"])
        if key not in best or item["confidence"] > best[key]["confidence"]:
            best[key] = item
    return sorted(best.values(), key=lambda m: -m["importance"])[:3]


async def store_candidates(user_id: int, candidates: list[dict], source_id: str = "") -> list[dict]:
    """调用 Java /api/memory/write 落库（去重/supersede 由 Java 治理），返回写入结果。"""
    results = []
    for item in candidates:
        payload = {
            "userId": user_id,
            "memoryType": item["memory_type"],
            "predicate": item["predicate"],
            "value": item["value"],
            "content": item.get("content"),
            "importance": item.get("importance"),
            "confidence": item.get("confidence"),
            "sourceType": item["source"],
            "sourceId": source_id,
            "scope": item.get("scope"),
        }
        try:
            async with httpx.AsyncClient(timeout=5) as c:
                r = await c.post(f"{config.JAVA_API_URL}/memory/write", json=payload)
                r.raise_for_status()
                body = r.json().get("data") or {}
                results.append({"predicate": item["predicate"], "action": body.get("action")})
                print(f"[long-memory] stored {item['memory_type']}/{item['predicate']}"
                      f"={item['value']} action={body.get('action')}", flush=True)
                memory_id = (body.get("memory") or {}).get("id")
                if memory_id:
                    await _index_to_es(memory_id, item, user_id)
        except Exception as e:
            # 写入失败只影响记忆积累，不能影响当轮对话
            print(f"[long-memory] store failed: {e}", flush=True)
    return results


async def _index_to_es(memory_id, item: dict, user_id: int):
    """MySQL 是事实源，ES memory_index 只作检索索引；向量不可用时只建 BM25 文档。"""
    try:
        from .es_client import get_es
        es = get_es()
        if not es.es.indices.exists(index=config.MEMORY_INDEX):
            return
        doc = {
            "user_id": str(user_id),
            "memory_type": item["memory_type"],
            "predicate": item["predicate"],
            "content": item.get("content") or "",
            "importance": item.get("importance"),
            "confidence": item.get("confidence"),
            "status": "active",
            "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        if es.index_has_vector(config.MEMORY_INDEX):
            vectors = es.embed([doc["content"]])
            dims = es.vector_dims(config.MEMORY_INDEX)
            if vectors and vectors[0] and (not dims or len(vectors[0]) == dims):
                doc["embedding"] = vectors[0]
        await asyncio.to_thread(
            es.es.index, index=config.MEMORY_INDEX, id=str(memory_id), document=doc)
    except Exception as e:
        print(f"[long-memory] es index failed: {e}", flush=True)


# ---------- 读取路径 ----------

# 意图路由：只有回溯历史的提问才召回情景记忆（文档 §14，避免每轮全量搜记忆）
EPISODIC_TRIGGERS = re.compile(
    r"上次|上回|之前|以前|历史|买过|曾经|推荐过|说过|那次|上一次"
)


def wants_episodic_recall(message: str) -> bool:
    return bool(EPISODIC_TRIGGERS.search(message or ""))


async def fetch_facts(user_id: int) -> list[dict]:
    """结构化事实/偏好：MySQL 精确查询（能精确查就不模糊搜），失败静默为空。"""
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.get(f"{config.JAVA_API_URL}/memory/facts", params={"userId": user_id})
            r.raise_for_status()
            return r.json().get("data") or []
    except Exception as e:
        print(f"[long-memory] facts fetch failed: {e}", flush=True)
        return []


def search_episodes(query: str, user_id: int, size: int = 4) -> list[dict]:
    """情景记忆混合召回（同步，调用方需在线程池中执行）。"""
    from .rag import hybrid_memory_search
    try:
        return hybrid_memory_search(query, user_id, size=size, memory_types=["episode"])
    except Exception as e:
        print(f"[long-memory] episode search failed: {e}", flush=True)
        return []


def touch_memories(memory_ids: list):
    """召回被使用的记忆回写访问证据，供遗忘衰减计算 Memory Strength（后台执行）。"""

    async def run():
        for memory_id in memory_ids:
            try:
                async with httpx.AsyncClient(timeout=5) as c:
                    await c.post(f"{config.JAVA_API_URL}/memory/{memory_id}/access")
            except Exception:
                pass

    return asyncio.create_task(run())


def render_facts(rows: list[dict]) -> str:
    """事实渲染成紧凑上下文；非用户明确来源必须带（推断）标记（文档 §18）。"""
    lines = []
    for row in rows[:8]:
        value = row.get("value")
        if isinstance(value, str) and value:
            try:
                parsed = json.loads(value)
                value = parsed if not isinstance(parsed, str) else parsed
            except (TypeError, ValueError):
                pass
        if isinstance(value, dict):
            value = json.dumps(value, ensure_ascii=False)
        marker = "" if row.get("sourceType") == SOURCE_EXPLICIT else "（推断）"
        # Scope（文档 §13）：非用户本人的记忆必须标注主体，防止冒充用户自身偏好
        person = _scope_person(row.get("scope"))
        prefix = "" if person in ("", "user") else f"[为{person}] "
        lines.append(f"{prefix}{row.get('predicate')}={value}{marker}")
    return "；".join(lines)


def _scope_person(scope) -> str:
    if isinstance(scope, str) and scope:
        try:
            scope = json.loads(scope)
        except (TypeError, ValueError):
            return ""
    if isinstance(scope, dict):
        return str(scope.get("person") or "")
    return ""


def render_episodes(rows: list[dict]) -> str:
    lines = []
    for row in rows[:4]:
        content = " ".join(str(row.get("content") or "").split())[:120]
        created = str(row.get("createdAt") or "")[:10]
        lines.append(f"- {content}（{created}）")
    return "\n".join(lines)


async def capture_round(user_id: int, user_message: str, assistant_text: str,
                        recent_context: str = "", source_id: str = "") -> list[dict]:
    """一轮对话结束后的记忆捕获入口：抽取 + 落库，全程不抛异常。"""
    try:
        candidates = await extract_candidates(user_message, recent_context)
        if not candidates:
            return []
        return await store_candidates(user_id, candidates, source_id=source_id)
    except Exception as e:
        print(f"[long-memory] capture failed: {e}", flush=True)
        return []


def _clamp(value, low: float, high: float, fallback: float) -> float:
    try:
        return max(low, min(high, float(value)))
    except (TypeError, ValueError):
        return fallback
