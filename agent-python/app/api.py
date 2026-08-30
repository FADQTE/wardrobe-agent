# -*- coding: utf-8 -*-
"""HTTP API：SSE 流式聊天 / 商品混合检索 / 规则索引联动 / 兜底全量同步。"""
from __future__ import annotations

import asyncio
import json

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from . import config, rag
from .es_client import get_es
from .graph import build_graph
from .mcp_client import get_mcp_tools
from .memory import SessionMemory
from . import long_memory

router = APIRouter()

# 同一会话串行锁：session state 是整包读改写，并发轮次会互相覆盖
_session_locks: dict[str, asyncio.Lock] = {}


def _session_lock(session_id: str) -> asyncio.Lock:
    lock = _session_locks.get(session_id)
    if lock is None:
        lock = _session_locks[session_id] = asyncio.Lock()
    return lock


class ChatRequest(BaseModel):
    session_id: str
    user_id: int = 1
    message: str
    # sse: 事件随 SSE 流返回；ws: 事件经 Java PushController 推送到 Netty WS 网关
    transport: str = "sse"
    # Runtime Context（服务端可信字段，不由用户自然语言产生）
    member_level: str = ""
    risk_level: str = ""
    page_context: dict | None = None


def _sse(ev: dict) -> str:
    return f"data: {json.dumps(ev, ensure_ascii=False, default=str)}\n\n"


def _history_meta(final_state: dict | None) -> dict:
    """从本轮事件中提取重进页面后仍可恢复的富展示数据。"""
    meta: dict = {}
    for ev in (final_state or {}).get("events", []):
        data = ev.get("data") or {}
        if ev.get("type") == "product":
            meta["products"] = data.get("products") or []
            meta["productTitle"] = data.get("title") or "商城在售候选"
        elif ev.get("type") == "outfit":
            meta["outfit"] = data.get("outfit")
        elif ev.get("type") == "image":
            meta["image"] = {
                "url": data.get("url"),
                "label": data.get("label") or "换装效果图",
                "taskId": data.get("taskId"),
                "provider": data.get("provider"),
                "isSimulation": data.get("isSimulation", False),
                "notice": data.get("notice"),
            }
        elif ev.get("type") == "handoff":
            meta["handoff"] = data.get("reason")
    return {k: v for k, v in meta.items() if v is not None}


def _es_dt(s):
    """Java LocalDateTime(无时区) → ES date(ISO8601 +08:00)。"""
    if not s:
        return None
    s = s.replace(" ", "T")
    if len(s) == 19 and "+" not in s and not s.endswith("Z"):
        s += "+08:00"
    return s


def _family(title: str) -> str:
    """规则族键：剥离尾部版本后缀（"秋季通勤焕新季 v3" → "秋季通勤焕新季"）。"""
    import re
    return re.sub(r"\s*v?\d+$", "", title or "").strip()


def _deactivate_family(es, rule_id: int, title: str):
    """下架同族其他已发布版本（标题族键相同）。"""
    fam = _family(title)
    try:
        resp = es.es.search(index=config.RULE_INDEX, body={
            "query": {"match": {"title": fam}}, "size": 50})
        for h in resp["hits"]["hits"]:
            src = h["_source"]
            if (str(h["_id"]) != str(rule_id)
                    and _family(src.get("title", "")) == fam
                    and src.get("publish_status") == "published"):
                es.es.update(index=config.RULE_INDEX, id=h["_id"],
                             doc={"publish_status": "offline"})
                print(f"[rules] deactivate old version #{h['_id']} {src.get('title')}", flush=True)
    except Exception as e:
        print(f"[rules] deactivate failed: {e}", flush=True)


def _base_rule_doc(rule: dict) -> dict:
    tags = rule.get("tags") or []
    if isinstance(tags, str):
        try:
            tags = json.loads(tags)
        except (TypeError, json.JSONDecodeError):
            tags = []
    return {
        "title": rule.get("title"), "content": rule.get("content"),
        "type": rule.get("type"), "version": rule.get("version"),
        "publish_status": rule.get("publishStatus"),
        "effective_from": _es_dt(rule.get("effectiveFrom")),
        "effective_to": _es_dt(rule.get("effectiveTo")),
        "source": rule.get("source"), "tags": tags,
    }


