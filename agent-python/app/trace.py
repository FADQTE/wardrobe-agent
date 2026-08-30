# -*- coding: utf-8 -*-
"""Trace 记录器：把每轮执行的公开证据持久化到 Java 侧 trace_event 表。

只上报公开摘要（事件名/工具名/引用标识/路径），不上报系统提示词、CoT、密钥、隐私原文。
payload 统一构造成结构化字段（非长 JSON 字符串），前端可读、SQL 可查。
"""
from __future__ import annotations

import asyncio
import json

import httpx

from . import config

CATEGORY_MAP = {
    "entry": "entry",
    "plan": "control", "status": "control", "intent": "control",
    "tool": "fact", "product": "fact", "image_progress": "fact", "image": "fact",
    "rag": "knowledge", "outfit": "result",
    "done": "result", "error": "control",
    "safety": "safety", "handoff": "control", "context": "control",
    "memory": "control",
}

# 流式输出分块属于传输细节（每 8 字符一条），不是决策证据，不入链
SKIP_EVENTS = {"token"}


def _clip(value, limit: int) -> str:
    return str(value or "")[:limit]


def _sanitize_payload(ev: dict) -> dict:
    """构造脱敏载荷：按事件类型保留可读摘要，不存隐私原文与系统提示词。"""
    data = ev.get("data") or {}
    t = ev.get("type")

    if t == "entry":
        return {"message": _clip(data.get("message"), 160),
                "transport": data.get("transport"),
                "memberLevel": data.get("memberLevel") or "",
                "hasPageContext": bool(data.get("pageContext"))}
    if t == "done":
        payload = {"reply": _clip(data.get("reply"), 200)}
        if data.get("latencyMs") is not None:
            payload["latencyMs"] = data.get("latencyMs")
        return payload
    if t == "tool":
        return {"name": data.get("name"), "ok": data.get("ok"),
                "summary": _clip(data.get("summary"), 200)}
    if t == "rag":
        rules = data.get("rules") or []
        payload = {"query": _clip(data.get("query"), 80), "hits": len(rules),
                   "citations": [r.get("title") for r in rules[:5]]}
        notice = data.get("statusNotice")
        if notice:
            payload["statusNotice"] = {"title": notice.get("title"),
                                       "status": notice.get("publishStatus")}
        return payload
    if t == "product":
        products = data.get("products") or []
        return {"title": _clip(data.get("title"), 60), "hits": len(products),
                "names": [p.get("name") for p in products[:5]]}
    if t == "outfit":
        outfit = data.get("outfit") or {}
        return {"name": _clip(outfit.get("name"), 60),
                "items": [i.get("name") for i in (outfit.get("items") or [])[:6]],
                "ruleSources": outfit.get("ruleSources") or []}
    if t == "image":
        return {"label": _clip(data.get("label"), 60), "provider": data.get("provider"),
                "isSimulation": data.get("isSimulation"),
                "garments": data.get("garmentNames") or []}
    if t == "image_progress":
        return {"stage": data.get("stage"), "percent": data.get("percent")}
    if t == "memory":
        m = data.get("memory") or {}
        return {"persona": m.get("persona"),
                "selected": m.get("selected_items") or [],
                "candidates": m.get("candidates") or [],
                "clarifyCount": m.get("clarify_count") or 0,
                "longFacts": m.get("long_term_facts") or 0,
                "episodicRecalled": m.get("episodic_recalled") or 0}
    if t == "error":
        return {"text": _clip(data.get("text"), 200)}
    if t == "safety":
        return {"blocked": data.get("blocked"), "refusedTopics": data.get("refusedTopics") or [],
                "mode": data.get("mode")}
    if t == "plan":
        intents = data.get("intents") or {}
        return {"summary": intents.get("summary"),
                "confidence": intents.get("confidence"),
                "tasks": [(task.get("type"), task.get("deps"))
                          for task in (data.get("dag") or {}).get("tasks", [])]}
    if t == "handoff":
        return {"reason": _clip(data.get("reason"), 120)}
    if t == "context":
        return {"items": len(data.get("items") or []),
                "conflicts": (data.get("conflicts") or [])[:5]}
    if t == "status":
        return {"text": _clip(data.get("text"), 120)}
    return {"summary": json.dumps(data, ensure_ascii=False, default=str)[:200]}


class TraceRecorder:
    """按 session 收集并异步上报 trace 事件。"""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.count = 0
        self._tasks: list = []

    def record(self, ev: dict):
        if ev.get("type") in SKIP_EVENTS:
            return
        self.count += 1
        category = CATEGORY_MAP.get(ev.get("type", ""), "control")
        payload = _sanitize_payload(ev)
        self._tasks.append(asyncio.create_task(self._push(ev.get("type", ""), category, payload)))

    async def _push(self, event_type: str, category: str, payload: dict):
        try:
            async with httpx.AsyncClient(timeout=5, headers=config.JAVA_INTERNAL_HEADERS) as c:
                await c.post(f"{config.JAVA_API_URL}/internal/trace", json={
                    "sessionId": self.session_id, "eventType": event_type,
                    "category": category, "payload": payload,
                })
        except Exception as e:
            print(f"[trace] push failed: {e}", flush=True)

    async def wait(self):
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
            self._tasks.clear()
