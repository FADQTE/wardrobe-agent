# -*- coding: utf-8 -*-
"""任务执行器：衣橱查询 / 规则RAG / 商品检索 / mock 生图 / 订单 / 收藏。"""
from __future__ import annotations

import asyncio
import hashlib
import json

import httpx

from . import config, rag
from .mcp_client import call_tool, get_mcp_tools

TRYON_PRESETS = [
    ("tryon_result_0.svg", "白衬衫·通勤套装"),
    ("tryon_result_1.svg", "风衣叠穿·街拍"),
    ("tryon_result_2.svg", "小黑裙·约会"),
    ("tryon_result_3.svg", "西装·商务"),
    ("tryon_result_4.svg", "卫衣·运动"),
    ("tryon_result_5.svg", "大衣·冬日"),
]


def _tool_event(name, args, ok, summary, error_category=None):
    data = {"name": name, "args": args, "ok": ok, "summary": summary}
    if error_category:
        data["errorCategory"] = error_category
    return {"type": "tool", "data": data}


def _status_event(text, stage=""):
    return {"type": "status", "data": {"text": text, "stage": stage}}


def classify_error(e: Exception) -> str:
    """错误分类：timeout | not_found | permission | business | unknown（决定重试/降级策略）。"""
    s = str(e).lower()
    if "timeout" in s or "timed out" in s or "超时" in s:
        return "timeout"
    if "not found" in s or "不存在" in s or "404" in s:
        return "not_found"
    if "permission" in s or "denied" in s or "权限" in s or "forbidden" in s:
        return "permission"
    if "库存" in s or "状态" in s or "business" in s or "不可用" in s:
        return "business"
    return "unknown"


# ---------- 各任务实现 ----------

async def do_wardrobe(task, state, memory, ctx) -> dict:
    params = task.get("params", {})
    events = [_status_event("查询衣橱单品…", "wardrobe")]
    items = []
    ok, summary, err_cat = True, "", None
    try:
        result = await call_tool("listWardrobe", {"userId": ctx["user_id"]})
        items = json.loads(result) if isinstance(result, str) else result
        if not isinstance(items, list):
            items = []
        tags = [t for t in params.get("tags", []) if t]
        if tags:
            items = [i for i in items if any(
                t in (i.get("name") or "") or t in (json.dumps(i.get("tags"), ensure_ascii=False) if i.get("tags") else "")
                for t in tags)]
        summary = f"衣橱命中 {len(items)} 件" + (f"（{'、'.join(tags)}）" if tags else "")
    except Exception as e:
        ok, summary = False, f"衣橱查询失败: {e}"
        err_cat = classify_error(e)
    events.append(_tool_event("listWardrobe", params, ok, summary,
                              error_category=None if ok else err_cat))
    if ok and items:
        memory.select(items)
        events.append({"type": "product", "data": {
            "title": "衣橱命中单品", "products": [
                {"id": i.get("id"), "name": i.get("name"), "imageUrl": i.get("imageUrl"),
                 "price": 0, "category": i.get("category"), "color": i.get("color"),
                 "season": i.get("season"), "style": i.get("style")} for i in items[:6]]}})
    result = {"task_id": task["id"], "type": "wardrobe", "ok": ok, "data": {"items": items}, "events": events}
    if err_cat:
        result["error_category"] = err_cat
    return result


async def do_rag(task, state, memory, rule_type=None) -> dict:
    params = task.get("params", {})
    query = params.get("query") or ""
    tags = params.get("tags") or []
    stage = "rule_query" if rule_type else "rag"
    events = [_status_event("检索穿搭/活动规则（ES 混合检索 + 时间窗过滤）…", stage)]
    try:
        # rerank 开启时多召回候选，再重排收敛
        candidate_size = config.RERANK_TOP_N if (config.RERANK_ENABLED and query) else 6
        rules = rag.hybrid_rule_search(query, tags=tags, rule_type=rule_type,
                                       only_time_valid=True, fallback_all=(rule_type == "activity"),
                                       size=candidate_size)
        if config.RERANK_ENABLED and query and len(rules) > 1:
            from . import rerank as rerank_mod
            rules = await rerank_mod.rerank(
                query,
                [r | {"text": f"{r.get('title', '')} {r.get('content', '')}"} for r in rules],
                top_k=6)
            events.append(_tool_event("rerank", {"query": query, "topK": len(rules)}, True,
                                      f"Reranker 重排 Top{len(rules)}（Qwen3-Reranker 本地部署）"))
        events.append({"type": "rag", "data": {"rules": rules, "query": query}})
        events.append(_tool_event("hybrid_rule_search", {"query": query, "tags": tags, "type": rule_type},
                                  True, f"召回 {len(rules)} 条有效规则（已过滤过期/未生效/未发布）"))
        return {"task_id": task["id"], "type": stage, "ok": True, "data": {"rules": rules}, "events": events}
    except Exception as e:
        err_cat = classify_error(e)
        events.append(_tool_event("hybrid_rule_search", params, False, f"ES 检索失败: {e}",
                                  error_category=err_cat))
        return {"task_id": task["id"], "type": stage, "ok": False,
                "data": {"rules": []}, "error_category": err_cat, "events": events}


