package com.chaoyin.controller;

import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.chaoyin.common.ApiResponse;
import com.chaoyin.entity.Product;
import com.chaoyin.service.ProductService;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;

import java.math.BigDecimal;

@RestController
@RequestMapping("/api/products")
@RequiredArgsConstructor
public class ProductController {

    private final ProductService productService;

    /** 商城兜底检索（MySQL）；商城页与 Agent 的混合检索走 ES（agent-python）。 */
    @GetMapping
    public ApiResponse<Page<Product>> page(
            @RequestParam(required = false) String keyword,
            @RequestParam(required = false) String category,
            @RequestParam(required = false) String color,
            @RequestParam(required = false) String season,
            @RequestParam(required = false) String style,
            @RequestParam(required = false) BigDecimal maxPrice,
            @RequestParam(defaultValue = "1") int page,
            @RequestParam(defaultValue = "12") int size) {
        return ApiResponse.ok(productService.page(keyword, category, color, season, style, maxPrice, page, size));
    }

    @GetMapping("/{id}")
    public ApiResponse<Product> detail(@PathVariable Long id) {
        return ApiResponse.ok(productService.detail(id));
    }
}
