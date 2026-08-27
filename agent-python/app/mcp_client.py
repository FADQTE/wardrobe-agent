# -*- coding: utf-8 -*-
"""MCP Client：连接 Java 侧 MCP Server（SSE 传输），把商城/衣橱工具接入 Agent。

langchain-mcp-adapters 0.1.7: MultiServerMCPClient.get_tools() 返回平铺的 List[BaseTool]。
"""
from __future__ import annotations

from typing import Optional

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


async def call_tool(name: str, args: dict):
    tool = tool_by_name(name)
    if tool is None:
        raise RuntimeError(f"MCP 工具不可用: {name}")
    return await tool.ainvoke(args)
