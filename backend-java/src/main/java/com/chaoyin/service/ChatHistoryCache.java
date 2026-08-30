package com.chaoyin.service;

import com.chaoyin.entity.ChatMessage;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Service;

import java.time.Duration;
import java.util.List;

/**
 * 会话历史缓存（Redis）。
 *
 * 隐私设计（缓存绝不能变成跨用户泄露通道）：
 * 1. 键绑定服务端身份：chat:hist:{userId}:{sessionId}。userId 只能来自
 *    token 解析或会话行的 owner，绝不接受客户端自报身份拼键；
 * 2. 归属校验前置：所有调用方必须先过 ChatSessionService.requireOwned/
 *    会话行 owner 比对，缓存只是 DB 读加速层，不是授权层；
 * 3. 写即失效 + 短 TTL：append/delete 后立刻 evict 本人键，TTL 默认 10 分钟；
 * 4. 全链路降级：Redis 不可用时静默回源 DB，不影响主链路。
 */
@Slf4j
@Service
public class ChatHistoryCache {

    private static final String KEY_PREFIX = "chat:hist:";
    private static final TypeReference<List<ChatMessage>> MESSAGE_LIST = new TypeReference<>() {
    };

    private final StringRedisTemplate redis;
    private final ObjectMapper mapper = new ObjectMapper()
            .registerModule(new JavaTimeModule())
            .disable(SerializationFeature.WRITE_DATES_AS_TIMESTAMPS);

    @Value("${app.cache.history-ttl-seconds:600}")
    private long ttlSeconds;

    public ChatHistoryCache(StringRedisTemplate redis) {
        this.redis = redis;
    }

    private String key(Long userId, String sessionId) {
        return KEY_PREFIX + userId + ":" + sessionId;
    }

    /** 读取缓存；userId 必须是已通过归属校验的服务端身份。任何异常都降级为 miss。 */
    public List<ChatMessage> get(Long userId, String sessionId) {
        try {
            String json = redis.opsForValue().get(key(userId, sessionId));
            if (json == null) {
                return null;
            }
            return mapper.readValue(json, MESSAGE_LIST);
        } catch (Exception e) {
            log.warn("history cache get failed (degrade to db): {}", e.getMessage());
            return null;
        }
    }

    public void put(Long userId, String sessionId, List<ChatMessage> messages) {
        try {
            redis.opsForValue().set(key(userId, sessionId),
                    mapper.writeValueAsString(messages), Duration.ofSeconds(ttlSeconds));
        } catch (Exception e) {
            log.warn("history cache put failed: {}", e.getMessage());
        }
    }

    /** 写路径失效：只删当前用户自己的键。 */
    public void evict(Long userId, String sessionId) {
        try {
            redis.delete(key(userId, sessionId));
        } catch (Exception e) {
            log.warn("history cache evict failed: {}", e.getMessage());
        }
    }
}
