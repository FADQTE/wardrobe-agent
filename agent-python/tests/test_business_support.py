# -*- coding: utf-8 -*-
import json
import unittest
from unittest.mock import AsyncMock, patch

from app.graph import _compose_commerce_support
from app.intent import parse_intent
from app.memory import SessionMemory
from app.tasks import do_aftersale, do_order_query


class BusinessIntentTests(unittest.TestCase):
    def test_refund_question_never_falls_into_activity_rule(self):
        intent = parse_intent("退款支持吗？", "（暂无记忆）")

        self.assertEqual("aftersale", intent["tasks"][0]["type"])
        self.assertEqual("policy", intent["tasks"][0]["params"]["action"])

    def test_order_and_logistics_are_separate_intents(self):
        order = parse_intent("帮我查一下我的订单", "（暂无记忆）")
        logistics = parse_intent("查一下 CY202608150001 的物流", "（暂无记忆）")

        self.assertEqual("order_query", order["tasks"][0]["type"])
        self.assertEqual("logistics", logistics["tasks"][0]["type"])
        self.assertEqual("CY202608150001", logistics["tasks"][0]["params"]["orderNo"])


class RecentMemoryTests(unittest.TestCase):
    def test_recent_dialogue_is_included_in_context(self):
        memory = SessionMemory("session-1", 1)
        memory.recent_messages = [
            {"role": "user", "content": "帮我查一下我的订单"},
            {"role": "assistant", "content": "查到一笔待支付订单"},
        ]

        description = memory.describe()

        self.assertIn("最近对话（按时间顺序）", description)
        self.assertIn("用户: 帮我查一下我的订单", description)
        self.assertIn("助手: 查到一笔待支付订单", description)


class BusinessToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_refund_policy_uses_after_sale_tool_and_does_not_claim_success(self):
        policy = {
            "unpaidOrder": "待支付订单可取消。",
            "paidUnshipped": "已支付未发货可申请退款。",
            "shippedOrCompleted": "已发货需申请退货退款。",
            "exclusions": "影响二次销售的商品除外。",
            "processing": "提交后进入人工审核。",
        }
        with patch("app.tasks.call_tool", new=AsyncMock(return_value=json.dumps(policy, ensure_ascii=False))) as tool:
            result = await do_aftersale(
                {"id": "t1", "params": {"action": "policy"}}, [], None,
                {"user_id": 1, "session_id": "session-1"},
            )

        tool.assert_awaited_once_with("getAfterSalePolicy", {})
        answer = _compose_commerce_support({"results": [result]})
        self.assertIn("当前没有创建退款申请", answer)
        self.assertNotIn("已退款成功", answer)
        self.assertNotIn("正在生效的活动", answer)

    async def test_order_query_uses_current_user(self):
        orders = [{"orderNo": "CY202608150001", "totalAmount": 199, "status": "paid"}]
        with patch("app.tasks.call_tool", new=AsyncMock(return_value=orders)) as tool:
            result = await do_order_query(
                {"id": "t1", "params": {}}, [], None,
                {"user_id": 7, "session_id": "session-1"},
            )

        tool.assert_awaited_once_with("listOrders", {"userId": 7})
        self.assertEqual(orders, result["data"]["orders"])


if __name__ == "__main__":
    unittest.main()
