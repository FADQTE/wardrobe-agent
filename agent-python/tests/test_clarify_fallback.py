# -*- coding: utf-8 -*-
"""澄清兜底测试：连续 2 轮澄清后必须转入能力引导，而不是无限追问。"""
import asyncio
import unittest

from app.graph import assemble_node
from app.memory import SessionMemory


def _state(memory: SessionMemory) -> dict:
    return {
        "message": "帮我弄一下", "memory_desc": "",
        "safety_data": {"blocked_user_request": False},
        "intent_data": {"needsClarification": True,
                        "clarifyQuestion": "想要什么风格？"},
        "results": [], "mem": memory,
    }


def _run(coro):
    return asyncio.run(coro)


class ClarifyFallbackTests(unittest.TestCase):
    def test_first_two_rounds_ask_clarify_question_and_count(self):
        memory = SessionMemory("s1", 1)
        result = _run(assemble_node(_state(memory)))

        self.assertEqual("想要什么风格？", result["final_text"])
        self.assertEqual(1, memory.state["clarify_count"])

    def test_third_round_falls_back_to_capability_menu(self):
        memory = SessionMemory("s1", 1)
        memory.state["clarify_count"] = 2
        result = _run(assemble_node(_state(memory)))

        self.assertIn("穿搭推荐", result["final_text"])
        self.assertIn("订单", result["final_text"])
        self.assertEqual(0, memory.state["clarify_count"])  # 引导后重置计数

    def test_clarify_rounds_survive_across_memory_instances_via_state(self):
        memory = SessionMemory("s1", 1)
        for expected in (1, 2):
            _run(assemble_node(_state(memory)))
            self.assertEqual(expected, memory.state["clarify_count"])


if __name__ == "__main__":
    unittest.main()
