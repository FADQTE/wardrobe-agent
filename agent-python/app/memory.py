# -*- coding: utf-8 -*-
"""Session Memory：人物形象/选中单品/候选搭配，落库到 Java 侧 chat_session。"""
from __future__ import annotations

import httpx

from . import config

DEFAULT_MEMORY = {
    "persona": None,          # {name, avatar, height, scene}
    "selected_items": [],     # [{id, name, imageUrl, source: wardrobe|mall, price?}]
    "candidates": [],         # 候选搭配 [{name, items: [], reason, ruleSources}]
    "last_image": None,       # {url, label, taskId}
    "clarify_count": 0,
}


class SessionMemory:
    def __init__(self, session_id: str, user_id: int):
        self.session_id = session_id
        self.user_id = user_id
        # 深拷贝：DEFAULT_MEMORY 的嵌套 list 不能跨会话共享（否则污染新会话）
        import copy
        self.state = copy.deepcopy(DEFAULT_MEMORY)

    async def load(self):
        try:
            async with httpx.AsyncClient(timeout=5) as c:
                r = await c.get(f"{config.JAVA_API_URL}/chat/sessions/{self.session_id}")
                if r.status_code == 200:
                    data = r.json().get("data", {})
                    state = data.get("state")
                    if state:
                        import json
                        self.state.update(json.loads(state))
        except Exception:
            pass

    async def save(self):
        try:
            async with httpx.AsyncClient(timeout=5) as c:
                await c.post(f"{config.JAVA_API_URL}/chat/sessions", json={
                    "id": self.session_id, "userId": self.user_id,
                    "state": _json(self.state),
                })
        except Exception as e:
            print(f"[memory] save failed: {e}")

    def select(self, items: list[dict]):
        """记录本轮选中的单品（保留最近 8 件）。"""
        known = {i.get("name") for i in self.state["selected_items"]}
        for it in items:
            if it.get("name") and it["name"] not in known:
                self.state["selected_items"].append(it)
        self.state["selected_items"] = self.state["selected_items"][-8:]

    def set_candidates(self, outfit: dict):
        self.state["candidates"].append(outfit)
        self.state["candidates"] = self.state["candidates"][-5:]

    def describe(self) -> str:
        """把记忆压缩成给 LLM 的上下文描述。"""
        parts = []
        if self.state["persona"]:
            p = self.state["persona"]
            parts.append(f"用户形象: {p}")
        if self.state["selected_items"]:
            names = "、".join(i["name"] for i in self.state["selected_items"])
            parts.append(f"已选单品: {names}")
        if self.state["candidates"]:
            last = self.state["candidates"][-1]
            parts.append(f"上一套候选搭配: {last.get('name')}（{len(last.get('items', []))} 件）")
        if self.state["last_image"]:
            parts.append(f"已生成效果图: {self.state['last_image'].get('label')}")
        return "\n".join(parts) or "（暂无记忆）"


def _json(obj):
    import json
    return json.dumps(obj, ensure_ascii=False, default=str)
