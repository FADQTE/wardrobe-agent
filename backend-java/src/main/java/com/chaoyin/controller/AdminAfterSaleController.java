package com.chaoyin.controller;

import com.chaoyin.common.ApiResponse;
import com.chaoyin.common.BizException;
import com.chaoyin.entity.AfterSale;
import com.chaoyin.entity.MallOrder;
import com.chaoyin.mapper.MallOrderMapper;
import com.chaoyin.service.AfterSaleService;
import jakarta.servlet.http.HttpServletRequest;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.Map;
import java.util.function.Function;
import java.util.stream.Collectors;

/**
 * 人工客服工作台接口：处理转人工的退款/售后申请。
 * 鉴权：X-Internal-Api-Key 管理密钥（与内部接口同一密钥，页面输入一次）。
 * 拦截器已先校验该密钥；此处二次校验，防止误配后管理接口裸奔。
 */
@RestController
@RequestMapping("/api/admin/aftersales")
@RequiredArgsConstructor
public class AdminAfterSaleController {

    private final AfterSaleService afterSaleService;
    private final MallOrderMapper orderMapper;

    @Value("${app.internal-api-key:local-internal-key}")
    private String internalApiKey;

    public record ReviewRequest(String reason) {
    }

    public record AfterSaleRow(AfterSale sale, MallOrder order) {
    }

    private void requireAdmin(HttpServletRequest request) {
        String key = request.getHeader("X-Internal-Api-Key");
        if (internalApiKey == null || !internalApiKey.equals(key)) {
            throw new BizException(403, "管理密钥错误");
        }
    }

    @GetMapping
    public ApiResponse<List<AfterSaleRow>> list(HttpServletRequest request,
                                                @RequestParam(defaultValue = "pending") String status) {
        requireAdmin(request);
        List<AfterSale> sales = afterSaleService.listByStatus(status);
        Map<Long, MallOrder> orders = sales.isEmpty() ? Map.of()
                : orderMapper.selectBatchIds(sales.stream().map(AfterSale::getOrderId).toList())
                .stream().collect(Collectors.toMap(MallOrder::getId, Function.identity()));
        return ApiResponse.ok(sales.stream()
                .map(sale -> new AfterSaleRow(sale, orders.get(sale.getOrderId())))
                .toList());
    }

    @PostMapping("/{id}/approve")
    public ApiResponse<AfterSale> approve(@PathVariable Long id, HttpServletRequest request,
                                          @RequestBody(required = false) ReviewRequest req) {
        requireAdmin(request);
        return ApiResponse.ok(afterSaleService.approve(id, req == null ? null : req.reason()));
    }

    @PostMapping("/{id}/reject")
    public ApiResponse<AfterSale> reject(@PathVariable Long id, HttpServletRequest request,
                                         @RequestBody(required = false) ReviewRequest req) {
        requireAdmin(request);
        return ApiResponse.ok(afterSaleService.reject(id, req == null ? null : req.reason()));
    }
}
