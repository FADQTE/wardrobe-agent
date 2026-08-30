package com.chaoyin.mq;

import lombok.Data;

import java.util.Map;

/** 一轮对话任务：WS 入口接受后落 lite topic，由有序消费者驱动 Agent 执行。 */
@Data
public class ChatTurnMessage {
    private String sessionId;
    private Long userId;
    private String message;
    /** Runtime Context：服务端可信字段，随消息透传给 Agent */
    private String memberLevel;
    private String riskLevel;
    private Map<String, Object> pageContext;
    private long enqueuedAt;
}
