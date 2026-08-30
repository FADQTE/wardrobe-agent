package com.chaoyin.controller;

import com.chaoyin.common.ApiResponse;
import com.chaoyin.entity.ChatMessage;
import com.chaoyin.entity.ChatSession;
import com.chaoyin.service.ChatSessionService;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;

import java.util.List;

/** 面向已登录用户的会话管理接口。 */
@RestController
@RequestMapping("/api/chat/sessions")
@RequiredArgsConstructor
public class ChatController {
    private final ChatSessionService chatSessionService;

    public record RenameRequest(String title) {
    }

    @GetMapping
    public ApiResponse<List<ChatSession>> list(@RequestAttribute("currentUserId") Long userId) {
        return ApiResponse.ok(chatSessionService.list(userId));
    }

    @PostMapping
    public ApiResponse<ChatSession> create(@RequestAttribute("currentUserId") Long userId) {
        return ApiResponse.ok(chatSessionService.create(userId));
    }

    @PatchMapping("/{id}")
    public ApiResponse<ChatSession> rename(@PathVariable String id,
                                           @RequestAttribute("currentUserId") Long userId,
                                           @RequestBody RenameRequest request) {
        return ApiResponse.ok(chatSessionService.rename(id, userId, request.title()));
    }

    @DeleteMapping("/{id}")
    public ApiResponse<Void> delete(@PathVariable String id,
                                    @RequestAttribute("currentUserId") Long userId) {
        chatSessionService.delete(id, userId);
        return ApiResponse.ok(null);
    }

    @GetMapping("/{id}/messages")
    public ApiResponse<List<ChatMessage>> messages(@PathVariable String id,
                                                   @RequestAttribute("currentUserId") Long userId,
                                                   @RequestParam(defaultValue = "200") int limit) {
        return ApiResponse.ok(chatSessionService.messages(id, userId, limit));
    }
}
