package com.chaoyin.mq;

import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.extern.slf4j.Slf4j;
import org.apache.rocketmq.spring.core.RocketMQTemplate;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

/**
 * 聊天轮次生产者（lite topic 模式）。
 *
 * 「lite topic」：不为每个会话建独立 topic（会话量大会把 topic/队列撑爆），
 * 而是用一个固定主题，发送时以 sessionId 为 shardingKey 做队列哈希——
 * 同一会话的轮次永远落在同一队列，队列内严格 FIFO，天然保证会话内顺序；
 * 不同会话分散到不同队列并行消费。C 端高并发下请求先排队、消费端按
 * 队列数限速驱动 Agent，起到削峰填谷作用。
 */
@Slf4j
@Service
public class ChatTurnProducer {

    private final RocketMQTemplate template;
    private final ObjectMapper mapper = new ObjectMapper();

    @Value("${app.mq.chat-turn-topic:chat_turn_topic}")
    private String topic;

    public ChatTurnProducer(RocketMQTemplate template) {
        this.template = template;
    }

    /** shardingKey=sessionId：同会话同队列（有序），跨会话哈希分散（并行）。 */
    public void submit(ChatTurnMessage msg) {
        try {
            String json = mapper.writeValueAsString(msg);
            template.syncSendOrderly(topic, json, msg.getSessionId());
            log.info("turn enqueued: session={} user={}", msg.getSessionId(), msg.getUserId());
        } catch (Exception e) {
            // 发送失败抛给调用方走同步降级路径，绝不丢用户消息
            throw new RuntimeException("enqueue chat turn failed: " + e.getMessage(), e);
        }
    }
}
