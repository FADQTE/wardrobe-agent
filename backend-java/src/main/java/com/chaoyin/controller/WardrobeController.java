package com.chaoyin.controller;

import com.chaoyin.common.ApiResponse;
import com.chaoyin.entity.WardrobeItem;
import com.chaoyin.service.WardrobeService;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;

import java.util.List;

@RestController
@RequestMapping("/api/wardrobe")
@RequiredArgsConstructor
public class WardrobeController {

    private final WardrobeService wardrobeService;

    @GetMapping
    public ApiResponse<List<WardrobeItem>> list(@RequestParam Long userId) {
        return ApiResponse.ok(wardrobeService.listByUser(userId));
    }

    @PostMapping
    public ApiResponse<WardrobeItem> add(@RequestBody WardrobeItem item) {
        return ApiResponse.ok(wardrobeService.add(item));
    }

    @PutMapping("/{id}")
    public ApiResponse<WardrobeItem> update(@PathVariable Long id, @RequestBody WardrobeItem patch) {
        return ApiResponse.ok(wardrobeService.update(id, patch));
    }

    @DeleteMapping("/{id}")
    public ApiResponse<Void> delete(@PathVariable Long id) {
        wardrobeService.delete(id);
        return ApiResponse.ok(null);
    }
}
