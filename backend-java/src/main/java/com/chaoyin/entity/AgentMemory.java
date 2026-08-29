package com.chaoyin.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * Agent 长期记忆：episode(事件)/semantic(稳定事实)/profile(长期偏好)。
 * 冲突不覆盖：旧值置 superseded，新值携带 supersedesMemoryId 保留历史可答性。
 */
@Data
@TableName("agent_memory")
public class AgentMemory {
    @TableId(type = IdType.AUTO)
    private Long id;
    private Long userId;
    private String memoryType;
    private String subject;
    private String predicate;
    /** 结构化值 JSON（如 {"max":1000}），episode 可为空 */
    private String value;
    private String content;
    private Float importance;
    private Float confidence;
    /** user_explicit|user_behavior|agent_inference，推断不得与用户明确等权 */
    private String sourceType;
    private String sourceId;
    private String scope;
    private String status;
    private Long supersedesMemoryId;
    private Integer accessCount;
    private LocalDateTime lastAccessedAt;
    private LocalDateTime expiresAt;
    private Integer decayEnabled;
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;
}