def _build_rule_docs(es, rules: list[dict]) -> tuple[list[dict], str]:
    """构建规则索引文档；向量索引存在时同步生成 title+content embedding。"""
    docs = [_base_rule_doc(rule) for rule in rules]
    if not docs or not es.index_has_vector(config.RULE_INDEX):
        return docs, "index_without_vector"
    vectors = es.embed([
        f"{doc.get('title') or ''} {doc.get('content') or ''}".strip() for doc in docs
    ])
    expected_dims = es.vector_dims(config.RULE_INDEX)
    if not vectors or len(vectors) != len(docs):
        return docs, "embedding_unavailable"
    if expected_dims and any(len(vector) != expected_dims for vector in vectors):
        return docs, "dimension_mismatch"
    for doc, vector in zip(docs, vectors):
        doc["embedding"] = vector
    return docs, "ok"


def _apply_latest_versions(rules: list[dict], docs: list[dict]) -> None:
    """全量同步时同族只保留最高版本 published，避免通知丢失后旧版继续被召回。"""
    latest: dict[str, tuple[int, int]] = {}
    for rule, doc in zip(rules, docs):
        if doc.get("publish_status") != "published":
            continue
        family = _family(doc.get("title") or "")
        marker = (int(doc.get("version") or 0), int(rule.get("id") or 0))
        if marker > latest.get(family, (-1, -1)):
            latest[family] = marker
    for rule, doc in zip(rules, docs):
        family = _family(doc.get("title") or "")
        marker = (int(doc.get("version") or 0), int(rule.get("id") or 0))
        if doc.get("publish_status") == "published" and latest.get(family) != marker:
            doc["publish_status"] = "offline"


@router.post("/api/chat")
async def chat(req: ChatRequest, request: Request):
    # WS 请求只能来自 Java Relay；浏览器 SSE 则必须携带 Java 签发的 bearer token，
    # 且 token 所属用户必须与请求 user_id 一致。
    if req.transport == "ws":
        if request.headers.get("X-Internal-Api-Key") != config.JAVA_INTERNAL_API_KEY:
            raise HTTPException(status_code=401, detail="invalid internal credential")
    else:
        authorization = request.headers.get("Authorization", "")
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                response = await client.get(
                    f"{config.JAVA_API_URL}/auth/me",
                    headers={"Authorization": authorization},
                )
            body = response.json()
            authenticated_id = int((body.get("data") or {}).get("id") or 0)
            if response.status_code != 200 or body.get("code") != 0 or authenticated_id != req.user_id:
                raise ValueError("identity mismatch")
        except Exception as exc:
            raise HTTPException(status_code=401, detail="login required") from exc

    async def gen():
        memory = None
        assistant_saved = False
        lock = _session_lock(req.session_id)
        if lock.locked():
            yield _sse({"type": "status", "data": {
                "text": "同一会话的上一轮请求仍在处理中，本轮已排队…", "stage": "session"}})
        await lock.acquire()
        try:
            memory = SessionMemory(req.session_id, req.user_id)
            await memory.load()
            await memory.load_long_term(req.message)
            # 先落会话和用户消息：即使用户立刻切换页面，后台仍可完成本轮并供前端恢复。
            await memory.save(title=req.message.strip()[:60] if not memory.exists else None)
            await memory.append_message("user", req.message)
            try:
                await get_mcp_tools()
            except Exception as e:
                yield _sse({"type": "status", "data": {"text": f"MCP 连接失败（降级 REST）：{e}", "stage": "mcp"}})

            ws_mode = req.transport == "ws"

            # Trace 可观测：每轮执行证据持久化到 Java trace_event（只存公开摘要）
            from .trace import TraceRecorder
            trace = TraceRecorder(req.session_id)

            async def push(ev):
                """ws 模式：事件经 Java 内部接口推送到 Netty WS 网关（按 sessionId 隔离）。"""
                try:
                    async with httpx.AsyncClient(timeout=5, headers=config.JAVA_INTERNAL_HEADERS) as c:
                        await c.post(f"{config.JAVA_API_URL}/internal/push",
                                     json={"sessionId": req.session_id, "event": ev})
                except Exception as e:
                    print(f"[push] failed: {e}", flush=True)

            async def emit(ev):
                trace.record(ev)
                if ws_mode:
                    await push(ev)
                else:
                    yield _sse(ev)

            # 执行中事件经 event_sink 即时进入推送通道（SSE 队列 / WS 网关），
            # 不再等 LangGraph 节点结束才随 updates 批量出现。
            live_queue: asyncio.Queue = asyncio.Queue()

            async def deliver(ev):
                trace.record(ev)
                if ws_mode:
                    await push(ev)
                else:
                    live_queue.put_nowait(ev)

            # Runtime Context 双通道（trusted_for_model / system_only + 冲突解析）
            from .context import RuntimeContext
            runtime = RuntimeContext(
                user_id=req.user_id, member_level=req.member_level,
                risk_level=req.risk_level, page_context=req.page_context,
                user_message=req.message,
            ).build()

            graph = build_graph()
            inputs = {
                "session_id": req.session_id, "user_id": req.user_id,
                "message": req.message, "memory_desc": memory.describe(), "mem": memory,
                "runtime": runtime, "event_sink": deliver,
            }

            async def run_graph() -> dict | None:
                final = None
                async for mode, chunk in graph.astream(inputs, stream_mode=["updates", "values"]):
                    if mode == "updates":
                        for _node, delta in chunk.items():
                            for ev in delta.get("events", []):
                                if ev.get("_liveEmitted"):
                                    continue  # 已在执行中即时推送，避免重复
                                await deliver(ev)
                    else:
                        final = chunk
                return final

            graph_task = asyncio.create_task(run_graph())
            try:
                while True:
                    await asyncio.wait({graph_task}, timeout=0.05)
                    while not live_queue.empty():
                        yield _sse(live_queue.get_nowait())
                    if graph_task.done():
                        break
                final_state = graph_task.result()
            finally:
                if not graph_task.done():
                    graph_task.cancel()

            await memory.save()
            text = (final_state or {}).get("final_text", "") or ""
            await memory.append_message("assistant", text, _history_meta(final_state))
            assistant_saved = True
            for i in range(0, len(text), 8):
                async for sse_line in emit({"type": "token", "data": {"text": text[i:i + 8]}}):
                    yield sse_line
                await asyncio.sleep(0.015)
            async for sse_line in emit({"type": "done", "data": {"reply": text, "sessionId": req.session_id}}):
                yield sse_line
            await trace.wait()
            # 长期记忆捕获：本轮结束后后台执行（抽取+治理落库），不阻塞响应收尾
            if config.MEMORY_WRITE_ENABLED:
                asyncio.create_task(long_memory.capture_round(
                    req.user_id, req.message, text,
                    recent_context=memory.transcript(), source_id=req.session_id))
        except Exception as e:
            import traceback
            traceback.print_exc()
            error_text = f"Agent 内部错误: {e}"
            if memory is not None and not assistant_saved:
                await memory.append_message("assistant", error_text, {"error": True})
            if req.transport == "ws":
                try:
                    async with httpx.AsyncClient(timeout=5, headers=config.JAVA_INTERNAL_HEADERS) as c:
                        await c.post(f"{config.JAVA_API_URL}/internal/push", json={
                            "sessionId": req.session_id,
                            "event": {"type": "error", "data": {"text": error_text}}})
                except Exception:
                    pass
            yield _sse({"type": "error", "data": {"text": error_text}})
        finally:
            lock.release()

    return StreamingResponse(gen(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive",
    })


