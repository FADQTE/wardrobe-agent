package com.chaoyin.controller;

import com.chaoyin.common.ApiResponse;
import com.chaoyin.common.BizException;
import com.chaoyin.service.CartService;
import jakarta.servlet.http.HttpServletRequest;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;

import java.util.List;

/** 购物车：登录用户维度落库，商城页与 AI 对话操作同一份数据。 */
@RestController
@RequestMapping("/api/cart")
@RequiredArgsConstructor
public class CartController {

    private final CartService cartService;

    public record AddRequest(Long productId, Integer quantity) {
    }

    public record UpdateRequest(Integer quantity) {
    }

    /**
     * 身份解析：浏览器 token 用户取拦截器写入的 currentUserId（优先）；
     * Agent 内部密钥通道没有该属性，回退到调用方显式传的 userId。
     */
    private static Long requireUser(HttpServletRequest request, Long fallback) {
        Object attr = request.getAttribute("currentUserId");
        if (attr instanceof Long id) {
            return id;
        }
        if (fallback != null) {
            return fallback;
        }
        throw new BizException(401, "未登录");
    }

    @GetMapping
    public ApiResponse<List<CartService.CartLine>> list(HttpServletRequest request,
                                                        @RequestParam(required = false) Long userId) {
        return ApiResponse.ok(cartService.list(requireUser(request, userId)));
    }

    @PostMapping
    public ApiResponse<CartService.CartLine> add(HttpServletRequest request,
                                                 @RequestParam(required = false) Long userId,
                                                 @RequestBody AddRequest req) {
        return ApiResponse.ok(cartService.add(requireUser(request, userId),
                req.productId(), req.quantity() == null ? 1 : req.quantity()));
    }

    @PatchMapping("/{id}")
    public ApiResponse<Void> update(@PathVariable Long id, HttpServletRequest request,
                                    @RequestParam(required = false) Long userId,
                                    @RequestBody UpdateRequest req) {
        cartService.updateQuantity(requireUser(request, userId), id,
                req.quantity() == null ? 1 : req.quantity());
        return ApiResponse.ok(null);
    }

    @DeleteMapping("/{id}")
    public ApiResponse<Void> remove(@PathVariable Long id, HttpServletRequest request,
                                    @RequestParam(required = false) Long userId) {
        cartService.remove(requireUser(request, userId), id);
        return ApiResponse.ok(null);
    }
}