async def do_product(task, state, memory) -> dict:
    params = task.get("params", {})
    keyword = params.get("keyword") or ""
    events = [_status_event("检索商城在售商品（ES 双索引 · 混合检索）…", "product")]
    try:
        candidate_size = config.RERANK_TOP_N if (config.RERANK_ENABLED and keyword) else 6
        result = rag.hybrid_product_search(
            keyword=keyword, category=params.get("category") or "",
            color=params.get("color") or "", season=params.get("season") or "",
            style=params.get("style") or "", max_price=params.get("maxPrice"),
            page=1, size=candidate_size)
        products = result["products"]
        if config.RERANK_ENABLED and keyword and len(products) > 1:
            from . import rerank as rerank_mod
            products = await rerank_mod.rerank(
                keyword,
                [p | {"text": f"{p.get('name', '')} {p.get('detail', '')}"} for p in products],
                top_k=6)
            events.append(_tool_event("rerank", {"keyword": keyword, "topK": len(products)}, True,
                                      f"Reranker 重排 Top{len(products)}"))
        events.append(_tool_event("hybrid_product_search", params, True,
                                  f"商城命中 {result['total']} 件，展示 Top{len(products)}"))
        if products:
            events.append({"type": "product", "data": {
                "title": "商城在售候选（可点击查看详情/购买）", "products": products[:6]}})
        return {"task_id": task["id"], "type": "product", "ok": True,
                "data": {"products": products}, "events": events}
    except Exception as e:
        err_cat = classify_error(e)
        events.append(_tool_event("hybrid_product_search", params, False, f"ES 检索失败: {e}",
                                  error_category=err_cat))
        return {"task_id": task["id"], "type": "product", "ok": False,
                "data": {"products": []}, "error_category": err_cat, "events": events}


async def do_image(task, state, memory, ctx) -> dict:
    label = task.get("params", {}).get("label") or "换装效果"
    events = [_status_event("创建换装任务（统一管理输入/状态/结果地址）…", "image")]
    task_id = None
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(f"{config.JAVA_API_URL}/tryon", json={
                "sessionId": ctx["session_id"], "userId": ctx["user_id"],
                "garmentIds": json.dumps([]),
                "params": json.dumps({"label": label}, ensure_ascii=False),
                "status": "processing",
            })
            if r.status_code == 200:
                task_id = r.json().get("data", {}).get("id")
    except Exception as e:
        events.append(_tool_event("mock_tryon:create", task, False, f"任务创建失败: {e}"))

    for stage, percent in [("上传人像与衣物图", 20), ("解析穿搭要求", 45), ("模型生成中", 75), ("渲染完成", 100)]:
        events.append({"type": "image_progress", "data": {"stage": stage, "percent": percent, "taskId": task_id}})
        await asyncio.sleep(0.5)

    # 从预设结果池挑选（按 label 稳定哈希）
    idx = int(hashlib.md5(label.encode()).hexdigest(), 16) % len(TRYON_PRESETS)
    fname, preset_label = TRYON_PRESETS[idx]
    url = f"/seed-images/{fname}"
    if task_id:
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                await c.post(f"{config.JAVA_API_URL}/tryon/{task_id}/status",
                             json={"status": "done", "resultUrl": url, "errorMsg": None})
        except Exception:
            pass
    memory.state["last_image"] = {"url": url, "label": preset_label, "taskId": task_id}
    events.append({"type": "image", "data": {"url": url, "label": preset_label, "taskId": task_id}})
    events.append(_tool_event("mock_tryon", {"label": label}, True,
                              f"任务 #{task_id} 完成，结果地址 {url}（mock provider，可无缝替换真实生图 API）"))
    return {"task_id": task["id"], "type": "image", "ok": True,
            "data": {"url": url, "label": preset_label, "taskId": task_id}, "events": events}


