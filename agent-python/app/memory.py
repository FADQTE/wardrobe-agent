# -*- coding: utf-8 -*-
"""Session Memory：人物形象/选中单品/候选搭配，落库到 Java 侧 chat_session。"""
from __future__ import annotations

import asyncio
import json

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
        self.exists = False
        # 最近对话只用于当轮上下文，不写回 session state，避免与 chat_message 重复持久化。
        self.recent_messages: list[dict] = []
        # 长期记忆（当轮读取视图，不入 session state）：事实走 MySQL 精确查询，
        # 情景走 ES 混合召回，均为 user_id 隔离。
        self.long_facts: list[dict] = []
        self.episodic: list[dict] = []

    async def load(self):
        try:
            async with httpx.AsyncClient(timeout=5) as c:
                state_req = c.get(f"{config.JAVA_API_URL}/chat/sessions/{self.session_id}")
                messages_req = c.get(f"{config.JAVA_API_URL}/chat/sessions/{self.session_id}/messages")
                state_res, messages_res = await asyncio.gather(
                    state_req, messages_req, return_exceptions=True,
                )
                # 两份记忆互相独立：会话状态或聊天记录任一接口临时失败时，
                # 仍然保留另一份可用上下文，不能因为一个异常把两份都静默丢掉。
                if isinstance(state_res, httpx.Response) and state_res.status_code == 200:
                    data = state_res.json().get("data", {})
                    self.exists = bool(data)
                    state = data.get("state")
                    if state:
                        self.state.update(json.loads(state))
                if isinstance(messages_res, httpx.Response) and messages_res.status_code == 200:
                    rows = messages_res.json().get("data") or []
                    self.recent_messages = [
                        {"role": row.get("role"), "content": row.get("content") or ""}
                        for row in rows[-8:]
                        if row.get("role") in ("user", "assistant") and row.get("content")
                    ]
        except Exception:
            pass

    async def load_long_term(self, message: str):
        """按意图路由读取长期记忆：事实常载（小而准），情景记忆仅历史回溯类提问召回。"""
        from . import long_memory
        self.long_facts = await long_memory.fetch_facts(self.user_id)
        if long_memory.wants_episodic_recall(message):
            rows = await asyncio.to_thread(
                long_memory.search_episodes, message, self.user_id, 4)
            self.episodic = rows
            used = [r.get("id") for r in rows if r.get("id")]
            if used:
                long_memory.touch_memories(used)

    async def save(self, title: str | None = None):
        try:
            payload = {
                "id": self.session_id, "userId": self.user_id,
                "state": _json(self.state),
            }
            if title:
                payload["title"] = title[:128]
            async with httpx.AsyncClient(timeout=5) as c:
                r = await c.post(f"{config.JAVA_API_URL}/chat/sessions", json=payload)
                r.raise_for_status()
                self.exists = True
        except Exception as e:
            print(f"[memory] save failed: {e}")

    async def append_message(self, role: str, content: str, meta: dict | None = None):
        """把可恢复的对话正文与展示元数据写入 Java 侧 chat_message。"""
        try:
            async with httpx.AsyncClient(timeout=5) as c:
                r = await c.post(f"{config.JAVA_API_URL}/chat/messages", json={
                    "sessionId": self.session_id,
                    "role": role,
                    "content": content,
                    "meta": _json(meta or {}),
                })
                r.raise_for_status()
        except Exception as e:
            # 持久化失败不能中断当轮回复，但需要在服务日志中留下明确证据。
            print(f"[memory] append message failed: {e}")

    def select(self, items: list[dict]):
        """记录本轮选中的单品（保留最近 8 件）。"""
        known = {i.get("name") for i in self.state["selected_items"]}
        for it in items:
            if it.get("name") and it["name"] not in known:
                self.state["selected_items"].append(it)
        self.state["selected_items"] = self.state["selected_items"][-8:]

    def transcript(self, limit: int = 6) -> str:
        """最近对话的紧凑转写，供长期记忆抽取提供上下文。"""
        lines = []
        for row in self.recent_messages[-limit:]:
            role = "用户" if row["role"] == "user" else "助手"
            lines.append(f"{role}: {' '.join(str(row['content']).split())[:160]}")
        return "\n".join(lines)

    def set_candidates(self, outfit: dict):
        self.state["candidates"].append(outfit)
        self.state["candidates"] = self.state["candidates"][-5:]

    def describe(self) -> str:
        """把记忆压缩成给 LLM 的上下文描述。"""
        from . import long_memory
        parts = []
        if self.recent_messages:
            dialogue = []
            for row in self.recent_messages:
                role = "用户" if row["role"] == "user" else "助手"
                content = " ".join(str(row["content"]).split())[:240]
                dialogue.append(f"{role}: {content}")
            parts.append("最近对话（按时间顺序）:\n" + "\n".join(dialogue))
        if self.long_facts:
            facts = long_memory.render_facts(self.long_facts)
            if facts:
                parts.append(f"用户长期记忆（事实/偏好）: {facts}")
        if self.episodic:
            episodes = long_memory.render_episodes(self.episodic)
            if episodes:
                parts.append("相关历史记忆（仅线索，实时状态以业务系统为准）:\n" + episodes)
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
    return json.dumps(obj, ensure_ascii=False, default=str)
