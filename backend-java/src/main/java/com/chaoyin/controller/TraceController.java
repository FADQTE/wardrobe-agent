package com.chaoyin.controller;

import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.chaoyin.common.ApiResponse;
import com.chaoyin.entity.TraceEvent;
import com.chaoyin.mapper.TraceEventMapper;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.Map;

/**
 * Trace 持久化接口：Agent 每轮把公开执行证据上报到这里，按 session 可查询复盘。
 * 只存公开摘要（事件名/工具名/引用标识/路径），不存系统提示词、CoT、密钥与隐私原文。
 */
@RestController
@RequestMapping("/api/internal/trace")
@RequiredArgsConstructor
public class TraceController {

    private final TraceEventMapper traceEventMapper;
    private final ObjectMapper mapper = new ObjectMapper();

    public record TraceRequest(String sessionId, String eventType, String category, Object payload) {
    }

    @PostMapping
    public ApiResponse<TraceEvent> record(@RequestBody TraceRequest req) {
        TraceEvent ev = new TraceEvent();
        ev.setSessionId(req.sessionId());
        ev.setEventType(req.eventType());
        ev.setCategory(req.category());
        try {
            ev.setPayload(mapper.writeValueAsString(req.payload() == null ? Map.of() : req.payload()));
        } catch (Exception e) {
            ev.setPayload("{}");
        }
        traceEventMapper.insert(ev);
        return ApiResponse.ok(ev);
    }

    @GetMapping("/{sessionId}")
    public ApiResponse<List<TraceEvent>> list(@PathVariable String sessionId,
                                              @RequestParam(defaultValue = "200") int limit) {
        return ApiResponse.ok(traceEventMapper.selectList(new QueryWrapper<TraceEvent>()
                .eq("session_id", sessionId)
                .orderByAsc("id")
                .last("LIMIT " + Math.min(Math.max(limit, 1), 500))));
    }
}
