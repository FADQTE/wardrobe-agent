package com.chaoyin.controller;

import com.chaoyin.common.ApiResponse;
import com.chaoyin.entity.MallOrder;
import com.chaoyin.entity.OrderItem;
import com.chaoyin.service.OrderService;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.LinkedHashMap;
import java.util.Map;

@RestController
@RequestMapping("/api/orders")
@RequiredArgsConstructor
public class OrderController {

    private final OrderService orderService;
    private final com.chaoyin.service.AfterSaleService afterSaleService;

    public record CreateOrderRequest(Long userId, List<OrderService.ItemReq> items,
                                     String receiverName, String receiverPhone, String receiverAddress) {
    }

    @PostMapping
    public ApiResponse<MallOrder> create(@RequestBody CreateOrderRequest req) {
        return ApiResponse.ok(orderService.create(req.userId(), req.items(),
                req.receiverName(), req.receiverPhone(), req.receiverAddress()));
    }

    @GetMapping
    public ApiResponse<List<MallOrder>> list(@RequestParam Long userId) {
        return ApiResponse.ok(orderService.listByUser(userId));
    }

    @GetMapping("/{id}")
    public ApiResponse<Map<String, Object>> detail(@PathVariable Long id, @RequestParam Long userId) {
        MallOrder order = orderService.detailForUser(id, userId);
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("order", order);
        data.put("items", orderService.items(id));
        data.put("afterSale", afterSaleService.findByOrder(id, userId));
        return ApiResponse.ok(data);
    }

    @PostMapping("/{id}/pay")
    public ApiResponse<Void> pay(@PathVariable Long id, @RequestParam Long userId) {
        orderService.detailForUser(id, userId);
        orderService.pay(id);
        return ApiResponse.ok(null);
    }

    @PostMapping("/{id}/ship")
    public ApiResponse<MallOrder> ship(@PathVariable Long id) {
        return ApiResponse.ok(orderService.ship(id));
    }

    @PostMapping("/{id}/cancel")
    public ApiResponse<Void> cancel(@PathVariable Long id, @RequestParam Long userId) {
        orderService.cancelForUser(id, userId);
        return ApiResponse.ok(null);
    }
}
