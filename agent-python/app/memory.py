# -*- coding: utf-8 -*-
"""Session Memory：人物形象/选中单品/候选搭配，落库到 Java 侧 chat_session。

会话记忆压缩（文档 §5/§17）：最近 N 轮保留原文，更早的历史滚动合并为
conversation_summary 存入 state；注入 LLM 的记忆区按优先级做字符预算裁剪。
"""
from __future__ import annotations

import asyncio
import copy
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

SUMMARY_SYSTEM = ("你是电商对话记忆压缩器。把历史对话合并成一段不超过 200 字的摘要，"
                  "保留：用户需求/场景、身材尺码、预算、偏好、已完成的操作（下单/收藏/生图）、"
                  "未决问题。丢弃寒暄和重复内容，只输出摘要正文。")


class SessionMemory:
    def __init__(self, session_id: str, user_id: int):
        self.session_id = session_id
        self.user_id = user_id
        # 深拷贝：DEFAULT_MEMORY 的嵌套 list 不能跨会话共享（否则污染新会话）
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
                messages_req = c.get(f"{config.JAVA_API_URL}/chat/sessions/{self.session_id}/messages",
                                     params={"limit": 200})
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
                    rows = [row for row in rows
                            if row.get("role") in ("user", "assistant") and row.get("content")]
                    await self._compress_history(rows)
        except Exception as e:
            # 加载失败等于本轮裸跑无记忆，必须留下日志证据而不是静默吞掉
            print(f"[memory] load failed: {e}")

    async def _compress_history(self, rows: list[dict]):
        """滑动窗口 + 摘要：窗口外更早的新历史滚动合并进 conversation_summary。"""
        recent_turns, threshold = config.MEMORY_RECENT_TURNS, config.MEMORY_SUMMARY_THRESHOLD
        summary = self.state.get("conversation_summary") or ""
        summary_upto = int(self.state.get("summary_upto_id") or 0)
        new_rows = [row for row in rows if int(row.get("id") or 0) > summary_upto]
        if len(new_rows) > recent_turns + threshold:
            to_summarize = new_rows[:-recent_turns]
            merged = await _summarize(summary, to_summarize)
            if merged:
                summary = merged
                summary_upto = int(to_summarize[-1].get("id") or summary_upto)
                self.state["conversation_summary"] = summary
                self.state["summary_upto_id"] = summary_upto
        self.recent_messages = [
            {"id": row.get("id"), "role": row.get("role"), "content": row.get("content") or ""}
            for row in new_rows[-recent_turns:]
        ]

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
        """把记忆压缩成给 LLM 的上下文描述，按优先级做字符预算裁剪。"""
        from . import long_memory
        # priority 越小越关键：预算不足时从大往小丢
        parts: list[tuple[int, str]] = []
        if self.state.get("conversation_summary"):
            parts.append((4, f"更早对话摘要: {self.state['conversation_summary']}"))
        if self.recent_messages:
            dialogue = []
            for row in self.recent_messages:
                role = "用户" if row["role"] == "user" else "助手"
                content = " ".join(str(row["content"]).split())[:240]
                dialogue.append(f"{role}: {content}")
            parts.append((0, "最近对话（按时间顺序）:\n" + "\n".join(dialogue)))
        if self.long_facts:
            facts = long_memory.render_facts(self.long_facts)
            if facts:
                parts.append((1, f"用户长期记忆（事实/偏好）: {facts}"))
        if self.episodic:
            episodes = long_memory.render_episodes(self.episodic)
            if episodes:
                parts.append((3, "相关历史记忆（仅线索，实时状态以业务系统为准）:\n" + episodes))
        if self.state["persona"]:
            p = self.state["persona"]
            parts.append((2, f"用户形象: {p}"))
        if self.state["selected_items"]:
            names = "、".join(i["name"] for i in self.state["selected_items"])
            parts.append((2, f"已选单品: {names}"))
        if self.state["candidates"]:
            last = self.state["candidates"][-1]
            parts.append((2, f"上一套候选搭配: {last.get('name')}（{len(last.get('items', []))} 件）"))
        if self.state["last_image"]:
            parts.append((2, f"已生成效果图: {self.state['last_image'].get('label')}"))
        return _apply_budget(parts, config.MEMORY_DESC_MAX_CHARS)


def _apply_budget(parts: list[tuple[int, str]], budget: int) -> str:
    """Context Builder（文档 §17）：优先保留高优先级记忆，超出预算从低优先级丢弃。"""
    kept = list(parts)
    total = lambda: sum(len(text) + 1 for _, text in kept)
    while kept and total() > budget:
        drop_index = max(range(len(kept)), key=lambda i: kept[i][0])
        if all(p == kept[drop_index][0] for p, _ in kept):
            # 全部同优先级仍超预算：截断尾部
            merged, size = [], 0
            for _, text in kept:
                merged.append(text)
                size += len(text) + 1
                if size >= budget:
                    break
            return "\n".join(merged)[:budget]
        kept.pop(drop_index)
    return "\n".join(text for _, text in kept) or "（暂无记忆）"


async def _summarize(existing_summary: str, rows: list[dict]) -> str:
    """LLM 压缩历史对话；失败返回空串（保持旧摘要，仅丢失本次合并）。"""
    if not rows:
        return existing_summary
    lines = [f"{'用户' if r['role'] == 'user' else '助手'}: "
             f"{' '.join(str(r['content']).split())[:200]}" for r in rows]
    try:
        return await asyncio.to_thread(_summarize_sync, existing_summary, lines)
    except Exception as e:
        print(f"[memory] summarize failed: {e}")
        return ""


def _summarize_sync(existing_summary: str, lines: list[str]) -> str:
    from .llm import get_llm
    user = "已有摘要:\n" + (existing_summary or "（无）") + \
           "\n\n新增对话:\n" + "\n".join(lines) + "\n\n请输出合并后的摘要。"
    text = get_llm().chat(SUMMARY_SYSTEM, user)
    return " ".join(text.split())[:400]


def _json(obj):
    return json.dumps(obj, ensure_ascii=False, default=str)
