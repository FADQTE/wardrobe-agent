package com.chaoyin.service;

import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.chaoyin.common.BizException;
import com.chaoyin.entity.Product;
import com.chaoyin.mapper.ProductMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

import java.math.BigDecimal;

@Service
@RequiredArgsConstructor
public class ProductService {

    private final ProductMapper productMapper;

    /** MySQL 检索（商城管理/兜底用）；商城页与 Agent 的混合检索走 ES。 */
    public Page<Product> page(String keyword, String category, String color,
                              String season, String style, BigDecimal maxPrice,
                              int page, int size) {
        QueryWrapper<Product> qw = new QueryWrapper<Product>().eq("status", 1);
        if (StringUtils.hasText(keyword)) {
            qw.and(w -> w.like("name", keyword).or().like("detail", keyword));
        }
        qw.eq(StringUtils.hasText(category), "category", category)
          .eq(StringUtils.hasText(color), "color", color)
          .eq(StringUtils.hasText(season), "season", season)
          .eq(StringUtils.hasText(style), "style", style)
          .le(maxPrice != null, "price", maxPrice)
          .orderByDesc("sales").orderByDesc("id");
        return productMapper.selectPage(new Page<>(page, size), qw);
    }

    public Product detail(Long id) {
        Product p = productMapper.selectById(id);
        if (p == null) {
            throw new BizException(404, "商品不存在");
        }
        return p;
    }

    /** 扣减库存（乐观校验），库存不足抛异常。 */
    public void deductStock(Long productId, int quantity) {
        Product p = detail(productId);
        if (p.getStock() < quantity) {
            throw new BizException(409, "库存不足: " + p.getName() + " 仅剩 " + p.getStock() + " 件");
        }
        int rows = productMapper.update(null,
                new com.baomidou.mybatisplus.core.conditions.update.UpdateWrapper<Product>()
                        .setSql("stock = stock - " + quantity)
                        .eq("id", productId).ge("stock", quantity));
        if (rows == 0) {
            throw new BizException(409, "库存扣减失败: " + p.getName());
        }
    }

    /** 取消未支付订单时回补库存。 */
    public void restoreStock(Long productId, int quantity) {
        productMapper.update(null,
                new com.baomidou.mybatisplus.core.conditions.update.UpdateWrapper<Product>()
                        .setSql("stock = stock + " + Math.max(quantity, 1))
                        .eq("id", productId));
    }
}
