# -*- coding: utf-8 -*-
"""任务执行器：衣橱查询 / 规则RAG / 商品检索 / 虚拟试衣 / 订单 / 收藏。"""
from __future__ import annotations

import asyncio
import json
import re

import httpx

from . import config, rag
from .mcp_client import call_tool, get_mcp_tools

TRYON_PRESETS = [
    {"file": "tryon_result_0.svg", "label": "白衬衫·通勤套装",
     "keywords": ("白衬衫", "衬衫", "通勤", "简约")},
    {"file": "tryon_result_1.svg", "label": "风衣叠穿·街拍",
     "keywords": ("风衣", "叠穿", "街拍", "街头")},
    {"file": "tryon_result_2.svg", "label": "小黑裙·约会",
     "keywords": ("小黑裙", "连衣裙", "短裙", "半身裙", "裙", "约会")},
    {"file": "tryon_result_3.svg", "label": "西装·商务",
     "keywords": ("西装", "西服", "商务", "正装", "面试")},
    {"file": "tryon_result_4.svg", "label": "卫衣·运动",
     "keywords": ("卫衣", "运动", "休闲", "跑步", "健身")},
    {"file": "tryon_result_5.svg", "label": "大衣·冬日",
     "keywords": ("大衣", "冬日", "冬季", "保暖", "羊毛")},
]

MOCK_TRYON_NOTICE = "当前未接入生图模型；下图是按推荐单品和风格匹配的本地模拟预览，不代表真人试穿或真实生成效果。"


def _tryon_garments(task: dict, results: list, memory) -> list[dict]:
    """从 image 的依赖结果提取实际单品；跨轮调整时回退到最近一套候选搭配。"""
    dependency_ids = set(task.get("deps") or [])
    dependency_results = [
        result for result in results
        if not dependency_ids or result.get("task_id") in dependency_ids
    ]
    garments: list[dict] = []
    for result in dependency_results:
        if not result.get("ok"):
            continue
        if result.get("type") == "wardrobe":
            garments.extend(result.get("data", {}).get("items", []))
        elif result.get("type") == "product":
            garments.extend(result.get("data", {}).get("products", []))

    if not garments and memory:
        candidates = memory.state.get("candidates") or []
        if candidates:
            garments.extend(candidates[-1].get("items") or [])
        elif memory.state.get("selected_items"):
            garments.extend(memory.state["selected_items"])

    # 同一单品可能同时出现在检索结果与记忆中，按 id/name 稳定去重。
    unique, seen = [], set()
    for garment in garments:
        key = (garment.get("id"), garment.get("name"))
        if key in seen:
            continue
        seen.add(key)
        unique.append(garment)
    return unique


def _garment_text(garments: list[dict]) -> str:
    fields = ("name", "category", "color", "season", "style", "detail")
    return " ".join(
        str(garment.get(field) or "")
        for garment in garments for field in fields
    ).lower()


def _tryon_style_context(task: dict, results: list) -> str:
    """提取依赖规则中的风格描述，供没有完整衣物图时选择最接近的模拟素材。"""
    dependency_ids = set(task.get("deps") or [])
    parts = []
    for result in results:
        if dependency_ids and result.get("task_id") not in dependency_ids:
            continue
        if result.get("ok") and result.get("type") in ("rag", "rule_query"):
            for rule in result.get("data", {}).get("rules", []):
                parts.extend((str(rule.get("title") or ""), str(rule.get("content") or ""),
                              str(rule.get("tags") or "")))
    return " ".join(parts).lower()


def _select_mock_preset(label: str, garments: list[dict], style_context: str = "") -> dict:
    """实际单品优先于泛化请求标签，避免西装推荐被哈希成裙装预览。"""
    garment_context = _garment_text(garments)
    request_context = f"{label or ''} {style_context}".lower()
    best_index, best_score = 0, 0
    for index, preset in enumerate(TRYON_PRESETS):
        garment_score = sum(3 for keyword in preset["keywords"] if keyword in garment_context)
        request_score = sum(1 for keyword in preset["keywords"] if keyword in request_context)
        score = garment_score + request_score
        if score > best_score:
            best_index, best_score = index, score
    return TRYON_PRESETS[best_index]


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


