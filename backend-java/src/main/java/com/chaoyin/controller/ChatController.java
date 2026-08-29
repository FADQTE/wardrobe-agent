package com.chaoyin.controller;

import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.chaoyin.common.ApiResponse;
import com.chaoyin.entity.ChatMessage;
import com.chaoyin.entity.ChatSession;
import com.chaoyin.mapper.ChatMessageMapper;
import com.chaoyin.mapper.ChatSessionMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;

import java.util.Collections;
import java.util.List;
import java.util.Map;

/**
 * 会话持久化：Agent 通过内部接口保存 Session Memory 状态与消息记录。
 */
@RestController
@RequestMapping("/api/chat")
@RequiredArgsConstructor
public class ChatController {

    private final ChatSessionMapper sessionMapper;
    private final ChatMessageMapper messageMapper;

    @PostMapping("/sessions")
    public ApiResponse<ChatSession> upsertSession(@RequestBody ChatSession session) {
        ChatSession exist = sessionMapper.selectById(session.getId());
        if (exist == null) {
            sessionMapper.insert(session);
        } else {
            sessionMapper.updateById(session);
        }
        return ApiResponse.ok(session);
    }

    @GetMapping("/sessions/{id}/messages")
    public ApiResponse<List<ChatMessage>> messages(@PathVariable String id,
                                                   @RequestParam(defaultValue = "200") int limit) {
        // 只取最近 limit 条再正序返回：长会话不再每轮全量拉取
        List<ChatMessage> rows = messageMapper.selectList(new QueryWrapper<ChatMessage>()
                .eq("session_id", id).orderByDesc("id")
                .last("LIMIT " + Math.max(1, Math.min(limit, 500))));
        Collections.reverse(rows);
        return ApiResponse.ok(rows);
    }

    @PostMapping("/messages")
    public ApiResponse<Void> appendMessage(@RequestBody ChatMessage message) {
        message.setId(null);
        messageMapper.insert(message);
        return ApiResponse.ok(null);
    }

    @GetMapping("/sessions/{id}")
    public ApiResponse<Map<String, Object>> sessionState(@PathVariable String id) {
        ChatSession session = sessionMapper.selectById(id);
        return ApiResponse.ok(session == null ? Map.of() : Map.of("state", session.getState() == null ? "" : session.getState()));
    }
}
