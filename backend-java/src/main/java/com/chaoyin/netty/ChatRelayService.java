package com.chaoyin.netty;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestTemplate;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;

import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * WS 聊天转发：把前端经 Netty 发来的消息交给 Agent（transport=ws），
 * Agent 生成过程的事件经 PushController 直接回推到 WS；
 * 这里只解析 Agent 返回的收尾事件（done/error）做兜底回推。
 */
@Slf4j
@Service
public class ChatRelayService {

    private final RestTemplate restTemplate;
    private final WsSessionRegistry registry;
    private final ObjectMapper mapper = new ObjectMapper();
    private final ExecutorService executor = Executors.newFixedThreadPool(4);

    @Value("${chaoyin.agent-url:http://localhost:8000}")
    private String agentUrl;

    @Value("${chaoyin.internal-api-key:chaoyin-dev-internal-key}")
    private String internalApiKey;

    public ChatRelayService(RestTemplate restTemplate, WsSessionRegistry registry) {
        this.restTemplate = restTemplate;
        this.registry = registry;
    }

    public void send(String sessionId, Long userId, String message) {
        executor.submit(() -> {
            try {
                Map<String, Object> body = Map.of(
                        "session_id", sessionId, "user_id", userId,
                        "message", message, "transport", "ws");
                HttpHeaders headers = new HttpHeaders();
                headers.set("X-Internal-Api-Key", internalApiKey);
                String resp = restTemplate.postForObject(
                        agentUrl + "/api/chat", new HttpEntity<>(body, headers), String.class);
                if (resp == null) {
                    return;
                }
                for (String line : resp.split("\n")) {
                    if (!line.startsWith("data:")) {
                        continue;
                    }
                    String payload = line.substring(5).trim();
                    if (payload.isEmpty()) {
                        continue;
                    }
                    try {
                        JsonNode ev = mapper.readTree(payload);
                        String t = ev.path("type").asText("");
                        if ("done".equals(t) || "error".equals(t)) {
                            registry.broadcast(sessionId, mapper.writeValueAsString(ev));
                        }
                    } catch (Exception ignore) {
                        // 非 JSON 行忽略
                    }
                }
            } catch (Exception e) {
                log.error("relay to agent failed: {}", e.getMessage());
                registry.broadcast(sessionId,
                        "{\"type\":\"error\",\"data\":{\"text\":\"Agent 服务不可用: " + e.getMessage() + "\"}}");
            }
        });
    }
}
