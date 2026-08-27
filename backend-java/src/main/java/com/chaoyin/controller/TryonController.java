package com.chaoyin.controller;

import com.chaoyin.common.ApiResponse;
import com.chaoyin.entity.TryonTask;
import com.chaoyin.service.TryonTaskService;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;

import java.util.List;

/**
 * 换装任务管理：Agent 创建任务、上报进度/结果；前端查询状态与结果地址。
 */
@RestController
@RequestMapping("/api/tryon")
@RequiredArgsConstructor
public class TryonController {

    private final TryonTaskService tryonTaskService;

    public record StatusRequest(String status, String resultUrl, String errorMsg) {
    }

    @PostMapping
    public ApiResponse<TryonTask> create(@RequestBody TryonTask task) {
        return ApiResponse.ok(tryonTaskService.create(task));
    }

    @PostMapping("/{id}/status")
    public ApiResponse<TryonTask> updateStatus(@PathVariable Long id, @RequestBody StatusRequest req) {
        return ApiResponse.ok(tryonTaskService.updateStatus(id, req.status(), req.resultUrl(), req.errorMsg()));
    }

    @GetMapping
    public ApiResponse<List<TryonTask>> list(@RequestParam(required = false) String sessionId) {
        return ApiResponse.ok(tryonTaskService.listBySession(sessionId));
    }

    @GetMapping("/{id}")
    public ApiResponse<TryonTask> get(@PathVariable Long id) {
        return ApiResponse.ok(tryonTaskService.get(id));
    }
}
