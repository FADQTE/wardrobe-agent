package com.chaoyin.config;

import com.chaoyin.mcp.MallTools;
import com.chaoyin.mcp.SmokeTools;
import org.springframework.ai.tool.ToolCallbackProvider;
import org.springframework.ai.tool.method.MethodToolCallbackProvider;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * 把 @Tool 工具 Bean 显式注册为 ToolCallbackProvider，
 * 供 MCP Server（McpServerAutoConfiguration）暴露给 Agent。
 */
@Configuration
public class McpToolsConfig {

    @Bean
    public ToolCallbackProvider mallToolCallbacks(MallTools mallTools, SmokeTools smokeTools) {
        return MethodToolCallbackProvider.builder()
                .toolObjects(mallTools, smokeTools)
                .build();
    }
}
