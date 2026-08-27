# -*- coding: utf-8 -*-
"""HTTP API：SSE 流式聊天 / 商品混合检索 / 规则索引联动 / 兜底全量同步。"""
from __future__ import annotations

import asyncio
import json

import httpx
from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from . import config, rag
from .es_client import get_es
from .graph import build_graph
from .mcp_client import get_mcp_tools
from .memory import SessionMemory

router = APIRouter()


class ChatRequest(BaseModel):
    session_id: str
    user_id: int = 1
    message: str
    # sse: 事件随 SSE 流返回；ws: 事件经 Java PushController 推送到 Netty WS 网关
    transport: str = "sse"


def _sse(ev: dict) -> str:
    return f"data: {json.dumps(ev, ensure_ascii=False, default=str)}\n\n"


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


@router.post("/api/chat")
async def chat(req: ChatRequest):
    async def gen():
        try:
            memory = SessionMemory(req.session_id, req.user_id)
            await memory.load()
            try:
                await get_mcp_tools()
            except Exception as e:
                yield _sse({"type": "status", "data": {"text": f"MCP 连接失败（降级 REST）：{e}", "stage": "mcp"}})

            ws_mode = req.transport == "ws"

            async def push(ev):
                """ws 模式：事件经 Java 内部接口推送到 Netty WS 网关（按 sessionId 隔离）。"""
                try:
                    async with httpx.AsyncClient(timeout=5) as c:
                        await c.post(f"{config.JAVA_API_URL}/internal/push",
                                     json={"sessionId": req.session_id, "event": ev})
                except Exception as e:
                    print(f"[push] failed: {e}", flush=True)

            async def emit(ev):
                if ws_mode:
                    await push(ev)
                else:
                    yield _sse(ev)

            graph = build_graph()
            inputs = {
                "session_id": req.session_id, "user_id": req.user_id,
                "message": req.message, "memory_desc": memory.describe(), "mem": memory,
            }
            final_state = None
            async for mode, chunk in graph.astream(inputs, stream_mode=["updates", "values"]):
                if mode == "updates":
                    for _node, delta in chunk.items():
                        for ev in delta.get("events", []):
                            async for sse_line in emit(ev):
                                yield sse_line
                else:
                    final_state = chunk

            await memory.save()
            text = (final_state or {}).get("final_text", "") or ""
            for i in range(0, len(text), 8):
                async for sse_line in emit({"type": "token", "data": {"text": text[i:i + 8]}}):
                    yield sse_line
                await asyncio.sleep(0.015)
            async for sse_line in emit({"type": "done", "data": {"reply": text, "sessionId": req.session_id}}):
                yield sse_line
        except Exception as e:
            import traceback
            traceback.print_exc()
            if req.transport == "ws":
                try:
                    async with httpx.AsyncClient(timeout=5) as c:
                        await c.post(f"{config.JAVA_API_URL}/internal/push", json={
                            "sessionId": req.session_id,
                            "event": {"type": "error", "data": {"text": f"Agent 内部错误: {e}"}}})
                except Exception:
                    pass
            yield _sse({"type": "error", "data": {"text": f"Agent 内部错误: {e}"}})

    return StreamingResponse(gen(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive",
    })


@router.get("/api/products/search")
async def product_search(
    keyword: str = Query(""), category: str = Query(""), color: str = Query(""),
    season: str = Query(""), style: str = Query(""), maxPrice: float | None = Query(None),
    page: int = Query(1), size: int = Query(24),
):
    """商城页 ES 混合检索（BM25 + 向量 + 标签过滤）。"""
    result = rag.hybrid_product_search(
        keyword=keyword, category=category, color=color, season=season,
        style=style, max_price=maxPrice, page=page, size=size)
    return {"code": 0, "msg": "ok", "data": result}


class ReindexRequest(BaseModel):
    rule_id: int


@router.post("/internal/rules/reindex")
async def rules_reindex(req: ReindexRequest):
    """规则发布联动：从 Java 拉取最新规则 → 增量更新索引 → 下架同族旧版本 → 失效缓存。"""
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"{config.JAVA_API_URL}/rules/{req.rule_id}")
            r.raise_for_status()
            rule = r.json()["data"]
        es = get_es()
        doc = {
            "title": rule.get("title"), "content": rule.get("content"),
            "type": rule.get("type"), "version": rule.get("version"),
            "publish_status": rule.get("publishStatus"),
            "effective_from": _es_dt(rule.get("effectiveFrom")),
            "effective_to": _es_dt(rule.get("effectiveTo")),
            "source": rule.get("source"),
            "tags": json.loads(rule.get("tags") or "[]"),
        }
        es.es.index(index=config.RULE_INDEX, id=str(req.rule_id), document=doc)
        # 下架同族旧版本（族键相同、已发布、非当前 id）
        _deactivate_family(es, req.rule_id, doc.get("title", ""))
        rag.invalidate_cache()
        return {"code": 0, "msg": f"rule #{req.rule_id} 已增量更新索引，同族旧版本已下架，缓存已失效"}
    except Exception as e:
        return {"code": 500, "msg": f"reindex 失败: {e}"}


@router.post("/internal/rules/fullsync")
async def rules_fullsync():
    """兜底：从 Java 全量同步已发布规则到 ES。"""
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"{config.JAVA_API_URL}/rules", params={"status": "published"})
            rules = r.json()["data"]
        es = get_es()
        for rule in rules:
            doc = {
                "title": rule.get("title"), "content": rule.get("content"),
                "type": rule.get("type"), "version": rule.get("version"),
                "publish_status": rule.get("publishStatus"),
                "effective_from": _es_dt(rule.get("effectiveFrom")),
                "effective_to": _es_dt(rule.get("effectiveTo")),
                "source": rule.get("source"),
                "tags": json.loads(rule.get("tags") or "[]"),
            }
            es.es.index(index=config.RULE_INDEX, id=str(rule.get("id")), document=doc)
        rag.invalidate_cache()
        return {"code": 0, "msg": f"fullsync {len(rules)} rules"}
    except Exception as e:
        return {"code": 500, "msg": f"fullsync 失败: {e}"}

