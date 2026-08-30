package com.chaoyin.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * Trace 事件：每轮执行的公开证据（事件名/类别/脱敏载荷），按 session 持久化。
 */
@Data
@TableName("trace_event")
public class TraceEvent {
    @TableId(type = IdType.AUTO)
    private Long id;
    private String sessionId;
    private String eventType;
    /** entry | fact | knowledge | control | result | safety | cost */
    private String category;
    private String payload;
    private LocalDateTime createdAt;
}
