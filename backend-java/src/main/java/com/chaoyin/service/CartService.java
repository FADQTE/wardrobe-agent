package com.chaoyin.service;

import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.chaoyin.common.BizException;
import com.chaoyin.entity.CartItem;
import com.chaoyin.entity.Product;
import com.chaoyin.mapper.CartItemMapper;
import com.chaoyin.mapper.ProductMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;
import java.util.function.Function;
import java.util.stream.Collectors;

/** 购物车：落库存储（用户/会话共享一致），AI 与商城页操作同一份数据。 */
@Service
@RequiredArgsConstructor
public class CartService {

    private final CartItemMapper cartItemMapper;
    private final ProductMapper productMapper;

    /** 扁平结构：id/productId/quantity 与商品信息平铺，前端与 MCP 直接用。 */
    public record CartLine(Long id, Long productId, Integer quantity, Product product) {
    }

    public List<CartLine> list(Long userId) {
        List<CartItem> items = cartItemMapper.selectList(new QueryWrapper<CartItem>()
                .eq("user_id", userId).orderByDesc("updated_at"));
        if (items.isEmpty()) {
            return List.of();
        }
        Map<Long, Product> products = productMapper.selectBatchIds(
                        items.stream().map(CartItem::getProductId).toList()).stream()
                .collect(Collectors.toMap(Product::getId, Function.identity()));
        return items.stream()
                .filter(it -> products.containsKey(it.getProductId()))
                .map(it -> new CartLine(it.getId(), it.getProductId(),
                        it.getQuantity(), products.get(it.getProductId())))
                .toList();
    }

    /** 加购：同商品已存在则数量累加；商品必须在售且库存足够。 */
    @Transactional
    public CartLine add(Long userId, Long productId, int quantity) {
        if (quantity < 1) throw new BizException(400, "加购数量至少为 1");
        Product product = productMapper.selectById(productId);
        if (product == null || product.getStatus() == null || product.getStatus() != 1) {
            throw new BizException(404, "商品不存在或已下架");
        }
        CartItem existing = cartItemMapper.selectOne(new QueryWrapper<CartItem>()
                .eq("user_id", userId).eq("product_id", productId).last("LIMIT 1"));
        int nextQuantity = (existing == null ? 0 : existing.getQuantity()) + quantity;
        if (product.getStock() != null && nextQuantity > product.getStock()) {
            throw new BizException(409, "超出库存：仅剩 " + product.getStock() + " 件");
        }
        CartItem item;
        if (existing == null) {
            item = new CartItem();
            item.setUserId(userId);
            item.setProductId(productId);
            item.setQuantity(quantity);
            item.setCreatedAt(LocalDateTime.now());
            item.setUpdatedAt(LocalDateTime.now());
            cartItemMapper.insert(item);
        } else {
            existing.setQuantity(nextQuantity);
            existing.setUpdatedAt(LocalDateTime.now());
            cartItemMapper.updateById(existing);
            item = existing;
        }
        return new CartLine(item.getId(), productId, item.getQuantity(), product);
    }

    @Transactional
    public CartItem updateQuantity(Long userId, Long id, int quantity) {
        CartItem item = requireOwned(userId, id);
        if (quantity < 1) {
            cartItemMapper.deleteById(id);
            return null;
        }
        item.setQuantity(quantity);
        item.setUpdatedAt(LocalDateTime.now());
        cartItemMapper.updateById(item);
        return item;
    }

    @Transactional
    public void remove(Long userId, Long id) {
        requireOwned(userId, id);
        cartItemMapper.deleteById(id);
    }

    private CartItem requireOwned(Long userId, Long id) {
        CartItem item = cartItemMapper.selectById(id);
        if (item == null || !item.getUserId().equals(userId)) {
            throw new BizException(404, "购物车条目不存在");
        }
        return item;
    }
}
