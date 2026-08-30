# -*- coding: utf-8 -*-
"""LangGraph 编排：安全闸 → 意图识别 → 依赖 DAG 执行（无依赖并行）→ 汇总回复。

图结构：safety → intent → execute → assemble。
- safety：Prompt Injection / 越权 / 隐私扫描，命中拒答直接短路到 assemble
- intent：结构化输出把自然语言拆为任务 DAG（依赖用 deps 引用任务 id）
- execute：按拓扑层级执行——同层无依赖任务用 asyncio.gather 并行，
  依赖任务在其依赖完成后的下一层执行；关键事实查询失败触发转人工
- assemble：汇总任务结果为最终回复（搭配建议 + 规则来源 + 会话记忆）

注：langgraph 0.2.74 的 Send 分支状态相互隔离（无法跨分支 join），
且节点内无 runnable config 上下文，因此并行放在 execute 节点内部实现。
"""
from __future__ import annotations

import asyncio
import json
import operator
from datetime import datetime
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph

from . import config
from .context import build_context_report
from .intent import parse_intent
from .llm import get_llm
from .safety import REFUSAL_ANSWER, build_safety_decision
from .tasks import execute_task

TASK_NAMES = {
    "wardrobe": "衣橱查询", "rag": "穿搭规则RAG", "rule_query": "活动规则查询",
    "product": "商城商品检索", "image": "换装生图", "order": "创建订单",
    "favorite": "收藏商品", "clarify": "澄清",
    "order_query": "订单查询", "logistics": "物流查询", "aftersale": "售后服务",
}


class AgentState(TypedDict, total=False):
    session_id: str
    user_id: int
    message: str
    memory_desc: str
    mem: Any
    runtime: dict
    event_sink: Any
    safety_data: dict
    handoff: str
    intent_data: dict
    tasks: list
    results: Annotated[list, operator.add]
    events: Annotated[list, operator.add]
    final_text: str


# ---------- 节点 ----------

async def safety_node(state: AgentState) -> dict:
    """第一道安全闸：用户消息按外部文本扫描，索要系统信息/覆盖指令直接拒答。"""
    decision = build_safety_decision(state["message"])
    events = []
    if decision["blocked_user_request"]:
        events.append({"type": "status", "data": {
            "text": "安全拦截：拒绝泄露系统提示词/内部指令", "stage": "safety"}})
    events.append({"type": "safety", "data": {
        "blocked": decision["blocked_user_request"],
        "mode": decision["mode"],
        "refusedTopics": decision["refused_topics"],
        "scans": decision["scans"],
    }})
    return {"safety_data": decision, "events": events}


def route_after_safety(state: AgentState):
    if state["safety_data"].get("blocked_user_request"):
        return "assemble"
    return "intent"


async def intent_node(state: AgentState) -> dict:
    intent = parse_intent(state["message"], state["memory_desc"])
    tasks = intent.get("tasks", [])
    events = []
    # Context Builder：本轮上下文组装摘要（来源 + 可信度 + 冲突解析）
    runtime = state.get("runtime") or {}
    ctx_report = build_context_report(runtime, state["memory_desc"], 0, 0, state["message"])
    events.append({"type": "context", "data": ctx_report})
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
                    "clarifyQuestion": intent.get("clarifyQuestion"),
                    "riskLevel": intent.get("risk_level", "low"),
                    "fallbackPolicy": intent.get("fallback_policy", "tool_first")},
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
    ctx = {
        "user_id": state.get("user_id", 1),
        "session_id": state.get("session_id", ""),
        "event_sink": state.get("event_sink"),
    }
    results, events = [], []
    done: set = set()
    pending = list(tasks)
    level = 0
    handoff = ""
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
        # 错误分类降级：关键事实查询失败（超时/未知异常）→ 转人工，不猜答案
        if not handoff:
            critical = [r for r in results if not r.get("ok")
                        and r.get("error_category") in ("timeout", "unknown")
                        and r.get("type") in (
                            "wardrobe", "product", "rag", "rule_query", "order",
                            "order_query", "logistics", "aftersale")]
            if critical:
                handoff = "业务事实查询失败：" + "、".join(
                    TASK_NAMES.get(r["type"], r["type"]) for r in critical)
                events.append({"type": "handoff", "data": {"reason": handoff}})
                events.append({"type": "status", "data": {
                    "text": f"降级转人工：{handoff}", "stage": "handoff"}})
    upd: dict = {"results": results, "events": events}
    if handoff:
        upd["handoff"] = handoff
    return upd


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


