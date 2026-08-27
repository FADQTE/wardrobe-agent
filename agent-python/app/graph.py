# -*- coding: utf-8 -*-
"""LangGraph 编排：意图识别 → 依赖 DAG 执行（无依赖并行）→ 汇总回复。

图结构：intent → execute → assemble。
- intent：结构化输出把自然语言拆为任务 DAG（依赖用 deps 引用任务 id）
- execute：按拓扑层级执行——同层无依赖任务用 asyncio.gather 并行，
  依赖任务在其依赖完成后的下一层执行
- assemble：汇总任务结果为最终回复（搭配建议 + 规则来源 + 会话记忆）

注：langgraph 0.2.74 的 Send 分支状态相互隔离（无法跨分支 join），
且节点内无 runnable config 上下文，因此并行放在 execute 节点内部实现。
"""
from __future__ import annotations

import asyncio
import json
import operator
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph

from . import config
from .intent import parse_intent
from .llm import get_llm
from .tasks import execute_task

TASK_NAMES = {
    "wardrobe": "衣橱查询", "rag": "穿搭规则RAG", "rule_query": "活动规则查询",
    "product": "商城商品检索", "image": "换装生图", "order": "创建订单",
    "favorite": "收藏商品", "clarify": "澄清",
}


class AgentState(TypedDict, total=False):
    session_id: str
    user_id: int
    message: str
    memory_desc: str
    mem: Any
    intent_data: dict
    tasks: list
    results: Annotated[list, operator.add]
    events: Annotated[list, operator.add]
    final_text: str


# ---------- 节点 ----------

async def intent_node(state: AgentState) -> dict:
    intent = parse_intent(state["message"], state["memory_desc"])
    tasks = intent.get("tasks", [])
    events = []
    if intent.get("needsClarification"):
        events.append({"type": "status", "data": {
            "text": "意图置信度不足 / 关键信息缺失，进入澄清", "stage": "clarify"}})
    else:
        events.append({"type": "status", "data": {
            "text": f"意图识别完成：{intent.get('summary', '')}（{len(tasks)} 个任务）", "stage": "intent"}})
    dag = {"tasks": [{"id": t["id"], "name": TASK_NAMES.get(t["type"], t["type"]),
                      "type": t["type"], "deps": t.get("deps", [])} for t in tasks]}
    events.append({"type": "plan", "data": {
        "intents": {"confidence": intent.get("confidence"), "summary": intent.get("summary"),
                    "needsClarification": intent.get("needsClarification"),
                    "clarifyQuestion": intent.get("clarifyQuestion")},
        "dag": dag}})
    return {"intent_data": intent, "tasks": tasks, "events": events}


def route_after_intent(state: AgentState):
    if state["intent_data"].get("needsClarification"):
        return "assemble"
    return "execute"


async def execute_node(state: AgentState) -> dict:
    """按拓扑层级并行执行任务：无依赖节点并行，依赖节点按拓扑顺序执行。"""
    tasks = state.get("tasks", [])
    memory = state.get("mem")
    ctx = {"user_id": state.get("user_id", 1), "session_id": state.get("session_id", "")}
    results, events = [], []
    done: set = set()
    pending = list(tasks)
    level = 0
    while pending:
        level += 1
        ready = [t for t in pending if all(d in done for d in t.get("deps", []))]
        if not ready:
            events.append({"type": "status", "data": {
                "text": "存在无法满足的依赖，跳过剩余任务", "stage": "dag"}})
            break
        events.append({"type": "status", "data": {
            "text": f"并行执行第 {level} 层：{', '.join(TASK_NAMES.get(t['type'], t['type']) for t in ready)}",
            "stage": "execute"}})
        batch = await asyncio.gather(*(execute_task(t, results, memory, ctx) for t in ready))
        for r in batch:
            if r.get("task_id"):
                results.append(r)
            events.extend(r.get("events", []))
        done.update(t["id"] for t in ready)
        pending = [t for t in pending if t["id"] not in done]
    return {"results": results, "events": events}


# ---------- 汇总 ----------

def _get_results(state, *types):
    return [r for r in state.get("results", []) if r.get("type") in types and r.get("ok")]


