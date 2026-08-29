# -*- coding: utf-8 -*-
"""会话记忆压缩测试：滑动窗口+摘要滚动合并 + describe 注入预算裁剪。"""
import asyncio
import unittest
from unittest.mock import patch

from app.memory import SessionMemory, _apply_budget


def _history(n: int) -> list[dict]:
    return [{"id": i, "role": "user", "content": f"消息{i}"} for i in range(1, n + 1)]


async def _fake_summarize(summary: str, rows: list[dict]) -> str:
    return f"摘要({len(rows)}条)"


class WindowTests(unittest.TestCase):
    def _run(self, coro):
        return asyncio.run(coro)

    def test_short_history_keeps_recent_without_summary(self):
        memory = SessionMemory("s1", 1)
        self._run(memory._compress_history(_history(10)))

        self.assertEqual(8, len(memory.recent_messages))
        self.assertNotIn("conversation_summary", memory.state)

    def test_long_history_rolls_older_messages_into_summary(self):
        memory = SessionMemory("s1", 1)
        with patch("app.memory._summarize", _fake_summarize):
            self._run(memory._compress_history(_history(39)))

        self.assertEqual("摘要(31条)", memory.state["conversation_summary"])
        self.assertEqual(31, memory.state["summary_upto_id"])
        self.assertEqual(8, len(memory.recent_messages))
        self.assertEqual("消息32", memory.recent_messages[0]["content"])

    def test_next_round_reuses_summary_without_re_summarizing(self):
        memory = SessionMemory("s1", 1)
        with patch("app.memory._summarize", _fake_summarize):
            self._run(memory._compress_history(_history(39)))
            first_summary = memory.state["conversation_summary"]
            # 之后只新增 1 条：仍在窗口容忍范围内，不再触发摘要
            rows = _history(40)
            self._run(memory._compress_history(rows))

        self.assertEqual(first_summary, memory.state["conversation_summary"])
        self.assertEqual(31, memory.state["summary_upto_id"])
        self.assertEqual(8, len(memory.recent_messages))
        self.assertEqual("消息40", memory.recent_messages[-1]["content"])

    def test_summarize_failure_keeps_recent_window(self):
        memory = SessionMemory("s1", 1)

        def broken(summary, lines):
            raise RuntimeError("llm down")

        with patch("app.memory._summarize_sync", broken):
            self._run(memory._compress_history(_history(39)))

        self.assertEqual(8, len(memory.recent_messages))
        self.assertNotIn("conversation_summary", memory.state)


class BudgetTests(unittest.TestCase):
    def _memory(self) -> SessionMemory:
        memory = SessionMemory("s1", 1)
        memory.recent_messages = [{"id": 1, "role": "user", "content": "推荐一件通勤外套"}]
        memory.long_facts = [{"predicate": "size_top", "value": "\"L\"",
                              "sourceType": "user_explicit"}]
        memory.episodic = [{"content": "长" * 600, "createdAt": "2026-08-29"}]
        memory.state["conversation_summary"] = "早" * 600
        return memory

    def test_over_budget_drops_lowest_priority_first(self):
        memory = self._memory()
        with patch("app.config.MEMORY_DESC_MAX_CHARS", 100):
            desc = memory.describe()

        self.assertIn("最近对话", desc)
        self.assertIn("size_top=L", desc)
        self.assertNotIn("相关历史记忆", desc)   # 优先级 3，先丢
        self.assertNotIn("更早对话摘要", desc)  # 优先级 4，最后丢

    def test_within_budget_keeps_everything(self):
        memory = self._memory()
        desc = memory.describe()

        self.assertIn("最近对话", desc)
        self.assertIn("相关历史记忆", desc)
        self.assertIn("更早对话摘要", desc)

    def test_apply_budget_empty_returns_placeholder(self):
        self.assertEqual("（暂无记忆）", _apply_budget([], 100))


if __name__ == "__main__":
    unittest.main()
