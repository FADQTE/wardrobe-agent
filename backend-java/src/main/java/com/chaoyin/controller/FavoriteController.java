package com.chaoyin.controller;

import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.chaoyin.common.ApiResponse;
import com.chaoyin.entity.Favorite;
import com.chaoyin.entity.Product;
import com.chaoyin.mapper.FavoriteMapper;
import com.chaoyin.service.ProductService;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;

import java.util.List;

@RestController
@RequestMapping("/api/favorites")
@RequiredArgsConstructor
public class FavoriteController {

    private final FavoriteMapper favoriteMapper;
    private final ProductService productService;

    public record FavoriteRequest(Long userId, Long productId) {
    }

    @PostMapping
    public ApiResponse<Favorite> add(@RequestBody FavoriteRequest req) {
        Favorite exist = favoriteMapper.selectOne(new QueryWrapper<Favorite>()
                .eq("user_id", req.userId()).eq("product_id", req.productId()));
        if (exist != null) {
            return ApiResponse.ok(exist);
        }
        productService.detail(req.productId()); // 校验商品存在
        Favorite f = new Favorite();
        f.setUserId(req.userId());
        f.setProductId(req.productId());
        favoriteMapper.insert(f);
        return ApiResponse.ok(f);
    }

    @GetMapping
    public ApiResponse<List<Product>> list(@RequestParam Long userId) {
        List<Favorite> favs = favoriteMapper.selectList(new QueryWrapper<Favorite>()
                .eq("user_id", userId).orderByDesc("id"));
        List<Product> products = favs.stream()
                .map(f -> productService.detail(f.getProductId()))
                .toList();
        return ApiResponse.ok(products);
    }

    @DeleteMapping("/{productId}")
    public ApiResponse<Void> remove(@PathVariable Long productId, @RequestParam Long userId) {
        favoriteMapper.delete(new QueryWrapper<Favorite>()
                .eq("user_id", userId).eq("product_id", productId));
        return ApiResponse.ok(null);
    }
}
