package com.chaoyin.netty;

import com.chaoyin.mq.ChatTurnMessage;
import com.chaoyin.mq.ChatTurnProducer;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestTemplate;

import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * WS 聊天转发：默认经 RocketMQ lite topic 削峰（sessionId 作 shardingKey，
 * 会话内 FIFO），由 ChatTurnConsumer 有序驱动 Agent；
 * MQ 关闭或入队失败时退回线程池同步转发（降级路径，不丢消息）。
 * Agent 生成过程的事件经 PushController 直接回推到 WS；
 * 这里只解析 Agent 返回的收尾事件（done/error）做兜底回推。
 */
@Slf4j
@Service
public class ChatRelayService {

    private final RestTemplate restTemplate;
    private final WsSessionRegistry registry;
    private final ChatTurnProducer producer;
    private final ObjectMapper mapper = new ObjectMapper();
    private final ExecutorService executor = Executors.newFixedThreadPool(8);

    @Value("${app.agent-url:http://localhost:16546}")
    private String agentUrl;

    @Value("${app.internal-api-key:local-internal-key}")
    private String internalApiKey;

    @Value("${app.mq.enabled:true}")
    private boolean mqEnabled;

    public ChatRelayService(RestTemplate restTemplate, WsSessionRegistry registry,
                            ChatTurnProducer producer) {
        this.restTemplate = restTemplate;
        this.registry = registry;
        this.producer = producer;
    }

    public void send(String sessionId, Long userId, String message) {
        send(sessionId, userId, message, "silver", "low", Map.of("page", "chat"));
    }

    public void send(String sessionId, Long userId, String message,
                     String memberLevel, String riskLevel, Map<String, Object> pageContext) {
        if (mqEnabled) {
            try {
                ChatTurnMessage turn = new ChatTurnMessage();
                turn.setSessionId(sessionId);
                turn.setUserId(userId);
                turn.setMessage(message);
                turn.setMemberLevel(memberLevel);
                turn.setRiskLevel(riskLevel);
                turn.setPageContext(pageContext);
                turn.setEnqueuedAt(System.currentTimeMillis());
                producer.submit(turn);
                // 入队回执：用户立刻知道消息已受理，处理进度经既有事件通道推送
                broadcast(sessionId, "{\"type\":\"status\",\"data\":{\"text\":\"消息已提交，排队处理中…\",\"stage\":\"queue\"}}");
                return;
            } catch (Exception e) {
                log.warn("enqueue failed, fallback to direct dispatch: {}", e.getMessage());
            }
        }
        executor.submit(() -> dispatchToAgent(sessionId, userId, message, memberLevel, riskLevel, pageContext));
    }

    /** 驱动 Agent 执行一轮（MQ 消费者与降级路径共用）。事件仍走 Agent → PushController 通道。 */
    public void dispatchToAgent(String sessionId, Long userId, String message,
                                String memberLevel, String riskLevel, Map<String, Object> pageContext) {
        try {
            Map<String, Object> body = Map.of(
                    "session_id", sessionId, "user_id", userId,
                    "message", message, "transport", "ws",
                    "member_level", memberLevel == null ? "silver" : memberLevel,
                    "risk_level", riskLevel == null ? "low" : riskLevel,
                    "page_context", pageContext == null ? Map.of("page", "chat") : pageContext);
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
            broadcastError(sessionId, "Agent 服务不可用: " + e.getMessage());
        }
    }

    public void broadcast(String sessionId, String json) {
        registry.broadcast(sessionId, json);
    }

    public void broadcastError(String sessionId, String text) {
        try {
            registry.broadcast(sessionId, mapper.writeValueAsString(
                    Map.of("type", "error", "data", Map.of("text", text))));
        } catch (Exception ignore) {
            // 序列化失败则退化为手工 JSON
            registry.broadcast(sessionId,
                    "{\"type\":\"error\",\"data\":{\"text\":\"处理失败，请重试\"}}");
        }
    }
}
