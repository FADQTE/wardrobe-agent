# -*- coding: utf-8 -*-
"""公共答案缓存（L2，跨用户共享）：相同/相近的全局性问题只算一次，省 LLM token。

与 Java 侧的会话历史缓存（L1，私有）分工：
- L1 防「同一用户反复读历史打 DB」，键绑定用户身份，永不跨用户；
- L2 防「不同用户重复问同一个全局问题反复烧 token」，只缓存全局事实类回答。

隔离设计（公共池绝不能泄露个人信息）——写入三道闸：
1. 任务类型白名单：本轮 DAG 任务必须 ⊆ {rule_query, rag}，答案才会是全局事实
   （活动/穿搭规则）；凡涉及衣橱/订单/物流/售后/收藏/试穿的轮次永不入池；
2. 个人标识扫描：问题与回答都扫描订单号（CY…）、手机号、该用户昵称/用户名，
   命中即不入池（防止「我叫X，有什么活动」这类带身份的提问入池）；
3. 非回答轮次不入池：澄清/转人工/安全拦截一律跳过。

读取一道门：
4. 问题预分类：必须含活动/优惠/券/搭配等公共词，且不含「我的/衣橱/订单/退款」
   等个人词——个人问题根本不会查公共池（防错配，而非仅防泄露）。

匹配：精确（归一化文本 O(1)）+ 语义（embedding 余弦 ≥ 阈值，池上限 300 条）。
时效：activity 类 TTL 5 分钟（活动会过期），rag 类 6 小时；规则发布/下线时清池。
故障：Redis/Embedding 任何异常都静默降级为正常走完整链路。
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import time

import redis as redis_lib

from . import config

# 公共词 → 类目；个人词命中则不查/不写公共池
_ACTIVITY_HINTS = ("活动", "优惠", "券", "折扣", "促销", "满减", "打折", "立减")
_RAG_HINTS = ("搭配", "穿搭", "规则", "风格", "场合", "怎么穿", "适合穿")
_PERSONAL_HINTS = ("我的", "衣橱", "订单", "物流", "退款", "退货", "售后", "收藏",
                   "购物车", "下单", "购买", "试穿", "生成图", "效果图", "进度")
# 硬个人标识：订单号 / 手机号
_ORDER_NO = re.compile(r"CY\d{8,}", re.IGNORECASE)
_PHONE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")

_POOL_CAP = 300

_pool_client: redis_lib.Redis | None = None


def _client() -> redis_lib.Redis | None:
    global _pool_client
    if not config.ANSWER_CACHE_ENABLED:
        return None
    if _pool_client is None:
        try:
            _pool_client = redis_lib.Redis.from_url(
                config.ANSWER_CACHE_REDIS_URL, socket_timeout=1, decode_responses=True)
            _pool_client.ping()
        except Exception:
            _pool_client = None
    return _pool_client


def normalize(text: str) -> str:
    return re.sub(r"[，。？?！!·、,.\s：:；;～~]", "", (text or "").strip()).lower()


def is_shareable_question(message: str) -> str | None:
    """读取预分类：返回类目（activity/rag）或 None（个人问题/无关问题不查公共池）。"""
    text = message or ""
    if any(w in text for w in _PERSONAL_HINTS):
        return None
    if any(w in text for w in _ACTIVITY_HINTS):
        return "activity"
    if any(w in text for w in _RAG_HINTS):
        return "rag"
    return None


def contains_personal(text: str, identity_hints: list[str] | None = None) -> bool:
    """硬个人标识扫描：订单号/手机号/当前用户昵称或用户名。"""
    t = text or ""
    if _ORDER_NO.search(t) or _PHONE.search(t):
        return True
    for hint in identity_hints or []:
        if hint and len(hint) >= 2 and hint in t:
            return True
    return False


def _ttl(category: str) -> int:
    return (config.ANSWER_CACHE_ACTIVITY_TTL if category == "activity"
            else config.ANSWER_CACHE_RAG_TTL)


def _exact_key(category: str, norm_q: str) -> str:
    return f"ansc:x:{category}:{hashlib.sha1(norm_q.encode()).hexdigest()[:24]}"


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na and nb else 0.0


def lookup(message: str, embed_fn=None,
           identity_hints: list[str] | None = None) -> tuple[str, str] | None:
    """查公共池：返回 (回答, 类目) 或 None。任何故障静默降级。"""
    client = _client()
    if client is None:
        return None
    category = is_shareable_question(message)
    if not category:
        return None
    norm_q = normalize(message)
    if not norm_q:
        return None
    now = time.time()
    ttl = _ttl(category)
    try:
        # 1) 精确命中
        raw = client.get(_exact_key(category, norm_q))
        if raw:
            entry = json.loads(raw)
            if now - entry.get("created", 0) <= ttl:
                return entry["answer"], category
        # 2) 语义命中（池内余弦；条目过期惰性剔除）
        if embed_fn is not None:
            vectors = embed_fn([message])
            if vectors and vectors[0]:
                qvec = vectors[0]
                pool = client.hgetall(f"ansc:p:{category}")
                best_id, best_score, stale_ids = None, 0.0, []
                for field, raw_entry in pool.items():
                    entry = json.loads(raw_entry)
                    if now - entry.get("created", 0) > ttl:
                        stale_ids.append(field)
                        continue
                    score = _cosine(qvec, entry.get("emb") or [])
                    if score > best_score:
                        best_id, best_score = field, score
                for field in stale_ids:
                    client.hdel(f"ansc:p:{category}", field)
                if best_id and best_score >= config.ANSWER_CACHE_SEMANTIC_THRESHOLD:
                    return json.loads(pool[best_id])["answer"], category
    except Exception:
        return None
    return None


def store(message: str, answer: str, category: str, embed_fn=None,
          identity_hints: list[str] | None = None) -> bool:
    """写入公共池。调用方必须先完成任务白名单闸门；这里再做个人标识扫描兜底。"""
    client = _client()
    if client is None or not answer or not message:
        return False
    if category not in ("activity", "rag"):
        return False
    # 个人标识扫描：问题与回答任一命中都不入池
    if contains_personal(message, identity_hints) or contains_personal(answer, identity_hints):
        return False
    norm_q = normalize(message)
    if not norm_q:
        return False
    try:
        now = time.time()
        entry = {"q": message[:120], "answer": answer, "created": now}
        client.set(_exact_key(category, norm_q), json.dumps(entry, ensure_ascii=False),
                   ex=_ttl(category))
        # 语义池：embedding 失败只影响语义匹配，精确层照常生效
        if embed_fn is not None:
            vectors = embed_fn([message])
            if vectors and vectors[0]:
                entry["emb"] = vectors[0]
                pool_key = f"ansc:p:{category}"
                client.hset(pool_key, hashlib.sha1(norm_q.encode()).hexdigest()[:24],
                            json.dumps(entry, ensure_ascii=False))
                if client.hlen(pool_key) > _POOL_CAP:
                    # 按创建时间淘汰最旧的一批，保持池有界
                    rows = [(json.loads(v).get("created", 0), f)
                            for f, v in client.hgetall(pool_key).items()]
                    rows.sort()
                    for _, field in rows[: _POOL_CAP // 10]:
                        client.hdel(pool_key, field)
        return True
    except Exception:
        return False


def maybe_store_turn(final_state: dict, answer: str, embed_fn=None,
                     identity_hints: list[str] | None = None) -> bool:
    """写入闸门：只有「纯全局知识轮次」的非空回答才允许进公共池。

    - 任务类型白名单：tasks ⊆ {rule_query, rag}，混入任何个人类任务（衣橱/订单/
      物流/售后/收藏/试穿）即整轮不入池；
    - 澄清、转人工、安全拦截轮不入池；
    - store() 内部再做问题/回答的个人标识扫描兜底。
    """
    intent = final_state.get("intent_data") or {}
    if intent.get("needsClarification") or final_state.get("handoff"):
        return False
    if (final_state.get("safety_data") or {}).get("blocked_user_request"):
        return False
    types = {t.get("type") for t in (intent.get("tasks") or [])}
    if not types or not types <= {"rule_query", "rag"}:
        return False
    category = "activity" if "rule_query" in types else "rag"
    return store(final_state.get("message") or "", answer, category, embed_fn, identity_hints)


def invalidate(category: str | None = None) -> int:
    """规则发布/下线时清池（activity/rag/None=全部）。"""
    client = _client()
    if client is None:
        return 0
    removed = 0
    try:
        categories = [category] if category else ["activity", "rag"]
        for cat in categories:
            keys = list(client.scan_iter(f"ansc:x:{cat}:*"))
            if keys:
                removed += client.delete(*keys)
            removed += client.delete(f"ansc:p:{cat}")
    except Exception:
        return 0
    return removed
