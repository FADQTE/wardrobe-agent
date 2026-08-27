package com.chaoyin.controller;

import com.chaoyin.common.ApiResponse;
import com.chaoyin.entity.RuleEntity;
import com.chaoyin.service.RuleService;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;

import java.util.List;

@RestController
@RequestMapping("/api/rules")
@RequiredArgsConstructor
public class RuleController {

    private final RuleService ruleService;

    @GetMapping
    public ApiResponse<List<RuleEntity>> list(
            @RequestParam(required = false) String type,
            @RequestParam(required = false) String status) {
        return ApiResponse.ok(ruleService.list(type, status));
    }

    @GetMapping("/{id}")
    public ApiResponse<RuleEntity> get(@PathVariable Long id) {
        return ApiResponse.ok(ruleService.get(id));
    }

    @PostMapping
    public ApiResponse<RuleEntity> create(@RequestBody RuleEntity rule) {
        return ApiResponse.ok(ruleService.create(rule));
    }

    @PutMapping("/{id}")
    public ApiResponse<RuleEntity> update(@PathVariable Long id, @RequestBody RuleEntity patch) {
        return ApiResponse.ok(ruleService.update(id, patch));
    }

    /** 发布：增量更新 ES 索引、下架旧版本关联缓存。 */
    @PostMapping("/{id}/publish")
    public ApiResponse<RuleEntity> publish(@PathVariable Long id) {
        return ApiResponse.ok(ruleService.publish(id));
    }

    @PostMapping("/{id}/offline")
    public ApiResponse<RuleEntity> offline(@PathVariable Long id) {
        return ApiResponse.ok(ruleService.offline(id));
    }
}
