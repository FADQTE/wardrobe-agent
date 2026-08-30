package com.chaoyin.controller;

import com.chaoyin.common.ApiResponse;
import com.chaoyin.entity.AfterSale;
import com.chaoyin.service.AfterSaleService;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;

import java.util.List;

@RestController
@RequestMapping("/api/after-sales")
@RequiredArgsConstructor
public class AfterSaleController {

    private final AfterSaleService afterSaleService;

    public record ApplyRequest(Long userId, Long orderId, String type, String reason) {
    }

    @GetMapping("/policy")
    public ApiResponse<AfterSaleService.Policy> policy() {
        return ApiResponse.ok(afterSaleService.policy());
    }

    @GetMapping
    public ApiResponse<List<AfterSale>> list(@RequestParam Long userId) {
        return ApiResponse.ok(afterSaleService.listByUser(userId));
    }

    @PostMapping
    public ApiResponse<AfterSale> apply(@RequestBody ApplyRequest req) {
        return ApiResponse.ok(afterSaleService.apply(
                req.userId(), req.orderId(), req.type(), req.reason()));
    }
}
