package com.chaoyin.controller;

import com.chaoyin.common.ApiResponse;
import com.chaoyin.entity.AfterSale;
import com.chaoyin.entity.MallOrder;
import com.chaoyin.mapper.MallOrderMapper;
import com.chaoyin.service.AfterSaleService;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.Map;
import java.util.function.Function;
import java.util.stream.Collectors;

/**
 * 人工客服工作台接口：处理转人工的退款/售后申请。
 * 鉴权：登录态（拦截器统一校验）；本地演示环境未区分角色，
 * 生产环境需要在这里叠加客服角色校验。
 */
@RestController
@RequestMapping("/api/admin/aftersales")
@RequiredArgsConstructor
public class AdminAfterSaleController {

    private final AfterSaleService afterSaleService;
    private final MallOrderMapper orderMapper;

    public record ReviewRequest(String reason) {
    }

    public record AfterSaleRow(AfterSale sale, MallOrder order) {
    }

    @GetMapping
    public ApiResponse<List<AfterSaleRow>> list(@RequestParam(defaultValue = "pending") String status) {
        List<AfterSale> sales = afterSaleService.listByStatus(status);
        Map<Long, MallOrder> orders = sales.isEmpty() ? Map.of()
                : orderMapper.selectBatchIds(sales.stream().map(AfterSale::getOrderId).toList())
                .stream().collect(Collectors.toMap(MallOrder::getId, Function.identity()));
        return ApiResponse.ok(sales.stream()
                .map(sale -> new AfterSaleRow(sale, orders.get(sale.getOrderId())))
                .toList());
    }

    @PostMapping("/{id}/approve")
    public ApiResponse<AfterSale> approve(@PathVariable Long id,
                                          @RequestBody(required = false) ReviewRequest req) {
        return ApiResponse.ok(afterSaleService.approve(id, req == null ? null : req.reason()));
    }

    @PostMapping("/{id}/reject")
    public ApiResponse<AfterSale> reject(@PathVariable Long id,
                                         @RequestBody(required = false) ReviewRequest req) {
        return ApiResponse.ok(afterSaleService.reject(id, req == null ? null : req.reason()));
    }
}
