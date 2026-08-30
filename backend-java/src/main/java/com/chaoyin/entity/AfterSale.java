package com.chaoyin.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.math.BigDecimal;
import java.time.LocalDateTime;

@Data
@TableName("after_sale")
public class AfterSale {
    @TableId(type = IdType.AUTO)
    private Long id;
    private String requestNo;
    private Long orderId;
    private Long userId;
    /** refund | return_refund | exchange */
    private String type;
    /** pending | approved | rejected | completed */
    private String status;
    private String reason;
    private BigDecimal amount;
    /** auto=规则自动审核 | manual=人工审核 | null=未判定 */
    private String reviewSource;
    /** 审核判定说明（为什么自动通过/为什么转人工/人工结论） */
    private String reviewReason;
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;
}