def _format_activity_end(value: str | None) -> str:
    if not value:
        return "结束时间以活动页为准"
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.strftime("%m月%d日 %H:%M")
    except (TypeError, ValueError):
        return str(value)


def _compose_activity_list(state: AgentState) -> str | None:
    """纯活动查询用确定性清单回答，保证每条召回证据都被展示且不被模型省略。"""
    activity_results = _get_results(state, "rule_query")
    if not activity_results:
        return None
    if _get_results(state, "wardrobe", "rag", "product", "image", "order", "favorite"):
        return None
    rules = activity_results[0]["data"].get("rules", [])
    if not rules:
        return "目前没有查到可靠的进行中活动。你也可以告诉我想买的品类，我再帮你查对应优惠。"
    lines = [f"目前有 **{len(rules)} 个正在生效的活动**（按结束时间排序）：", ""]
    for rule in rules:
        lines.append(
            f"- **{rule.get('title') or '未命名活动'}**：{rule.get('content') or '详情以活动页为准'}"
            f"（有效至 {_format_activity_end(rule.get('effectiveTo'))}；来源：{rule.get('source') or '运营平台'}）"
        )
    lines.extend(["", "> 仅展示已发布且当前处于有效期内的活动，过期、未生效和草稿活动已过滤。"])
    return "\n".join(lines)


ORDER_STATUS_CN = {
    "pending": "待支付", "paid": "已支付，待发货", "shipped": "已发货",
    "done": "已完成", "cancelled": "已取消",
}


def _compose_commerce_support(state: AgentState) -> str | None:
    """订单、物流和售后走确定性回答，避免模型篡改状态或误说“已退款”。"""
    order_results = _get_results(state, "order_query")
    if order_results:
        orders = order_results[0]["data"].get("orders", [])
        if not orders:
            return "暂时没有查到你的订单记录。你可以先去商城选择商品并创建订单。"
        lines = [f"查到 **{len(orders)} 笔订单**（最新在前）：", ""]
        for order in orders[:5]:
            status = ORDER_STATUS_CN.get(order.get("status"), order.get("status") or "未知")
            lines.append(
                f"- `{order.get('orderNo')}`：¥{order.get('totalAmount')}，{status}"
                + (f"，物流单号 `{order.get('logisticsNo')}`" if order.get("logisticsNo") else "")
            )
        lines.append("\n可继续告诉我订单号查询物流；取消或售后申请请在商城的“我的订单”中确认操作。")
        return "\n".join(lines)

    logistics_results = _get_results(state, "logistics")
    if logistics_results:
        data = logistics_results[0]["data"]
        if data.get("needsOrderNo"):
            orders = data.get("orders", [])
            if not orders:
                return "没有找到可查询物流的订单。"
            choices = "、".join(f"`{o.get('orderNo')}`" for o in orders[:3])
            return f"你有多笔订单，请告诉我要查哪一笔：{choices}。"
        status = ORDER_STATUS_CN.get(data.get("status"), data.get("status") or "未知")
        logistics_no = data.get("logisticsNo") or "暂未生成"
        return (f"订单 `{data.get('orderNo')}` 当前为 **{status}**。\n\n"
                f"物流单号：`{logistics_no}`。{data.get('hint') or ''}")

    aftersale_results = _get_results(state, "aftersale")
    if aftersale_results:
        data = aftersale_results[0]["data"]
        if data.get("action") == "query":
            records = data.get("records", [])
            if not records:
                return "目前没有查到你的售后申请。若需要退换货，请到商城 → 我的订单 → 查看详情后提交申请。"
            status_cn = {"pending": "待审核", "approved": "已通过", "rejected": "已拒绝", "completed": "已完成"}
            lines = [f"查到 **{len(records)} 条售后记录**（最新在前）：", ""]
            for row in records[:5]:
                lines.append(
                    f"- `{row.get('requestNo')}`：订单 #{row.get('orderId')}，"
                    f"{status_cn.get(row.get('status'), row.get('status'))}，金额 ¥{row.get('amount')}"
                )
            return "\n".join(lines)

        policy = data.get("policy") or {}
        lines = [
            "支持退换货，但要根据订单状态处理：", "",
            f"- {policy.get('unpaidOrder', '待支付订单可取消。')}",
            f"- {policy.get('paidUnshipped', '已支付未发货订单可申请退款。')}",
            f"- {policy.get('shippedOrCompleted', '已发货订单需按退货退款流程处理。')}",
            f"- 例外：{policy.get('exclusions', '影响二次销售的商品不适用无理由退换。')}", "",
            f"> {policy.get('processing', '提交后进入人工审核。')}",
        ]
        if data.get("action") == "guide":
            lines.extend(["", "请到 **商城 → 我的订单 → 查看详情 → 申请退款** 提交；我不会在对话里直接替你执行资金相关操作。"])
        else:
            lines.extend(["", "这只是政策查询，**当前没有创建退款申请**。需要办理时可在商城的“我的订单”里提交。"])
        return "\n".join(lines)
    return None


