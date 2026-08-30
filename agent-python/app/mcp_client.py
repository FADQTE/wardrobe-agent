# -*- coding: utf-8 -*-
"""MCP Client：连接 Java 侧 MCP Server（SSE 传输），把商城/衣橱工具接入 Agent。

langchain-mcp-adapters 0.1.7: MultiServerMCPClient.get_tools() 返回平铺的 List[BaseTool]。
"""
from __future__ import annotations

from typing import Optional

import httpx

from . import config

_mcp_client: Optional[object] = None
_tools: Optional[list] = None


async def get_mcp_tools() -> list:
    """返回 [BaseTool...]；连接失败返回空列表（不缓存，下次重试；Agent 可降级走 REST）。"""
    global _mcp_client, _tools
    if _tools:
        return _tools
    try:
        from langchain_mcp_adapters.client import MultiServerMCPClient
        _mcp_client = MultiServerMCPClient({
            "mall": {"url": config.JAVA_MCP_URL, "transport": "sse"},
        })
        tools = await _mcp_client.get_tools()
        if not isinstance(tools, list):
            tools = list(tools.values())[0] if tools else []
        if tools:
            _tools = tools
            print(f"[mcp] connected, tools={[t.name for t in _tools]}", flush=True)
        else:
            print("[mcp] connected but 0 tools registered on server", flush=True)
        return tools
    except Exception as e:
        print(f"[mcp] connect failed: {e}", flush=True)
        return []


def tool_by_name(name: str):
    """从 MCP 工具表中按名字取工具。"""
    if not _tools:
        return None
    for t in _tools:
        if t.name == name:
            return t
    return None


async def _api(method: str, path: str, **kwargs):
    async with httpx.AsyncClient(timeout=10, headers=config.JAVA_INTERNAL_HEADERS) as client:
        response = await client.request(method, f"{config.JAVA_API_URL}{path}", **kwargs)
        response.raise_for_status()
        body = response.json()
        if body.get("code") != 0:
            raise RuntimeError(body.get("msg") or f"Java API error: {body.get('code')}")
        return body.get("data")


async def _rest_fallback(name: str, args: dict):
    """MCP 连接不可用时的同源 Java REST 降级；业务校验仍由 Spring Boot 执行。"""
    user_id = args.get("userId")
    if name == "listWardrobe":
        return await _api("GET", "/wardrobe", params={"userId": user_id})
    if name == "searchProducts":
        params = {key: value for key, value in {
            "keyword": args.get("keyword"), "category": args.get("category"),
            "color": args.get("color"), "season": args.get("season"),
            "style": args.get("style"), "maxPrice": args.get("maxPrice"),
            "page": args.get("page", 1), "size": 10,
        }.items() if value not in (None, "")}
        page = await _api("GET", "/products", params=params)
        return {"products": page.get("records", []), "total": page.get("total", 0)}
    if name in ("getProduct", "checkStock"):
        product = await _api("GET", f"/products/{args.get('productId')}")
        if name == "checkStock":
            return {"productId": product.get("id"), "name": product.get("name"),
                    "stock": product.get("stock")}
        return product
    if name == "addFavorite":
        return await _api("POST", "/favorites", json={
            "userId": user_id, "productId": args.get("productId"),
        })
    if name == "createOrder":
        return await _api("POST", "/orders", json={
            "userId": user_id, "items": args.get("items") or [],
            "receiverName": args.get("receiverName"),
            "receiverPhone": args.get("receiverPhone"),
            "receiverAddress": args.get("receiverAddress"),
        })
    if name in ("listOrders", "queryOrder", "queryLogistics"):
        orders = await _api("GET", "/orders", params={"userId": user_id})
        if name == "listOrders":
            return orders
        order_no = args.get("orderNo")
        order = next((row for row in orders if row.get("orderNo") == order_no), None)
        if not order:
            raise RuntimeError(f"订单不存在或无权访问: {order_no}")
        if name == "queryOrder":
            return order
        hints = {
            "pending": "订单待支付，尚未发货", "paid": "已支付，等待发货",
            "shipped": "已发货，运输中", "done": "已签收", "cancelled": "订单已取消",
        }
        return {"orderNo": order_no, "status": order.get("status"),
                "logisticsNo": order.get("logisticsNo"),
                "hint": hints.get(order.get("status"), "订单状态未知")}
    if name == "getAfterSalePolicy":
        return await _api("GET", "/after-sales/policy")
    if name == "listAfterSales":
        return await _api("GET", "/after-sales", params={"userId": user_id})
    raise RuntimeError(f"MCP 工具 {name} 没有 REST 降级映射")


async def call_tool(name: str, args: dict):
    tool = tool_by_name(name)
    if tool is None:
        print(f"[mcp] {name} unavailable, fallback REST", flush=True)
        return await _rest_fallback(name, args)
    try:
        return await tool.ainvoke(args)
    except Exception:
        # 查询与收藏（幂等）可安全重试 REST；创建订单结果不确定时禁止重试，避免重复扣库存。
        if name != "createOrder":
            print(f"[mcp] {name} invocation failed, fallback REST", flush=True)
            return await _rest_fallback(name, args)
        raise
