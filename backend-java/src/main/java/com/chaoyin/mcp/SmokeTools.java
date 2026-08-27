package com.chaoyin.mcp;

import org.springframework.ai.tool.annotation.Tool;
import org.springframework.ai.tool.annotation.ToolParam;
import org.springframework.stereotype.Component;

/**
 * M0 冒烟工具：验证 MCP Server 链路可用（Agent 侧可通过 MCP 调用 echo）。
 * M1 将替换为真实的商品/库存/订单/物流/衣橱工具。
 */
@Component
public class SmokeTools {

    @Tool(description = "回显输入文本，用于验证 MCP 链路连通性")
    public String echo(@ToolParam(description = "要回显的文本") String text) {
        return "echo: " + text;
    }
}
