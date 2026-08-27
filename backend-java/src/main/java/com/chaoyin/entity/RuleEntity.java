package com.chaoyin.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 穿搭/活动规则：版本 + 生效/失效时间 + 发布状态，支撑时效治理。
 */
@Data
@TableName("`rule`")
public class RuleEntity {
    @TableId(type = IdType.AUTO)
    private Long id;
    /** activity | outfit */
    private String type;
    private String title;
    private String content;
    /** JSON 数组字符串 */
    private String tags;
    private Integer version;
    private LocalDateTime effectiveFrom;
    private LocalDateTime effectiveTo;
    /** draft | published | offline */
    private String publishStatus;
    private String source;
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;
}
