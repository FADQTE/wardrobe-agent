package com.chaoyin.mq;

import com.chaoyin.netty.ChatRelayService;
import lombok.extern.slf4j.Slf4j;
import org.apache.rocketmq.spring.annotation.ConsumeMode;
import org.apache.rocketmq.spring.annotation.MessageModel;
import org.apache.rocketmq.spring.annotation.RocketMQMessageListener;
import org.apache.rocketmq.spring.core.RocketMQListener;
import org.springframework.stereotype.Component;

/**
 * 聊天轮次有序消费者。
 *
 * ConsumeMode.ORDERLY：队列内单线程顺序消费 → 同一会话的轮次严格按提交顺序执行，
 * 与 Agent 侧的 per-session 锁形成双重串行保障；队列数即全局并发上限，
 * 高峰期请求在队列中排队而不是把 Agent/LLM 打挂（削峰）。
 *
 * 失败策略：消费异常不向上抛（顺序消费抛异常会阻塞队列并无限重试），
 * 记日志 + 给用户回推错误事件后跳过，本轮失败由用户重发。
 */
@Slf4j
@Component
@RocketMQMessageListener(
        topic = "${app.mq.chat-turn-topic:chat_turn_topic}",
        consumerGroup = "chat-turn-consumer",
        consumeMode = ConsumeMode.ORDERLY,
        consumeThreadNumber = 8,
        messageModel = MessageModel.CLUSTERING)
public class ChatTurnConsumer implements RocketMQListener<String> {

    private final ChatRelayService relay;
    private final com.fasterxml.jackson.databind.ObjectMapper mapper = new com.fasterxml.jackson.databind.ObjectMapper();

    public ChatTurnConsumer(ChatRelayService relay) {
        this.relay = relay;
    }

    @Override
    public void onMessage(String json) {
        try {
            ChatTurnMessage msg = mapper.readValue(json, ChatTurnMessage.class);
            log.info("turn consumed: session={} user={} queueWaitMs={}",
                    msg.getSessionId(), msg.getUserId(), System.currentTimeMillis() - msg.getEnqueuedAt());
            relay.dispatchToAgent(msg.getSessionId(), msg.getUserId(), msg.getMessage(),
                    msg.getMemberLevel(), msg.getRiskLevel(), msg.getPageContext());
        } catch (Exception e) {
            log.error("consume chat turn failed, skipped: {}", e.getMessage(), e);
            try {
                ChatTurnMessage msg = mapper.readValue(json, ChatTurnMessage.class);
                relay.broadcastError(msg.getSessionId(),
                        "本轮消息处理失败，请重新发送（" + e.getMessage() + "）");
            } catch (Exception ignore) {
                // 消息体损坏时无从回推，仅记录
            }
        }
    }
}
