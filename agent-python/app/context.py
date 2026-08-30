# -*- coding: utf-8 -*-
"""Runtime Context + Context Builder（轻量版）：

- Runtime Context 双通道：trusted_for_model（模型可见安全摘要）/ system_only（权限校验用）
- 用户自称（"我是 VIP"等）只是待验证文本，不能覆盖系统事实 → conflict_notes
- Context Builder：把用户消息/Runtime/Session Memory/RAG/Tool 结果统一为 ContextItem，
  标注 source 与 trust_level，输出组装摘要与冲突解析结果。
"""
from __future__ import annotations

CLAIM_PATTERNS = [
    ("我是|我是银卡|我是金卡|我是黑卡|是VIP|是会员", "identity_claim"),
    ("我是主管|我是管理员|我是老板|我是售后|我是运营", "role_claim"),
]


class RuntimeContext:
    def __init__(self, user_id: int, member_level: str = "", risk_level: str = "",
                 page_context: dict | None = None, user_message: str = ""):
        self.user_id = user_id
        self.member_level = member_level or "unknown"
        self.risk_level = risk_level or "low"
        self.page_context = page_context or {}
        self.user_message = user_message

    def build(self) -> dict:
        conflicts = []
        if "identity_claim" in _claims(self.user_message) and self.member_level == "unknown":
            conflicts.append({"claim": "用户自称身份", "system_fact": "member_level=unknown",
                              "resolution": "按系统事实 unknown 处理，不升级会员等级"})
        if "role_claim" in _claims(self.user_message):
            conflicts.append({"claim": "用户自称管理角色", "system_fact": "runtime 无管理角色",
                              "resolution": "拒绝按管理角色处理，写操作仍走业务校验"})
        trusted = {
            "nickname": "小潮", "member_level": self.member_level,
            "risk_level": self.risk_level, "page": self.page_context.get("page", "chat"),
        }
        system_only = {
            "user_id": self.user_id, "member_level": self.member_level,
            "risk_level": self.risk_level,
        }
        return {
            "trusted_for_model": trusted,
            "system_only": system_only,
            "conflict_notes": conflicts,
            "permission_decision": {"user_id": self.user_id, "reason": "runtime_supplied"},
        }


def _claims(text: str) -> list:
    import re
    hits = []
    for pat, name in CLAIM_PATTERNS:
        if re.search(pat, text):
            hits.append(name)
    return hits


class ContextItem:
    def __init__(self, source: str, content: str, trust_level: str, selected: bool = True):
        self.source = source
        self.content = content
        self.trust_level = trust_level  # high | medium | low
        self.selected = selected

    def as_dict(self):
        return {"source": self.source, "trust_level": self.trust_level,
                "content": (self.content or "")[:120], "selected": self.selected}


def build_context_report(runtime: dict, memory_desc: str, rag_hits: int, tool_count: int,
                         user_message: str) -> dict:
    """组装本轮上下文：按可信度分级排序，输出给模型前的结构摘要。"""
    items = [
        ContextItem("runtime_context", _sum(runtime), "high"),
        ContextItem("tool_observation", f"工具调用 {tool_count} 次（实时事实）", "high") if tool_count else None,
        ContextItem("rag_knowledge", f"RAG 命中 {rag_hits} 条（稳定知识）", "medium") if rag_hits else None,
        ContextItem("session_memory", memory_desc, "medium"),
        ContextItem("user_message", user_message[:120], "low"),
    ]
    items = [i for i in items if i is not None]
    return {
        "items": [i.as_dict() for i in items],
        "conflicts": runtime.get("conflict_notes", []),
        "rules": "身份看 Runtime Context、实时事实看 Tool、流程看 Workflow、政策看 RAG、记忆只做线索",
    }


def _sum(runtime: dict) -> str:
    t = runtime.get("trusted_for_model", {})
    return f"member_level={t.get('member_level')} risk_level={t.get('risk_level')} page={t.get('page')}"
