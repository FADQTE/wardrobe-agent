package com.chaoyin.netty;

import io.netty.channel.Channel;
import io.netty.handler.codec.http.websocketx.TextWebSocketFrame;
import org.springframework.stereotype.Component;

import java.util.Map;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;

/**
 * WS 会话注册表：sessionId → Channel 集合。
 * 会话隔离：事件只广播给同一 sessionId 的连接；
 * 重连友好：同一 sessionId 允许多个连接（旧连接关闭时自动注销）。
 */
@Component
public class WsSessionRegistry {

    private final Map<String, Set<Channel>> groups = new ConcurrentHashMap<>();

    public void register(String sessionId, Channel channel) {
        groups.computeIfAbsent(sessionId, k -> ConcurrentHashMap.newKeySet()).add(channel);
    }

    public void unregister(String sessionId, Channel channel) {
        Set<Channel> set = groups.get(sessionId);
        if (set != null) {
            set.remove(channel);
            if (set.isEmpty()) {
                groups.remove(sessionId, set);
            }
        }
    }

    /** 向指定会话的所有在线连接广播 JSON 事件，返回送达连接数。 */
    public int broadcast(String sessionId, String json) {
        Set<Channel> set = groups.get(sessionId);
        if (set == null || set.isEmpty()) {
            return 0;
        }
        int delivered = 0;
        for (Channel ch : set) {
            if (ch.isActive()) {
                ch.writeAndFlush(new TextWebSocketFrame(json));
                delivered++;
            }
        }
        return delivered;
    }

    public int sessionCount() {
        return groups.size();
    }
}
