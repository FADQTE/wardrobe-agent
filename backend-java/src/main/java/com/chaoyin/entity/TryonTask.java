package com.chaoyin.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 换装任务（mock 生图）：统一管理输入参数、任务状态与结果地址。
 */
@Data
@TableName("tryon_task")
public class TryonTask {
    @TableId(type = IdType.AUTO)
    private Long id;
    private String sessionId;
    private Long userId;
    private String personImage;
    /** JSON 数组字符串 */
    private String garmentIds;
    private String params;
    /** pending | processing | done | failed */
    private String status;
    private String resultUrl;
    private String errorMsg;
    private LocalDateTime createdAt;
    private LocalDateTime finishedAt;
}
