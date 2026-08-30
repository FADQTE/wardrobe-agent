# -*- coding: utf-8 -*-
"""意图识别：结构化输出把自然语言拆为任务 DAG；LLM 不可用时降级规则解析。"""
from __future__ import annotations

import re

from . import config
from .llm import get_llm, parse_json_loose
from .mock_intent import parse_mock

# 任务白名单：模型输出必须落回这里，防幻想工具/未注册路径
VALID_TASK_TYPES = {
    "wardrobe", "rag", "rule_query", "product", "image", "order", "favorite",
    "order_query", "logistics", "aftersale", "clarify",
}
# 写动作/高风险任务：进入后 risk_level=high
WRITE_TASK_TYPES = {"order"}

INTENT_SYSTEM = """你是智能衣橱的穿搭客服编排器。把用户的自然语言请求拆解为可执行的任务依赖 DAG。

可用任务类型：
- wardrobe: 查询用户个人衣橱单品。params: {tags: [颜色/品类关键词，如 "白色","衬衫"]}
- rag: 检索穿搭规则(outfit)。params: {query: 场景描述, tags: [季节/风格标签]}
- rule_query: 查询商城活动规则(activity，满减/折扣/优惠)。params: {query}
- product: 检索商城在售商品。params: {keyword, category, color, season, style, maxPrice}
- image: 生成换装效果图。params: {label} —— 必须用 deps 依赖 wardrobe/rag/product
- order: 创建订单购买商品。params: {productIds: []} —— deps 依赖 product
- favorite: 收藏商品。params: {productIds: []} —— deps 依赖 product
- order_query: 查询当前用户订单列表或指定订单。params: {orderNo，可为空}
- logistics: 查询指定订单物流。params: {orderNo；缺少时允许为空并查询最近订单}
- aftersale: 查询退换货/退款政策或售后进度。params: {action: policy|query|guide}。不得承诺退款成功，不得把售后问题路由到 rule_query
- clarify: 需要向用户澄清。params: {question}

拆解规则：
1. 信息不足（缺场景/单品/人物等）→ 输出 clarify 任务且 needsClarification=true，不输出其他任务
2. 意图含糊时 confidence 取 0.5 以下并触发澄清
3. "生成效果图"类任务 deps 必须引用其依赖的 wardrobe/rag/product 任务 id
4. 任务 id 用 t1,t2,... 顺序编号；没有依赖的 deps 用 []
5. "预算X以内" → product 任务 maxPrice=X；"换成商城在售的" → product 任务
6. "退款支持吗/能退吗/退换货规则" → aftersale(action=policy)；"售后进度" → aftersale(action=query)
7. "帮我查订单/我的订单" → order_query；"物流/快递到哪" → logistics。订单号格式通常为 CY 加数字

输出 JSON（不要输出其他内容）：
{"confidence": 0.9, "needsClarification": false, "clarifyQuestion": "", "summary": "一句话概括", "tasks": [{"id":"t1","type":"wardrobe","params":{},"deps":[]}]}
"""


def parse_intent(message: str, memory_desc: str) -> dict:
    """返回 intent dict；LLM 异常时降级 mock。"""
    # 订单/售后属于边界清晰的业务意图，先用确定性路由锁定，避免模型被有限任务白名单
    # 逼迫成“活动规则”等相邻但错误的任务。穿搭等开放问题仍交给 LLM。
    business = _parse_business_intent(message)
    if business:
        return business
    if not config.MOCK_AGENT and config.LLM_API_KEY:
        try:
            user = f"用户消息: {message}\n\n会话记忆:\n{memory_desc}\n\n请拆解任务。"
            intent = get_llm().chat_json(INTENT_SYSTEM, user)
            intent = _normalize(intent)
            if intent.get("tasks"):
                return intent
        except Exception as e:
            print(f"[intent] llm failed, fallback mock: {e}")
    return parse_mock(message, memory_desc)


def _parse_business_intent(message: str) -> dict | None:
    text = (message or "").strip()
    order_match = re.search(r"CY\d{8,}", text, re.IGNORECASE)
    order_no = order_match.group(0).upper() if order_match else ""

    aftersale_words = ("退款", "退货", "换货", "退换", "售后", "质量问题", "不想要了")
    if any(word in text for word in aftersale_words):
        if any(word in text for word in ("进度", "状态", "处理到哪", "审核到哪", "售后单")):
            action = "query"
            summary = "查询售后申请进度"
        elif any(word in text for word in ("申请", "我要退", "帮我退", "现在退")):
            action = "guide"
            summary = "退换货申请引导"
        else:
            action = "policy"
            summary = "查询退换货与退款政策"
        return {
            "confidence": 0.99, "needsClarification": False, "clarifyQuestion": "",
            "summary": summary,
            "tasks": [{"id": "t1", "type": "aftersale",
                       "params": {"action": action, "orderNo": order_no}, "deps": []}],
            "risk_level": "medium", "fallback_policy": "tool_first",
        }

    if any(word in text for word in ("物流", "快递", "发货了吗", "到哪了", "配送")):
        return {
            "confidence": 0.98, "needsClarification": False, "clarifyQuestion": "",
            "summary": "查询订单物流",
            "tasks": [{"id": "t1", "type": "logistics",
                       "params": {"orderNo": order_no}, "deps": []}],
            "risk_level": "low", "fallback_policy": "tool_first",
        }

    order_query = order_no or any(word in text for word in (
        "我的订单", "查订单", "查询订单", "订单状态", "订单记录", "买过什么",
    ))
    if order_query and not any(word in text for word in ("下单", "购买", "买一个", "买一件")):
        return {
            "confidence": 0.98, "needsClarification": False, "clarifyQuestion": "",
            "summary": "查询订单",
            "tasks": [{"id": "t1", "type": "order_query",
                       "params": {"orderNo": order_no}, "deps": []}],
            "risk_level": "low", "fallback_policy": "tool_first",
        }
    return None


def _normalize(intent: dict) -> dict:
    intent.setdefault("confidence", 0.8)
    intent.setdefault("needsClarification", False)
    intent.setdefault("clarifyQuestion", "")
    intent.setdefault("summary", "")
    tasks = []
    for i, t in enumerate(intent.get("tasks", [])):
        if not isinstance(t, dict) or "type" not in t:
            continue
        # 任务白名单：模型幻想/未知类型一律丢弃，防止混入未注册执行路径
        if t["type"] not in VALID_TASK_TYPES:
            continue
        t.setdefault("id", f"t{i + 1}")
        t.setdefault("params", {})
        t.setdefault("deps", [])
        tasks.append(t)
    intent["tasks"] = tasks
    # RoutePlan 契约：风险等级 + 兜底策略（下单/写动作视为高风险）
    has_write = any(t.get("type") in WRITE_TASK_TYPES for t in tasks)
    intent.setdefault("risk_level", "high" if has_write else "low")
    intent.setdefault("fallback_policy", "tool_first")
    return intent
