package com.chaoyin.netty;

import io.netty.bootstrap.ServerBootstrap;
import io.netty.channel.*;
import io.netty.channel.nio.NioEventLoopGroup;
import io.netty.channel.socket.SocketChannel;
import io.netty.channel.socket.nio.NioServerSocketChannel;
import io.netty.handler.codec.http.HttpObjectAggregator;
import io.netty.handler.codec.http.HttpServerCodec;
import io.netty.handler.timeout.IdleStateHandler;
import jakarta.annotation.PostConstruct;
import jakarta.annotation.PreDestroy;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

/**
 * Netty NIO WebSocket 推送网关（独立端口 8090，与 Tomcat 8080 分离）：
 * 负责向浏览器推送模型回复、生图进度与工具状态事件，支持心跳、重连与会话隔离。
 */
@Slf4j
@Component
public class NettyWsServer {

    private final WsSessionRegistry registry;
    private final ChatRelayService relay;

    @Value("${chaoyin.netty.port:8090}")
    private int port;

    private EventLoopGroup bossGroup;
    private EventLoopGroup workerGroup;
    private Channel serverChannel;

    public NettyWsServer(WsSessionRegistry registry, ChatRelayService relay) {
        this.registry = registry;
        this.relay = relay;
    }

    @PostConstruct
    public void start() {
        bossGroup = new NioEventLoopGroup(1);
        workerGroup = new NioEventLoopGroup();
        try {
            ServerBootstrap bootstrap = new ServerBootstrap();
            bootstrap.group(bossGroup, workerGroup)
                    .channel(NioServerSocketChannel.class)
                    .option(ChannelOption.SO_BACKLOG, 128)
                    .childOption(ChannelOption.SO_KEEPALIVE, true)
                    .childHandler(new ChannelInitializer<SocketChannel>() {
                        @Override
                        protected void initChannel(SocketChannel ch) {
                            ch.pipeline()
                                    .addLast(new HttpServerCodec())
                                    .addLast(new HttpObjectAggregator(8192))
                                    // 90s 无任何帧（心跳会重置）判定为死连接
                                    .addLast(new IdleStateHandler(0, 0, 90))
                                    .addLast(new WsFrameHandler(registry, relay));
                        }
                    });
            serverChannel = bootstrap.bind(port).sync().channel();
            log.info("Netty WS 推送网关已启动: ws://localhost:{}/ws/chat", port);
        } catch (Exception e) {
            log.error("Netty WS 网关启动失败", e);
        }
    }

    @PreDestroy
    public void stop() {
        if (serverChannel != null) {
            serverChannel.close();
        }
        if (bossGroup != null) {
            bossGroup.shutdownGracefully();
        }
        if (workerGroup != null) {
            workerGroup.shutdownGracefully();
        }
        log.info("Netty WS 推送网关已停止");
    }
}
