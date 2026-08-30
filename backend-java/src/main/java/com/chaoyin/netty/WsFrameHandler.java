package com.chaoyin.netty;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.netty.channel.ChannelHandlerContext;
import io.netty.channel.SimpleChannelInboundHandler;
import io.netty.handler.codec.http.*;
import io.netty.handler.codec.http.websocketx.*;
import io.netty.handler.timeout.IdleState;
import io.netty.handler.timeout.IdleStateEvent;
import lombok.extern.slf4j.Slf4j;

import java.util.List;
import java.util.Map;

/**
 * WS 帧处理（自定义握手，兼容带 query 参数的 URI）：
 * - 手动完成 WebSocket 握手，从 query 解析 sessionId/userId（会话隔离）
 * - 应用层心跳：客户端 {"type":"ping"} → 服务端 {"type":"pong"}
 * - 空闲 90s 无任何帧 → 关闭连接（死连接清理）
 * - 聊天帧 {"type":"chat",...} 转发给 Agent（响应事件由 PushController 回推）
 *
 * 注：Netty 4.1.119 的 WebSocketServerProtocolHandler 对带 query 的 URI
 * 路径匹配有问题（握手无响应），故这里手动握手。
 */
@Slf4j
public class WsFrameHandler extends SimpleChannelInboundHandler<Object> {

    private final WsSessionRegistry registry;
    private final ChatRelayService relay;
    private final ObjectMapper mapper = new ObjectMapper();

    private WebSocketServerHandshaker handshaker;
    private boolean handshakeDone = false;
    private String sessionId;
    private Long userId = 1L;

    public WsFrameHandler(WsSessionRegistry registry, ChatRelayService relay) {
        this.registry = registry;
        this.relay = relay;
    }

    @Override
    protected void channelRead0(ChannelHandlerContext ctx, Object msg) {
        if (!handshakeDone) {
            if (msg instanceof FullHttpRequest req) {
                handleHandshake(ctx, req);
            } else {
                ctx.close();
            }
            return;
        }
        if (msg instanceof TextWebSocketFrame frame) {
            handleFrame(ctx, frame);
        } else if (msg instanceof CloseWebSocketFrame) {
            ctx.close();
        } else if (msg instanceof PingWebSocketFrame pongFrame) {
            ctx.writeAndFlush(new PongWebSocketFrame(pongFrame.content().retain()));
        }
        // PongWebSocketFrame / BinaryWebSocketFrame 忽略
    }

    private void handleHandshake(ChannelHandlerContext ctx, FullHttpRequest req) {
        QueryStringDecoder qs = new QueryStringDecoder(req.uri());
        if (!"/ws/chat".equals(qs.path())) {
            ctx.writeAndFlush(new DefaultFullHttpResponse(HttpVersion.HTTP_1_1, HttpResponseStatus.NOT_FOUND));
            ctx.close();
            return;
        }
        sessionId = first(qs.parameters(), "sessionId");
        String uid = first(qs.parameters(), "userId");
        if (uid != null && !uid.isBlank()) {
            userId = Long.parseLong(uid);
        }
        if (sessionId == null || sessionId.isBlank()) {
            ctx.writeAndFlush(new DefaultFullHttpResponse(HttpVersion.HTTP_1_1, HttpResponseStatus.BAD_REQUEST));
            ctx.close();
            return;
        }
        String url = "ws://" + req.headers().get(HttpHeaderNames.HOST) + req.uri();
        WebSocketServerHandshakerFactory factory = new WebSocketServerHandshakerFactory(url, null, true);
        handshaker = factory.newHandshaker(req);
        if (handshaker == null) {
            WebSocketServerHandshakerFactory.sendUnsupportedVersionResponse(ctx.channel());
            return;
        }
        handshaker.handshake(ctx.channel(), req);
        handshakeDone = true;
        registry.register(sessionId, ctx.channel());
        ctx.channel().writeAndFlush(new TextWebSocketFrame(
                "{\"type\":\"welcome\",\"data\":{\"sessionId\":\"" + sessionId + "\",\"transport\":\"netty-ws\"}}"));
        log.info("WS connected: session={} userId={} channel={}", sessionId, userId, ctx.channel().id());
    }

    private void handleFrame(ChannelHandlerContext ctx, TextWebSocketFrame frame) {
        String text = frame.text();
        try {
            JsonNode node = mapper.readTree(text);
            String type = node.path("type").asText("");
            switch (type) {
                case "ping" -> ctx.channel().writeAndFlush(new TextWebSocketFrame("{\"type\":\"pong\"}"));
                case "chat" -> {
                    String message = node.path("message").asText("");
                    String sid = node.hasNonNull("sessionId") ? node.path("sessionId").asText() : sessionId;
                    long uid = node.hasNonNull("userId") ? node.path("userId").asLong() : userId;
                    if (message.isBlank()) {
                        ctx.channel().writeAndFlush(new TextWebSocketFrame(
                                "{\"type\":\"error\",\"data\":{\"text\":\"消息不能为空\"}}"));
                        return;
                    }
                    // 帧内身份不得覆盖握手身份，否则可把事件投递到别人的会话或冒用 userId。
                    if (!sessionId.equals(sid) || !userId.equals(uid)) {
                        ctx.channel().writeAndFlush(new TextWebSocketFrame(
                                "{\"type\":\"error\",\"data\":{\"text\":\"会话身份与握手不一致\"}}"));
                        log.warn("WS identity mismatch: handshake session={} userId={}, frame session={} userId={}",
                                sessionId, userId, sid, uid);
                        return;
                    }
                    log.info("WS chat relay: session={} userId={} msg={}", sessionId, userId, message);
                    relay.send(sessionId, userId, message);
                }
                default -> log.warn("WS unknown frame type: {}", type);
            }
        } catch (Exception e) {
            log.warn("WS frame parse failed: {}", text, e);
        }
    }

    @Override
    public void userEventTriggered(ChannelHandlerContext ctx, Object evt) throws Exception {
        if (evt instanceof IdleStateEvent idle && idle.state() == IdleState.ALL_IDLE) {
            log.info("WS heartbeat timeout, closing: session={}", sessionId);
            ctx.close();
            return;
        }
        super.userEventTriggered(ctx, evt);
    }

    @Override
    public void channelInactive(ChannelHandlerContext ctx) {
        if (sessionId != null) {
            registry.unregister(sessionId, ctx.channel());
            log.info("WS disconnected: session={} channel={}", sessionId, ctx.channel().id());
        }
    }

    @Override
    public void exceptionCaught(ChannelHandlerContext ctx, Throwable cause) {
        log.warn("WS channel error: {}", cause.getMessage());
        ctx.close();
    }

    private static String first(Map<String, List<String>> params, String key) {
        List<String> values = params.get(key);
        return values == null || values.isEmpty() ? null : values.get(0);
    }
}
