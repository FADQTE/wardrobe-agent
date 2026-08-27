package com.chaoyin.controller;

import com.chaoyin.common.ApiResponse;
import com.chaoyin.netty.WsSessionRegistry;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.*;

import java.util.Map;

/**
 * 内部推送接口：Agent 生成过程中把事件（模型回复/生图进度/工具状态）
 * 逐个 POST 到这里，由 Netty WS 网关按 sessionId 隔离广播给前端。
 */
@Slf4j
@RestController
@RequestMapping("/api/internal")
@RequiredArgsConstructor
public class PushController {

    private final WsSessionRegistry registry;
    private final ObjectMapper mapper = new ObjectMapper();

    public record PushRequest(String sessionId, Object event) {
    }

    @PostMapping("/push")
    public ApiResponse<Map<String, Object>> push(@RequestBody PushRequest req) {
        if (req.sessionId() == null || req.sessionId().isBlank()) {
            return ApiResponse.fail(400, "sessionId 不能为空");
        }
        try {
            String json = mapper.writeValueAsString(req.event());
            int delivered = registry.broadcast(req.sessionId(), json);
            if (delivered == 0) {
                log.debug("push to session {} dropped (no live WS connection)", req.sessionId());
            }
            return ApiResponse.ok(Map.of("delivered", delivered));
        } catch (Exception e) {
            return ApiResponse.fail(500, "推送失败: " + e.getMessage());
        }
    }

    @GetMapping("/ws/status")
    public ApiResponse<Map<String, Object>> status() {
        return ApiResponse.ok(Map.of(
                "sessions", registry.sessionCount(),
                "transport", "netty-ws"));
    }
}