def _compose_mock(state: AgentState) -> str:
    parts = []
    ward = _get_results(state, "wardrobe")
    if ward:
        names = "、".join(i["name"] for i in ward[0]["data"].get("items", [])[:4])
        parts.append(f"已从你的衣橱找到：{names}。")
    rules = _get_results(state, "rag", "rule_query")
    for result in rules[:1]:
        label = "活动" if result.get("type") == "rule_query" else "穿搭建议"
        for r in result["data"].get("rules", [])[:3]:
            parts.append(f"{label}（来源「{r['source']}」·{r['title']}）：{r['content']}")
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
    support = _compose_commerce_support(state)
    if support:
        parts.append(support)
    if not parts:
        parts.append("已完成。")
    return "\n".join(parts)


def _compose_llm(state: AgentState) -> str:
    # Observation 压缩：只给模型回答所需的短摘要，不塞原始字段（防编造编号/价格）
    results = []
    for r in state.get("results", []):
        if r.get("type") == "wardrobe" and r.get("ok"):
            items = [{"name": i.get("name"), "color": i.get("color"),
                      "season": i.get("season"), "style": i.get("style")}
                     for i in r["data"].get("items", [])]
            results.append({"type": "wardrobe", "items": items})
        elif r.get("type") in ("rag", "rule_query") and r.get("ok"):
            results.append({"type": r["type"], "rules": [
                {"title": x.get("title"), "content": x.get("content"), "source": x.get("source"),
                 "effectiveFrom": x.get("effectiveFrom"), "effectiveTo": x.get("effectiveTo")}
                for x in r["data"].get("rules", [])]})
        elif r.get("type") == "product" and r.get("ok"):
            results.append({"type": "product", "products": [
                {"name": p.get("name"), "price": p.get("price"), "color": p.get("color"),
                 "style": p.get("style")} for p in r["data"].get("products", [])]})
        elif r.get("type") == "order" and r.get("ok"):
            results.append({"type": "order", "orderNo": r["data"].get("orderNo"),
                            "status": r["data"].get("status")})
        elif r.get("type") == "image" and r.get("ok"):
            results.append({"type": "image", "label": r["data"].get("label")})
        elif r.get("type") == "favorite" and r.get("ok"):
            results.append({"type": "favorite", "count": len(r["data"].get("ids", []))})
        elif r.get("type") in ("order_query", "logistics", "aftersale") and r.get("ok"):
            results.append({"type": r.get("type"), "data": r.get("data")})
    context = {
        "用户消息": state["message"],
        "会话记忆": state["memory_desc"],
        "任务结果": results,
    }
    system = ("你是智能衣橱的穿搭助手。根据任务结果给出简洁实用的搭配建议，"
              "注明规则来源；语气亲切，中文回答，200 字以内。"
              "严格以工具结果为准：不要编造商品编号、价格、库存或规则内容；"
              "工具没查到的事实不要补充。")
    try:
        return get_llm().chat(system, json.dumps(context, ensure_ascii=False, default=str))
    except Exception as e:
        print(f"[assemble] llm failed, fallback template: {e}", flush=True)
        return _compose_mock(state)


