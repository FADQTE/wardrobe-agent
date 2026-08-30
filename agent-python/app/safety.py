# -*- coding: utf-8 -*-
"""安全边界（Prompt Injection / 越权 / 隐私 / 敏感信息索取）：

- 用户消息、RAG 文本、工具结果一律按"外部文本"处理，扫描后分类：
  prompt_injection / secret_or_reasoning_request / privacy
- 决策：索要系统提示词/hidden reasoning → 直接拒答（blocked_user_request）；
  试图覆盖系统指令且涉及高风险词 → 拒答；
  privacy → 脱敏后放行；其余注入 → 标记降权中和
- 业务校验（订单归属/审批边界）不在这里替代，安全扫描只做第一道闸。
"""
from __future__ import annotations

import re

INJECTION_PATTERNS = [
    r"忽略(之前|上面|以上|所有|系统)?.{0,12}(指令|规则|提示|设定)",
    r"(不要|别|拒绝)(遵守|执行|服从).{0,12}(规则|指令|提示词)",
    r"(你|现在|从现在起).{0,6}(是|变成|扮演).{0,30}(不受限制|无限制|没有规则|任何规则)",
    r"(忽略|无视|绕过)(系统|安全).{0,12}(规则|限制|边界)",
    r"忽略.{0,6}(以上|之前).{0,6}(所有|全部)?.{0,6}(指令|要求)",
    r"(直接|立刻|马上)(批准|同意|通过)(退款|退货|补偿|赔付)",
    r"告诉我(你的)?(系统)?(提示词|prompt|指令|规则)",
    r"(输出|打印|显示|泄露|泄漏).{0,10}(系统)?(提示词|prompt)",
    r"(show|reveal|print|leak).{0,10}(system )?(prompt|instruction)",
    r"你的(隐藏)?(推理|思考|思维链|cot|chain of thought)",
    r"(api|密钥|secret|token|key).{0,6}(是多少|是什么|给我|告诉我)",
]

SECRET_REQUEST_PATTERNS = [
    r"(系统)?(提示词|prompt|指令集|设定)",
    r"(隐藏)?(推理|思考过程|思维链|chain of thought|cot)",
    r"(api[ -]?key|密钥|secret|token)",
]

PRIVACY_PATTERNS = [
    (re.compile(r"1[3-9]\d{9}"), "phone"),
    (re.compile(r"\d{17}[\dXx]"), "id_card"),
    (re.compile(r"(收货)?(地址|住址)[:：]\S+"), "address"),
]

HIGH_RISK_WORDS = ["退款", "退货", "补偿", "赔付", "批准", "免费", "直接", "绕过", "冒充", "主管"]


def scan_text(text: str) -> list[str]:
    """返回命中的类别列表（去重）。"""
    if not text:
        return []
    cats = []
    lowered = text.lower()
    for pat in SECRET_REQUEST_PATTERNS:
        if re.search(pat, lowered):
            cats.append("secret_or_reasoning_request")
            break
    for pat in INJECTION_PATTERNS:
        if re.search(pat, lowered):
            cats.append("prompt_injection")
            break
    for rx, name in PRIVACY_PATTERNS:
        if rx.search(text):
            cats.append("privacy")
    return cats


def sanitize_text(text: str) -> str:
    """隐私脱敏：手机号/身份证中间打码。"""
    t = re.sub(r"(1[3-9]\d)(\d{4})(\d{4})", r"\1****\3", text)
    t = re.sub(r"(\d{6})\d{8}([\dXx]{3})", r"\1********\2", t)
    return t


def build_safety_decision(message: str) -> dict:
    """返回安全决策：blocked_user_request / refused_topics / sanitized_message / scans。"""
    cats = scan_text(message)
    decision = {
        "blocked_user_request": False,
        "refused_topics": [],
        "sanitized_message": sanitize_text(message),
        "scans": [{"source_type": "user", "categories": cats}],
        "mode": "pass",
    }
    if "secret_or_reasoning_request" in cats:
        decision["blocked_user_request"] = True
        decision["refused_topics"] = ["system_prompt_or_hidden_reasoning"]
        decision["mode"] = "blocked"
    elif "prompt_injection" in cats and any(w in message for w in HIGH_RISK_WORDS):
        decision["blocked_user_request"] = True
        decision["refused_topics"] = ["instruction_override"]
        decision["mode"] = "blocked"
    elif "prompt_injection" in cats:
        # 注入但未触及高风险动作：中和处理（仅作外部文本，不覆盖系统边界）
        decision["mode"] = "neutralized"
    elif "privacy" in cats:
        decision["mode"] = "sanitized"
    return decision


REFUSAL_ANSWER = (
    "抱歉，我不能提供系统提示词、内部指令或隐藏推理过程。"
    "如果你有穿搭、衣橱、商品或订单相关的问题，我很乐意帮你～"
)