def is_broad_activity_query(query: str) -> bool:
    """识别“现在有什么活动”一类清单查询，避免相关性阈值把有效活动压成一条。"""
    remaining = re.sub(r"[\s？?！!，,。.：:]", "", query or "")
    for word in ("告诉我", "帮我查", "查一下", "看一下", "请问", "现在", "当前", "最近",
                 "商城", "正在进行", "进行中", "有什么", "有哪些", "活动", "优惠", "促销", "折扣", "吗", "呢"):
        remaining = remaining.replace(word, "")
    return not remaining


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
        broad_activity = rule_type == "activity" and is_broad_activity_query(query)
        search_query = "" if broad_activity else query
        # rerank 开启时多召回候选，再重排收敛
        candidate_size = 20 if broad_activity else (config.RERANK_TOP_N if (config.RERANK_ENABLED and search_query) else 6)
        rules = rag.hybrid_rule_search(search_query, tags=tags, rule_type=rule_type,
                                       only_time_valid=True, fallback_all=(rule_type == "activity"),
                                       size=candidate_size)
        if config.RERANK_ENABLED and search_query and len(rules) > 1:
            from . import rerank as rerank_mod
            rules = await rerank_mod.rerank(
                search_query,
                [r | {"text": f"{r.get('title', '')} {r.get('content', '')}"} for r in rules],
                top_k=6)
            events.append(_tool_event("rerank", {"query": search_query, "topK": len(rules)}, True,
                                      f"Reranker 重排 Top{len(rules)}（Qwen3-Reranker 本地部署）"))
        retrieval_mode = rules[0].get("retrievalMode") if rules else (
            "catalog_filter" if broad_activity else "bm25")
        events.append({"type": "rag", "data": {
            "rules": rules, "query": query,
            "retrieval": {"mode": retrieval_mode,
                          "channels": rules[0].get("retrievalChannels", []) if rules else []},
        }})
        events.append(_tool_event("hybrid_rule_search", {
            "query": query, "tags": tags, "type": rule_type,
            "mode": "all_current" if broad_activity else "relevant",
        },
                                  True, f"召回 {len(rules)} 条有效规则（{retrieval_mode}；"
                                        "已过滤过期/未生效/未发布）"))
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
        retrieval = result.get("retrieval") or {}
        events.append(_tool_event("hybrid_product_search", params, True,
                                  f"商城命中 {result['total']} 件，展示 Top{len(products)}"
                                  f"（{retrieval.get('mode', 'bm25')}："
                                  f"BM25 {retrieval.get('lexicalHits', 0)} / "
                                  f"kNN {retrieval.get('vectorHits', 0)}）"))
        if products:
            events.append({"type": "product", "data": {
                "title": "商城在售候选（可点击查看详情/购买）", "products": products[:6],
                "retrieval": retrieval}})
        return {"task_id": task["id"], "type": "product", "ok": True,
                "data": {"products": products}, "events": events}
    except Exception as e:
        err_cat = classify_error(e)
        events.append(_tool_event("hybrid_product_search", params, False, f"ES 检索失败: {e}",
                                  error_category=err_cat))
        return {"task_id": task["id"], "type": "product", "ok": False,
                "data": {"products": []}, "error_category": err_cat, "events": events}


