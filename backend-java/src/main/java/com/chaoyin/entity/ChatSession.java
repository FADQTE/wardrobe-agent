package com.chaoyin.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

@Data
@TableName("chat_session")
public class ChatSession {
    @TableId(type = IdType.INPUT)
    private String id;
    private Long userId;
    private String title;
    /** Session Memory 状态 JSON：人物形象/选中单品/候选搭配 */
    private String state;
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;
}