async def assemble_node(state: AgentState) -> dict:
    events = []
    memory = state.get("mem")
    if state.get("safety_data", {}).get("blocked_user_request"):
        # 安全拒答：不进入业务编排，不生成 outfit
        text = REFUSAL_ANSWER
    elif state.get("handoff"):
        # 降级转人工：关键事实不可用时不猜答案
        text = f"抱歉，当前服务暂时无法完成本次查询（{state['handoff']}）。已为你转接人工客服，请稍候。"
    elif state["intent_data"].get("needsClarification"):
        clarify_done = int(memory.state.get("clarify_count") or 0) if memory else 0
        if clarify_done >= 2:
            # 兜底引导：连续澄清 2 轮仍未命中，不再追问，列出能力菜单让用户选
            text = ("我先说一下我能帮你做的事，你直接挑一个：\n\n"
                    "- **穿搭推荐**：告诉我场景（通勤 / 约会 / 面试…），我会结合你的衣橱和商城在售单品出搭配\n"
                    "- **虚拟试穿**：选定搭配后一键生成效果图\n"
                    "- **订单 / 物流 / 售后**：查订单、查快递、看退换货政策与进度\n"
                    "- **优惠活动**：查当前生效的满减和折扣\n\n"
                    "也可以直接说，比如「帮我搭配一套秋日通勤装」或「查一下我的订单」。")
            if memory:
                memory.state["clarify_count"] = 0
            events.append({"type": "status", "data": {
                "text": "连续澄清 2 轮未命中，转入能力引导", "stage": "clarify"}})
        else:
            text = state["intent_data"].get("clarifyQuestion") or "可以补充一点信息吗？"
            if memory:
                memory.state["clarify_count"] = clarify_done + 1
            events.append({"type": "status", "data": {
                "text": f"等待用户补充信息（第 {clarify_done + 1}/2 轮澄清，超限转能力引导）",
                "stage": "clarify"}})
    else:
        text = _compose_commerce_support(state)
        if text is None:
            text = _compose_activity_list(state)
        if text is None:
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
        "last_image": mem.get("last_image"), "clarify_count": mem.get("clarify_count"),
        "long_term_facts": len(getattr(memory, "long_facts", []) or []),
        "episodic_recalled": len(getattr(memory, "episodic", []) or []),
    }}})
    return {"final_text": text, "events": events}


# ---------- 图 ----------

def build_graph():
    g = StateGraph(AgentState)
    g.add_node("safety", safety_node)
    g.add_node("intent", intent_node)
    g.add_node("execute", execute_node)
    g.add_node("assemble", assemble_node)
    g.add_edge(START, "safety")
    g.add_conditional_edges("safety", route_after_safety, ["intent", "assemble"])
    g.add_conditional_edges("intent", route_after_intent, ["execute", "assemble"])
    g.add_edge("execute", "assemble")
    g.add_edge("assemble", END)
    return g.compile()