@router.get("/api/products/search")
async def product_search(
    keyword: str = Query(""), category: str = Query(""), color: str = Query(""),
    season: str = Query(""), style: str = Query(""), maxPrice: float | None = Query(None),
    page: int = Query(1), size: int = Query(24),
):
    """商城页 ES 混合检索（BM25 + 向量 + 标签过滤）+ Reranker 重排。"""
    candidate_size = config.RERANK_TOP_N if (config.RERANK_ENABLED and keyword) else size
    result = rag.hybrid_product_search(
        keyword=keyword, category=category, color=color, season=season,
        style=style, max_price=maxPrice, page=page, size=candidate_size)
    if config.RERANK_ENABLED and keyword and len(result["products"]) > 1:
        from . import rerank as rerank_mod
        result["products"] = await rerank_mod.rerank(
            keyword,
            [p | {"text": f"{p.get('name', '')} {p.get('detail', '')}"} for p in result["products"]],
            top_k=size)
        result["reranked"] = True
    return {"code": 0, "msg": "ok", "data": result}


class ReindexRequest(BaseModel):
    rule_id: int


@router.post("/internal/memory/fullsync")
async def memory_fullsync():
    """兜底：从 MySQL 全量同步 active 记忆到 ES memory_index（索引只是检索层，MySQL 是事实源）。"""
    try:
        async with httpx.AsyncClient(timeout=10, headers=config.JAVA_INTERNAL_HEADERS) as c:
            r = await c.get(f"{config.JAVA_API_URL}/memory/list",
                            params={"status": "active", "limit": 200})
            r.raise_for_status()
            rows = r.json().get("data") or []
        es = get_es()
        if not es.es.indices.exists(index=config.MEMORY_INDEX):
            es.es.indices.create(index=config.MEMORY_INDEX, body=_memory_mapping(es))
        docs = []
        for row in rows:
            content = row.get("content") or ""
            doc = {
                "user_id": str(row.get("userId") or ""),
                "memory_type": row.get("memoryType") or "episode",
                "predicate": row.get("predicate") or "",
                "content": content,
                "importance": row.get("importance"),
                "confidence": row.get("confidence"),
                "status": "active",
                "created_at": _es_dt(str(row.get("createdAt") or "").replace("T", " ")),
            }
            if content:
                docs.append(doc)
        if docs and es.index_has_vector(config.MEMORY_INDEX):
            vectors = es.embed([d["content"] for d in docs])
            dims = es.vector_dims(config.MEMORY_INDEX)
            if vectors and len(vectors) == len(docs) and all(
                    not dims or len(v) == dims for v in vectors):
                for doc, vector in zip(docs, vectors):
                    doc["embedding"] = vector
        for row, doc in zip(rows, docs):
            if not doc.get("content"):
                continue
            es.es.index(index=config.MEMORY_INDEX, id=str(row.get("id")), document=doc)
        if docs:
            es.es.refresh(index=config.MEMORY_INDEX)
        return {"code": 0, "msg": f"memory fullsync {len(docs)} docs, "
                f"vector={'ok' if any('embedding' in d for d in docs) else 'skipped'}"}
    except Exception as e:
        return {"code": 500, "msg": f"memory fullsync 失败: {e}"}