def build_outfit(state: AgentState) -> dict | None:
    ward = _get_results(state, "wardrobe")
    items = []
    if ward:
        items = [{"name": i.get("name"), "imageUrl": i.get("imageUrl"), "source": "wardrobe"}
                 for i in ward[0]["data"].get("items", [])[:4]]
    prods = _get_results(state, "product")
    if prods:
        items += [{"name": p.get("name"), "imageUrl": p.get("imageUrl"), "source": "mall",
                   "price": p.get("price")} for p in prods[0]["data"].get("products", [])[:2]]
    if not items:
        return None
    rules = _get_results(state, "rag", "rule_query")
    rule_sources = [r["title"] for r in rules[0]["data"].get("rules", [])[:2]] if rules else []
    reasons = []
    if rules:
        reasons = [r["content"] for r in rules[0]["data"].get("rules", [])[:2]]
    return {
        "name": state["intent_data"].get("summary") or "为你搭配的这套",
        "items": items,
        "reason": "；".join(reasons),
        "ruleSources": rule_sources,
    }


def _compose_mock(state: AgentState) -> str:
    parts = []
    ward = _get_results(state, "wardrobe")
    if ward:
        names = "、".join(i["name"] for i in ward[0]["data"].get("items", [])[:4])
        parts.append(f"已从你的衣橱找到：{names}。")
    rules = _get_results(state, "rag", "rule_query")
    for r in rules[0]["data"].get("rules", [])[:3] if rules else []:
        parts.append(f"穿搭建议（来源「{r['source']}」·{r['title']}）：{r['content']}")
    prods = _get_results(state, "product")
    if prods:
        ps = prods[0]["data"].get("products", [])[:4]
        parts.append("商城在售候选：" + "；".join(
            f"{p['name']} ¥{p['price']}（#{p['id']}）" for p in ps) + "。可直接让我收藏或下单。")
    img = _get_results(state, "image")
    if img:
        parts.append("换装效果图已生成，可点击“基于此图继续调整”让我修改。")
    orders = _get_results(state, "order")
    for o in orders:
        data = o.get("data", {})
        if data.get("orderNo"):
            parts.append(f"订单已创建：{data['orderNo']}，状态 {data.get('status')}。")
    favs = _get_results(state, "favorite")
    for f in favs:
        ids = f.get("data", {}).get("ids", [])
        if ids:
            parts.append(f"已收藏 {len(ids)} 件商品。")
    if not parts:
        parts.append("已完成。")
    return "\n".join(parts)


def _compose_llm(state: AgentState) -> str:
    context = {
        "用户消息": state["message"],
        "会话记忆": state["memory_desc"],
        "任务结果": [{k: v for k, v in r.items() if k != "events"} for r in state.get("results", [])],
    }
    system = ("你是潮引智能衣橱商城的穿搭助手。根据任务结果给出简洁实用的搭配建议，"
              "注明规则来源；语气亲切，中文回答，200 字以内。")
    try:
        return get_llm().chat(system, json.dumps(context, ensure_ascii=False, default=str))
    except Exception as e:
        print(f"[assemble] llm failed, fallback template: {e}", flush=True)
        return _compose_mock(state)


async def assemble_node(state: AgentState) -> dict:
    events = []
    memory = state.get("mem")
    if state["intent_data"].get("needsClarification"):
        text = state["intent_data"].get("clarifyQuestion") or "可以补充一点信息吗？"
        if memory:
            memory.state["clarify_count"] += 1
        events.append({"type": "status", "data": {
            "text": "等待用户补充信息（澄清最多 2 轮后兜底引导）", "stage": "clarify"}})
    else:
        text = _compose_mock(state) if (config.MOCK_AGENT or not config.LLM_API_KEY) else _compose_llm(state)
        outfit = build_outfit(state)
        if outfit:
            events.append({"type": "outfit", "data": {"outfit": outfit}})
            if memory:
                memory.set_candidates(outfit)
    mem = memory.state if memory else {}
    events.append({"type": "memory", "data": {"memory": {
        "persona": mem.get("persona"), "selected_items": [i.get("name") for i in mem.get("selected_items", [])],
        "candidates": [c.get("name") for c in mem.get("candidates", [])],
        "last_image": mem.get("last_image"), "clarify_count": mem.get("clarify_count")}}})
    return {"final_text": text, "events": events}


# ---------- 图 ----------

def build_graph():
    g = StateGraph(AgentState)
    g.add_node("intent", intent_node)
    g.add_node("execute", execute_node)
    g.add_node("assemble", assemble_node)
    g.add_edge(START, "intent")
    g.add_conditional_edges("intent", route_after_intent, ["execute", "assemble"])
    g.add_edge("execute", "assemble")
    g.add_edge("assemble", END)
    return g.compile()