async def do_image(task, state, memory, ctx) -> dict:
    params = dict(task.get("params", {}))
    label = params.get("label") or "换装效果"
    garments = _tryon_garments(task, state, memory)
    derived_ids = [garment.get("id") for garment in garments if garment.get("id") is not None]
    derived_urls = [garment.get("imageUrl") for garment in garments if garment.get("imageUrl")]
    params["garmentIds"] = params.get("garmentIds") or derived_ids
    params["garmentImageUrls"] = params.get("garmentImageUrls") or derived_urls
    params["garmentNames"] = params.get("garmentNames") or [
        garment.get("name") for garment in garments if garment.get("name")
    ]
    events = [_status_event("创建换装任务（统一管理输入/状态/结果地址）…", "image")]
    task_id = None
    try:
        async with httpx.AsyncClient(timeout=10, headers=config.JAVA_INTERNAL_HEADERS) as c:
            r = await c.post(f"{config.JAVA_API_URL}/tryon", json={
                "sessionId": ctx["session_id"], "userId": ctx["user_id"],
                "garmentIds": json.dumps(params.get("garmentIds") or []),
                "params": json.dumps(params | {"label": label}, ensure_ascii=False),
                "status": "processing",
            })
            if r.status_code == 200:
                task_id = r.json().get("data", {}).get("id")
    except Exception as e:
        events.append(_tool_event("tryon_task:create", task, False, f"任务创建失败: {e}"))

    async def update_task(status: str, result_url: str | None = None,
                          error_msg: str | None = None) -> None:
        if not task_id:
            return
        try:
            async with httpx.AsyncClient(timeout=10, headers=config.JAVA_INTERNAL_HEADERS) as c:
                await c.post(f"{config.JAVA_API_URL}/tryon/{task_id}/status", json={
                    "status": status, "resultUrl": result_url, "errorMsg": error_msg,
                })
        except Exception as error:
            print(f"[tryon] task status update failed: {error}", flush=True)

    async def progress(stage: str, percent: int) -> None:
        event = {"type": "image_progress", "data": {
            "stage": stage, "percent": percent, "taskId": task_id,
            "provider": config.TRYON_MODE,
        }}
        # API 注入 event_sink 时即时进入 SSE/Netty；事件仍保留在最终状态供 Trace/评测使用。
        event_sink = ctx.get("event_sink")
        if event_sink:
            await event_sink(event)
            event["_liveEmitted"] = True
        events.append(event)

    provider_task_id = None
    if config.TRYON_MODE == "mock":
        for stage, percent in [("加载本地模拟素材", 20), ("匹配推荐单品与风格", 45),
                               ("生成模拟预览", 75), ("模拟预览完成", 100)]:
            await progress(stage, percent)
            await asyncio.sleep(0.5)
        # 预设图必须与本轮依赖返回的实际单品一致；无单品时才使用请求标签兜底。
        preset = _select_mock_preset(label, garments, _tryon_style_context(task, state))
        preset_label = f"{preset['label']}（模拟预览）"
        url = f"/seed-images/{preset['file']}"
        tool_name = "mock_tryon"
    else:
        try:
            from .tryon_provider import generate
            generated = await generate({
                "taskId": task_id,
                "sessionId": ctx["session_id"],
                "userId": ctx["user_id"],
                "label": label,
                "personImageUrl": params.get("personImageUrl"),
                "garmentImageUrls": params.get("garmentImageUrls") or [],
                "garmentIds": params.get("garmentIds") or [],
                "params": params,
            }, progress)
            url = generated["url"]
            provider_task_id = generated.get("providerTaskId")
            preset_label = label
            tool_name = "http_tryon"
        except Exception as error:
            error_text = str(error)[:300]
            await update_task("failed", error_msg=error_text)
            events.append(_tool_event("http_tryon", {"label": label}, False, error_text,
                                      error_category=classify_error(error)))
            return {"task_id": task["id"], "type": "image", "ok": False,
                    "data": {"taskId": task_id},
                    "error_category": classify_error(error), "events": events}

    await update_task("done", result_url=url)
    memory.state["last_image"] = {
        "url": url, "label": preset_label, "taskId": task_id,
        "provider": config.TRYON_MODE, "providerTaskId": provider_task_id,
        "isSimulation": config.TRYON_MODE == "mock",
    }
    events.append({"type": "image", "data": {
        "url": url, "label": preset_label, "taskId": task_id,
        "provider": config.TRYON_MODE, "providerTaskId": provider_task_id,
        "isSimulation": config.TRYON_MODE == "mock",
        "notice": MOCK_TRYON_NOTICE if config.TRYON_MODE == "mock" else None,
        "garmentNames": params.get("garmentNames") or [],
    }})
    provider_summary = ("本地 mock 结果" if config.TRYON_MODE == "mock" else "真实 HTTP 生图服务结果")
    events.append(_tool_event(tool_name, {
        "label": label, "garmentIds": params.get("garmentIds") or [],
        "garmentNames": params.get("garmentNames") or [],
    }, True,
                              f"任务 #{task_id} 完成，结果地址 {url}（{provider_summary}）"))
    return {"task_id": task["id"], "type": "image", "ok": True,
            "data": {"url": url, "label": preset_label, "taskId": task_id,
                     "provider": config.TRYON_MODE, "providerTaskId": provider_task_id,
                     "isSimulation": config.TRYON_MODE == "mock",
                     "notice": MOCK_TRYON_NOTICE if config.TRYON_MODE == "mock" else None,
                     "garmentNames": params.get("garmentNames") or []},
            "events": events}


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