def _memory_mapping(es) -> dict:
    dims = es.vector_dims(config.PRODUCT_INDEX) or config.EMBEDDING_DIM
    props = {
        "user_id": {"type": "keyword"}, "memory_type": {"type": "keyword"},
        "predicate": {"type": "keyword"},
        "content": {"type": "text", "analyzer": "standard"},
        "importance": {"type": "float"}, "confidence": {"type": "float"},
        "status": {"type": "keyword"}, "created_at": {"type": "date"},
    }
    if config.EMBEDDING_MODE != "none":
        props["embedding"] = {"type": "dense_vector", "dims": dims,
                              "index": True, "similarity": "cosine"}
    return {"settings": {"number_of_shards": 1, "number_of_replicas": 0},
            "mappings": {"properties": props}}


@router.post("/eval/run")
async def eval_run():
    """固定回归用例评测：走真实 Agent 代码路径，返回 eval_report。"""
    from .evals import run_all
    return {"code": 0, "msg": "ok", "data": await run_all()}


@router.post("/internal/rules/reindex")
async def rules_reindex(req: ReindexRequest):
    """规则发布联动：从 Java 拉取最新规则 → 增量更新索引 → 下架同族旧版本 → 失效缓存。"""
    try:
        async with httpx.AsyncClient(timeout=10, headers=config.JAVA_INTERNAL_HEADERS) as c:
            r = await c.get(f"{config.JAVA_API_URL}/rules/{req.rule_id}")
            r.raise_for_status()
            rule = r.json()["data"]
        es = get_es()
        docs, vector_state = await asyncio.to_thread(_build_rule_docs, es, [rule])
        doc = docs[0]
        es.es.index(index=config.RULE_INDEX, id=str(req.rule_id), document=doc,
                    refresh="wait_for")
        # 只有发布新版本才下架同族旧版；下线旧版本不能误伤当前最新版。
        if doc.get("publish_status") == "published":
            _deactivate_family(es, req.rule_id, doc.get("title", ""))
        rag.invalidate_cache()
        return {"code": 0, "msg": f"rule #{req.rule_id} 已增量更新索引，"
                f"vector={vector_state}，缓存已失效"}
    except Exception as e:
        return {"code": 500, "msg": f"reindex 失败: {e}"}


@router.post("/internal/rules/fullsync")
async def rules_fullsync():
    """兜底：从 Java 全量同步全部规则，修复漏通知、旧版状态与缓存。"""
    try:
        async with httpx.AsyncClient(timeout=10, headers=config.JAVA_INTERNAL_HEADERS) as c:
            r = await c.get(f"{config.JAVA_API_URL}/rules")
            r.raise_for_status()
            rules = r.json()["data"]
        es = get_es()
        docs, vector_state = await asyncio.to_thread(_build_rule_docs, es, rules)
        _apply_latest_versions(rules, docs)
        ids = [str(rule.get("id")) for rule in rules]
        for rule, doc in zip(rules, docs):
            es.es.index(index=config.RULE_INDEX, id=str(rule.get("id")), document=doc)
        if ids:
            es.es.delete_by_query(index=config.RULE_INDEX, body={
                "query": {"bool": {"must_not": [{"ids": {"values": ids}}]}}
            }, conflicts="proceed", refresh=True)
        rag.invalidate_cache()
        return {"code": 0, "msg": f"fullsync {len(rules)} rules, vector={vector_state}"}
    except Exception as e:
        return {"code": 500, "msg": f"fullsync 失败: {e}"}