def _products_from_results(results: list) -> list:
    prods = []
    for r in results:
        if r.get("type") == "product" and r.get("ok"):
            prods.extend(r["data"].get("products", []))
    return prods


async def do_favorite(task, state, memory, ctx) -> dict:
    events = [_status_event("执行收藏操作…", "favorite")]
    params = task.get("params", {})
    ids = params.get("productIds") or []
    if not ids:
        kw = params.get("keyword") or ""
        ids = [p["id"] for p in _products_from_results(state) if kw in p.get("name", "")]
    if not ids:
        events.append(_tool_event("addFavorite", params, False, "未定位到商品，请先检索商城商品",
                                  error_category="not_found"))
        return {"task_id": task["id"], "type": "favorite", "ok": False,
                "data": {}, "error_category": "not_found", "events": events}
    done = []
    for pid in ids[:3]:
        try:
            await call_tool("addFavorite", {"userId": ctx["user_id"], "productId": pid})
            done.append(pid)
        except Exception as e:
            events.append(_tool_event("addFavorite", {"productId": pid}, False, str(e)[:80]))
    events.append(_tool_event("addFavorite", {"productIds": done}, True, f"已收藏 {len(done)} 件商品（MCP 写操作，Java 侧事务校验）"))
    return {"task_id": task["id"], "type": "favorite", "ok": True, "data": {"ids": done}, "events": events}


async def do_order(task, state, memory, ctx) -> dict:
    events = [_status_event("创建订单（MCP → Spring Boot 权限/库存/事务校验）…", "order")]
    params = task.get("params", {})
    ids = params.get("productIds") or []
    if not ids:
        ids = [p["id"] for p in _products_from_results(state)][:3]
    if not ids:
        events.append(_tool_event("createOrder", params, False, "未定位到商品，请先检索商城商品",
                                  error_category="not_found"))
        return {"task_id": task["id"], "type": "order", "ok": False,
                "data": {}, "error_category": "not_found", "events": events}
    try:
        result = await call_tool("createOrder", {
            "userId": ctx["user_id"],
            "items": [{"productId": pid, "quantity": 1} for pid in ids],
            "receiverName": "小潮", "receiverPhone": "13800000000",
            "receiverAddress": "上海市徐汇区漕河泾开发区",
        })
        data = json.loads(result) if isinstance(result, str) else result
        order_no = data.get("orderNo") if isinstance(data, dict) else ""
        events.append(_tool_event("createOrder", {"productIds": ids}, True,
                                  f"下单成功，订单号 {order_no}，状态 {data.get('status') if isinstance(data, dict) else ''}"))
        return {"task_id": task["id"], "type": "order", "ok": True, "data": data, "events": events}
    except Exception as e:
        err_cat = classify_error(e)
        events.append(_tool_event("createOrder", {"productIds": ids}, False, str(e)[:100],
                                  error_category=err_cat))
        return {"task_id": task["id"], "type": "order", "ok": False,
                "data": {}, "error_category": err_cat, "events": events}


async def execute_task(task: dict, results: list, memory, ctx: dict) -> dict:
    """执行单个任务（幂等：已完成则跳过）。state 即已完成结果列表。"""
    done = [r["task_id"] for r in results]
    if task["id"] in done:
        return {"events": []}
    t = task["type"]
    if t == "wardrobe":
        return await do_wardrobe(task, results, memory, ctx)
    if t == "rag":
        return await do_rag(task, results, memory)
    if t == "rule_query":
        return await do_rag(task, results, memory, rule_type="activity")
    if t == "product":
        return await do_product(task, results, memory)
    if t == "image":
        return await do_image(task, results, memory, ctx)
    if t == "favorite":
        return await do_favorite(task, results, memory, ctx)
    if t == "order":
        return await do_order(task, results, memory, ctx)
    return {"task_id": task["id"], "type": t, "ok": False,
            "data": {}, "events": [_tool_event(t, task.get("params", {}), False, f"未知任务类型 {t}")]}
