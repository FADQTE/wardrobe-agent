package com.chaoyin.controller;

import com.chaoyin.common.ApiResponse;
import com.chaoyin.common.BizException;
import com.chaoyin.entity.AgentMemory;
import com.chaoyin.service.MemoryService;
import lombok.Data;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.Locale;

/**
 * Agent 长期记忆内部接口：Python Agent 写入/精确查询/访问回写。
 */
@RestController
@RequestMapping("/api/memory")
@RequiredArgsConstructor
public class MemoryController {

    private final MemoryService memoryService;

    @Data
    public static class WriteRequest {
        private Long userId;
        private String memoryType;
        private String subject;
        private String predicate;
        private Object value;
        private String content;
        private Float importance;
        private Float confidence;
        private String sourceType;
        private String sourceId;
        private Object scope;
    }

    @PostMapping("/write")
    public ApiResponse<MemoryService.WriteResult> write(@RequestBody WriteRequest req) {
        if (req.getUserId() == null) {
            throw new BizException(400, "userId 不能为空");
        }
        MemoryService.WriteResult result = memoryService.write(toEntity(req));
        return ApiResponse.ok(result);
    }

    @GetMapping("/facts")
    public ApiResponse<List<AgentMemory>> facts(@RequestParam Long userId,
                                                @RequestParam(required = false) String predicates) {
        List<String> list = predicates == null || predicates.isBlank()
                ? List.of() : List.of(predicates.split(","));
        return ApiResponse.ok(memoryService.facts(userId, list));
    }

    @GetMapping("/list")
    public ApiResponse<List<AgentMemory>> list(@RequestParam(required = false) Long userId,
                                               @RequestParam(required = false) String memoryType,
                                               @RequestParam(defaultValue = "active") String status,
                                               @RequestParam(defaultValue = "50") int limit) {
        return ApiResponse.ok(memoryService.list(userId, memoryType, status, limit));
    }

    @PostMapping("/{id}/access")
    public ApiResponse<Void> touch(@PathVariable Long id) {
        memoryService.touch(id);
        return ApiResponse.ok(null);
    }

    @PostMapping("/{id}/invalid")
    public ApiResponse<Void> invalidate(@PathVariable Long id) {
        memoryService.invalidate(id);
        return ApiResponse.ok(null);
    }

    private AgentMemory toEntity(WriteRequest req) {
        AgentMemory memory = new AgentMemory();
        memory.setUserId(req.getUserId());
        memory.setMemoryType(req.getMemoryType() == null ? ""
                : req.getMemoryType().trim().toLowerCase(Locale.ROOT));
        memory.setSubject(req.getSubject());
        memory.setPredicate(req.getPredicate() == null ? ""
                : req.getPredicate().trim().toLowerCase(Locale.ROOT));
        memory.setValue(json(req.getValue()));
        memory.setContent(req.getContent());
        memory.setImportance(req.getImportance());
        memory.setConfidence(req.getConfidence());
        memory.setSourceType(req.getSourceType());
        memory.setSourceId(req.getSourceId());
        memory.setScope(json(req.getScope()));
        return memory;
    }

    private String json(Object value) {
        if (value == null) {
            return null;
        }
        if (value instanceof String s) {
            return s;
        }
        try {
            return new com.fasterxml.jackson.databind.ObjectMapper()
                    .writeValueAsString(value);
        } catch (Exception e) {
            return String.valueOf(value);
        }
    }
}
