# -*- coding: utf-8 -*-
import unittest
from unittest.mock import AsyncMock, patch

from app import mcp_client


class McpRestFallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_mcp_tool_falls_back_to_same_java_service(self):
        fallback = AsyncMock(return_value=[{"orderNo": "CY1"}])
        with patch.object(mcp_client, "_tools", None), \
                patch("app.mcp_client._rest_fallback", new=fallback):
            result = await mcp_client.call_tool("listOrders", {"userId": 7})

        self.assertEqual([{"orderNo": "CY1"}], result)
        fallback.assert_awaited_once_with("listOrders", {"userId": 7})

    async def test_read_failure_can_retry_rest(self):
        tool = AsyncMock()
        tool.name = "queryLogistics"
        tool.ainvoke.side_effect = RuntimeError("MCP transport closed")
        fallback = AsyncMock(return_value={"status": "shipped"})
        with patch.object(mcp_client, "_tools", [tool]), \
                patch("app.mcp_client._rest_fallback", new=fallback):
            result = await mcp_client.call_tool(
                "queryLogistics", {"userId": 7, "orderNo": "CY1"})

        self.assertEqual("shipped", result["status"])
        fallback.assert_awaited_once()

    async def test_uncertain_create_order_is_never_retried(self):
        tool = AsyncMock()
        tool.name = "createOrder"
        tool.ainvoke.side_effect = RuntimeError("timeout after send")
        fallback = AsyncMock()
        with patch.object(mcp_client, "_tools", [tool]), \
                patch("app.mcp_client._rest_fallback", new=fallback):
            with self.assertRaisesRegex(RuntimeError, "timeout after send"):
                await mcp_client.call_tool("createOrder", {"userId": 7, "items": []})

        fallback.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
