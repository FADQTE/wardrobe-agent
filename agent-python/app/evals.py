# -*- coding: utf-8 -*-
"""Eval 回归评测：/eval/run 跑固定用例（cases.yaml），断言事件/工具/禁用文本/引用。

走真实 Agent 代码路径（真实 ES/MCP/Java），不伪造模型回答或工具结果；
只报失败类别，不自动归因、不自动修复。
"""
from __future__ import annotations

from pathlib import Path

import yaml

from .graph import build_graph
from .memory import SessionMemory

CASES_FILE = Path(__file__).parent / "cases.yaml"


def load_cases() -> list[dict]:
    with open(CASES_FILE, encoding="utf-8") as f:
        return yaml.safe_load(f)["cases"]


async def run_case(case: dict) -> dict:
    from .mcp_client import get_mcp_tools
    await get_mcp_tools()  # 与 /api/chat 一致：评测走真实工具链路，需先建立 MCP 连接
    memory = SessionMemory(f"eval-{case['id']}", 1)
    graph = build_graph()
    inputs = {
        "session_id": f"eval-{case['id']}", "user_id": 1,
        "message": case["message"], "memory_desc": memory.describe(), "mem": memory,
        "runtime": {"trusted_for_model": {"member_level": "silver", "risk_level": "low",
                                          "page": "chat"},
                    "system_only": {"user_id": 1, "member_level": "silver", "risk_level": "low"},
                    "conflict_notes": [], "permission_decision": {"user_id": 1}},
    }
    events, final_state = [], None
    async for mode, chunk in graph.astream(inputs, stream_mode=["updates", "values"]):
        if mode == "updates":
            for _node, delta in chunk.items():
                events.extend(delta.get("events", []))
        else:
            final_state = chunk

    final_text = (final_state or {}).get("final_text", "") or ""
    event_types = [e.get("type") for e in events]
    tool_names = [e["data"].get("name") for e in events if e.get("type") == "tool"]
    rag_rules = []
    for e in events:
        if e.get("type") == "rag":
            rag_rules.extend(e["data"].get("rules", []))
    safety_blocked = any(e.get("type") == "safety" and e["data"].get("blocked") for e in events)
    clarify = bool((final_state or {}).get("intent_data", {}).get("needsClarification"))

    failures = []
    for t in case.get("must_events", []):
        if t not in event_types:
            failures.append(f"missing_event:{t}")
    for t in case.get("must_tools", []):
        if t not in tool_names:
            failures.append(f"missing_tool:{t}")
    for t in case.get("forbid_tools", []):
        if t in tool_names:
            failures.append(f"forbidden_tool:{t}")
    for t in case.get("forbid_text", []):
        if t in final_text:
            failures.append(f"forbidden_text:{t}")
    if case.get("expect_citation") and not rag_rules:
        failures.append("missing_citation")
    if case.get("expect_refusal") and not safety_blocked:
        failures.append("no_refusal")
    if case.get("expect_clarify") and not clarify:
        failures.append("no_clarify")

    return {
        "id": case["id"], "name": case["name"], "message": case["message"],
        "passed": not failures,
        "failures": failures,
        "evidence": {
            "events": event_types, "tools": tool_names,
            "citations": [r.get("title") for r in rag_rules[:3]],
            "safety_blocked": safety_blocked, "clarify": clarify,
            "answer_preview": final_text[:80],
        },
    }


async def run_all() -> dict:
    results = []
    for case in load_cases():
        try:
            results.append(await run_case(case))
        except Exception as e:
            results.append({"id": case.get("id"), "name": case.get("name"),
                            "passed": False, "failures": [f"exception:{type(e).__name__}:{e}"],
                            "evidence": {}})
    passed = sum(1 for r in results if r["passed"])
    return {
        "report": "eval_report_v1",
        "total": len(results), "passed": passed, "failed": len(results) - passed,
        "cases": results,
    }