async def do_order_query(task, state, memory, ctx) -> dict:
    params = task.get("params", {})
    order_no = (params.get("orderNo") or "").strip()
    events = [_status_event("查询订单实时状态（MCP）…", "order_query")]
    tool = "queryOrder" if order_no else "listOrders"
    args = {"userId": ctx["user_id"]}
    if order_no:
        args["orderNo"] = order_no
    try:
        raw = await call_tool(tool, args)
        data = json.loads(raw) if isinstance(raw, str) else raw
        orders = [data] if order_no and isinstance(data, dict) else (data if isinstance(data, list) else [])
        events.append(_tool_event(tool, args, True, f"查到 {len(orders)} 笔订单"))
        return {"task_id": task["id"], "type": "order_query", "ok": True,
                "data": {"orders": orders}, "events": events}
    except Exception as e:
        err_cat = classify_error(e)
        events.append(_tool_event(tool, args, False, f"订单查询失败: {e}", error_category=err_cat))
        return {"task_id": task["id"], "type": "order_query", "ok": False,
                "data": {"orders": []}, "error_category": err_cat, "events": events}


async def do_logistics(task, state, memory, ctx) -> dict:
    params = task.get("params", {})
    order_no = (params.get("orderNo") or "").strip()
    events = [_status_event("查询订单与物流实时状态（MCP）…", "logistics")]
    try:
        if not order_no:
            raw_orders = await call_tool("listOrders", {"userId": ctx["user_id"]})
            orders = json.loads(raw_orders) if isinstance(raw_orders, str) else raw_orders
            orders = [o for o in (orders if isinstance(orders, list) else [])
                      if o.get("status") not in ("cancelled", "pending")]
            events.append(_tool_event("listOrders", {"userId": ctx["user_id"]}, True,
                                      f"找到 {len(orders)} 笔可查询物流的订单"))
            if len(orders) != 1:
                return {"task_id": task["id"], "type": "logistics", "ok": True,
                        "data": {"needsOrderNo": True, "orders": orders[:5]}, "events": events}
            order_no = orders[0].get("orderNo") or ""
        args = {"userId": ctx["user_id"], "orderNo": order_no}
        raw = await call_tool("queryLogistics", args)
        data = json.loads(raw) if isinstance(raw, str) else raw
        events.append(_tool_event("queryLogistics", args, True,
                                  f"订单 {order_no} 物流状态查询完成"))
        return {"task_id": task["id"], "type": "logistics", "ok": True,
                "data": data if isinstance(data, dict) else {}, "events": events}
    except Exception as e:
        err_cat = classify_error(e)
        events.append(_tool_event("queryLogistics", {"orderNo": order_no}, False,
                                  f"物流查询失败: {e}", error_category=err_cat))
        return {"task_id": task["id"], "type": "logistics", "ok": False,
                "data": {}, "error_category": err_cat, "events": events}


async def do_aftersale(task, state, memory, ctx) -> dict:
    params = task.get("params", {})
    action = params.get("action") or "policy"
    events = [_status_event("查询售后政策与申请状态（MCP）…", "aftersale")]
    tool = "listAfterSales" if action == "query" else "getAfterSalePolicy"
    args = {"userId": ctx["user_id"]} if action == "query" else {}
    try:
        raw = await call_tool(tool, args)
        value = json.loads(raw) if isinstance(raw, str) else raw
        data = {"action": action}
        if action == "query":
            data["records"] = value if isinstance(value, list) else []
            summary = f"查到 {len(data['records'])} 条售后记录"
        else:
            data["policy"] = value if isinstance(value, dict) else {}
            summary = "已读取商城退换货政策（未创建退款申请）"
        events.append(_tool_event(tool, args, True, summary))
        return {"task_id": task["id"], "type": "aftersale", "ok": True,
                "data": data, "events": events}
    except Exception as e:
        err_cat = classify_error(e)
        events.append(_tool_event(tool, args, False, f"售后查询失败: {e}", error_category=err_cat))
        return {"task_id": task["id"], "type": "aftersale", "ok": False,
                "data": {"action": action}, "error_category": err_cat, "events": events}


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
    if t == "order_query":
        return await do_order_query(task, results, memory, ctx)
    if t == "logistics":
        return await do_logistics(task, results, memory, ctx)
    if t == "aftersale":
        return await do_aftersale(task, results, memory, ctx)
    return {"task_id": task["id"], "type": t, "ok": False,
            "data": {}, "events": [_tool_event(t, task.get("params", {}), False, f"未知任务类型 {t}")]}
