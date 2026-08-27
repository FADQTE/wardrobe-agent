# -*- coding: utf-8 -*-
"""意图识别：结构化输出把自然语言拆为任务 DAG；LLM 不可用时降级规则解析。"""
from __future__ import annotations

from . import config
from .llm import get_llm, parse_json_loose
from .mock_intent import parse_mock

INTENT_SYSTEM = """你是「潮引智能衣橱商城」的穿搭客服编排器。把用户的自然语言请求拆解为可执行的任务依赖 DAG。

可用任务类型：
- wardrobe: 查询用户个人衣橱单品。params: {tags: [颜色/品类关键词，如 "白色","衬衫"]}
- rag: 检索穿搭规则(outfit)。params: {query: 场景描述, tags: [季节/风格标签]}
- rule_query: 查询商城活动规则(activity，满减/折扣/优惠)。params: {query}
- product: 检索商城在售商品。params: {keyword, category, color, season, style, maxPrice}
- image: 生成换装效果图。params: {label} —— 必须用 deps 依赖 wardrobe/rag/product
- order: 创建订单购买商品。params: {productIds: []} —— deps 依赖 product
- favorite: 收藏商品。params: {productIds: []} —— deps 依赖 product
- clarify: 需要向用户澄清。params: {question}

拆解规则：
1. 信息不足（缺场景/单品/人物等）→ 输出 clarify 任务且 needsClarification=true，不输出其他任务
2. 意图含糊时 confidence 取 0.5 以下并触发澄清
3. "生成效果图"类任务 deps 必须引用其依赖的 wardrobe/rag/product 任务 id
4. 任务 id 用 t1,t2,... 顺序编号；没有依赖的 deps 用 []
5. "预算X以内" → product 任务 maxPrice=X；"换成商城在售的" → product 任务

输出 JSON（不要输出其他内容）：
{"confidence": 0.9, "needsClarification": false, "clarifyQuestion": "", "summary": "一句话概括", "tasks": [{"id":"t1","type":"wardrobe","params":{},"deps":[]}]}
"""


def parse_intent(message: str, memory_desc: str) -> dict:
    """返回 intent dict；LLM 异常时降级 mock。"""
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


def _normalize(intent: dict) -> dict:
    intent.setdefault("confidence", 0.8)
    intent.setdefault("needsClarification", False)
    intent.setdefault("clarifyQuestion", "")
    intent.setdefault("summary", "")
    tasks = []
    for i, t in enumerate(intent.get("tasks", [])):
        if not isinstance(t, dict) or "type" not in t:
            continue
        t.setdefault("id", f"t{i + 1}")
        t.setdefault("params", {})
        t.setdefault("deps", [])
        tasks.append(t)
    intent["tasks"] = tasks
    return intent
