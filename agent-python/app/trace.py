# -*- coding: utf-8 -*-
"""Trace 记录器：把每轮执行的公开证据持久化到 Java 侧 trace_event 表。

只上报公开摘要（事件名/工具名/引用标识/路径），不上报系统提示词、CoT、密钥、隐私原文。
"""
from __future__ import annotations

import asyncio
import json

import httpx

from . import config

CATEGORY_MAP = {
    "plan": "control", "status": "control", "intent": "control",
    "tool": "fact", "product": "fact", "image_progress": "fact", "image": "fact",
    "rag": "knowledge", "outfit": "result", "memory": "control",
    "token": "result", "done": "result", "error": "control",
    "safety": "safety", "handoff": "control", "context": "control",
}


def _sanitize_payload(ev: dict) -> dict:
    """构造脱敏载荷：只留事件摘要，不存隐私原文与系统提示词。"""
    data = ev.get("data") or {}
    if ev.get("type") == "tool":
        return {"name": data.get("name"), "ok": data.get("ok"),
                "summary": (data.get("summary") or "")[:200]}
    if ev.get("type") == "rag":
        rules = data.get("rules") or []
        return {"query": (data.get("query") or "")[:80], "hits": len(rules),
                "citations": [r.get("title") for r in rules[:5]]}
    if ev.get("type") in ("token", "image"):
        return {}
    if ev.get("type") == "error":
        return {"text": (data.get("text") or "")[:200]}
    if ev.get("type") == "safety":
        return {"blocked": data.get("blocked"), "refusedTopics": data.get("refusedTopics") or [],
                "mode": data.get("mode")}
    if ev.get("type") == "plan":
        return {"intents": (data.get("intents") or {}).get("summary"),
                "tasks": [(t.get("type"), t.get("deps")) for t in (data.get("dag") or {}).get("tasks", [])]}
    if ev.get("type") == "handoff":
        return {"reason": (data.get("reason") or "")[:120]}
    if ev.get("type") == "context":
        return {"items": len(data.get("items") or []),
                "conflicts": (data.get("conflicts") or [])[:5]}
    if ev.get("type") == "status":
        return {"text": (data.get("text") or "")[:120]}
    return {"summary": json.dumps(data, ensure_ascii=False, default=str)[:200]}


class TraceRecorder:
    """按 session 收集并异步上报 trace 事件。"""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.count = 0
        self._tasks: list = []

    def record(self, ev: dict):
        self.count += 1
        category = CATEGORY_MAP.get(ev.get("type", ""), "control")
        payload = _sanitize_payload(ev)
        self._tasks.append(asyncio.create_task(self._push(ev.get("type", ""), category, payload)))

    async def _push(self, event_type: str, category: str, payload: dict):
        try:
            async with httpx.AsyncClient(timeout=5) as c:
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
