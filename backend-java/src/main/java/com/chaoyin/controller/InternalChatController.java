package com.chaoyin.controller;

import com.chaoyin.common.ApiResponse;
import com.chaoyin.entity.ChatMessage;
import com.chaoyin.entity.ChatSession;
import com.chaoyin.service.ChatSessionService;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.Map;

/** Agent 专用会话持久化接口，由 X-Internal-Api-Key 保护。 */
@RestController
@RequestMapping("/api/internal/chat")
@RequiredArgsConstructor
public class InternalChatController {
    private final ChatSessionService chatSessionService;

    @PostMapping("/sessions")
    public ApiResponse<ChatSession> upsertSession(@RequestBody ChatSession session) {
        return ApiResponse.ok(chatSessionService.internalUpsert(session));
    }

    @GetMapping("/sessions/{id}")
    public ApiResponse<Map<String, Object>> sessionState(@PathVariable String id) {
        ChatSession session = chatSessionService.internalGet(id);
        return ApiResponse.ok(session == null ? Map.of() : Map.of(
                "state", session.getState() == null ? "" : session.getState()));
    }

    @GetMapping("/sessions/{id}/messages")
    public ApiResponse<List<ChatMessage>> messages(@PathVariable String id,
                                                   @RequestParam(defaultValue = "200") int limit) {
        return ApiResponse.ok(chatSessionService.internalMessages(id, limit));
    }

    @PostMapping("/messages")
    public ApiResponse<Void> appendMessage(@RequestBody ChatMessage message) {
        chatSessionService.internalAppend(message);
        return ApiResponse.ok(null);
    }
}
