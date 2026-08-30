package com.chaoyin.service;

import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.chaoyin.common.BizException;
import com.chaoyin.entity.MallOrder;
import com.chaoyin.entity.OrderItem;
import com.chaoyin.entity.Product;
import com.chaoyin.entity.User;
import com.chaoyin.mapper.MallOrderMapper;
import com.chaoyin.mapper.OrderItemMapper;
import com.chaoyin.mapper.UserMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.ThreadLocalRandom;

@Slf4j
@Service
@RequiredArgsConstructor
public class OrderService {

    public static final String PENDING = "pending";
    public static final String PAID = "paid";
    public static final String SHIPPED = "shipped";
    public static final String DONE = "done";
    public static final String CANCELLED = "cancelled";

    private final MallOrderMapper orderMapper;
    private final OrderItemMapper orderItemMapper;
    private final ProductService productService;
    private final UserMapper userMapper;

    public record ItemReq(Long productId, Integer quantity) {
    }

    /** 创建订单：权限/库存/金额校验 + 事务扣减库存。 */
    @Transactional
    public MallOrder create(Long userId, List<ItemReq> items,
                            String receiverName, String receiverPhone, String receiverAddress) {
        User user = userMapper.selectById(userId);
        if (user == null) {
            throw new BizException(404, "用户不存在");
        }
        if (items == null || items.isEmpty()) {
            throw new BizException("订单商品不能为空");
        }
        BigDecimal total = BigDecimal.ZERO;
        List<OrderItem> orderItems = new ArrayList<>();
        for (ItemReq item : items) {
            int qty = item.quantity() == null || item.quantity() < 1 ? 1 : item.quantity();
            Product product = productService.detail(item.productId());
            productService.deductStock(item.productId(), qty);
            total = total.add(product.getPrice().multiply(BigDecimal.valueOf(qty)));
            OrderItem oi = new OrderItem();
            oi.setProductId(product.getId());
            oi.setProductName(product.getName());
            oi.setPrice(product.getPrice());
            oi.setQuantity(qty);
            orderItems.add(oi);
        }

        MallOrder order = new MallOrder();
        order.setOrderNo(genOrderNo());
        order.setUserId(userId);
        order.setTotalAmount(total);
        order.setStatus(PENDING);
        order.setReceiverName(receiverName);
        order.setReceiverPhone(receiverPhone);
        order.setReceiverAddress(receiverAddress);
        orderMapper.insert(order);
        orderItems.forEach(oi -> {
            oi.setOrderId(order.getId());
            orderItemMapper.insert(oi);
        });
        return order;
    }

    public void pay(Long orderId) {
        transit(orderId, PENDING, PAID, "仅待支付订单可支付");
    }

    public MallOrder ship(Long orderId) {
        MallOrder order = transit(orderId, PAID, SHIPPED, "仅已支付订单可发货");
        order.setLogisticsNo("SF" + System.currentTimeMillis() % 1000000000L);
        orderMapper.updateById(order);
        return orderMapper.selectById(orderId);
    }

    public static final String REFUNDED = "refunded";

    /** 售后审核通过的退款效果：订单置为已退款并恢复库存（幂等）。 */
    @Transactional
    public MallOrder markRefunded(Long orderId) {
        MallOrder order = orderMapper.selectById(orderId);
        if (order == null) throw new BizException(404, "订单不存在");
        if (REFUNDED.equals(order.getStatus())) return order;
        if (CANCELLED.equals(order.getStatus())) throw new BizException(409, "订单已取消，无需退款");
        order.setStatus(REFUNDED);
        orderMapper.updateById(order);
        items(orderId).forEach(item -> productService.restoreStock(item.getProductId(), item.getQuantity()));
        return order;
    }

    public MallOrder cancel(Long orderId) {
        MallOrder order = transit(orderId, PENDING, CANCELLED, "仅待支付订单可取消");
        items(orderId).forEach(item -> productService.restoreStock(item.getProductId(), item.getQuantity()));
        return order;
    }

    @Transactional
    public MallOrder cancelForUser(Long orderId, Long userId) {
        detailForUser(orderId, userId);
        return cancel(orderId);
    }

    public List<MallOrder> listByUser(Long userId) {
        return orderMapper.selectList(new QueryWrapper<MallOrder>()
                .eq("user_id", userId).orderByDesc("id"));
    }

    public MallOrder detail(Long orderId) {
        MallOrder order = orderMapper.selectById(orderId);
        if (order == null) {
            throw new BizException(404, "订单不存在");
        }
        return order;
    }

    public MallOrder detailForUser(Long orderId, Long userId) {
        MallOrder order = detail(orderId);
        if (userId == null || !userId.equals(order.getUserId())) {
            throw new BizException(403, "无权访问该订单");
        }
        return order;
    }

    public MallOrder findByNo(String orderNo) {
        MallOrder order = orderMapper.selectOne(new QueryWrapper<MallOrder>().eq("order_no", orderNo));
        if (order == null) {
            throw new BizException(404, "订单不存在: " + orderNo);
        }
        return order;
    }

    public MallOrder findByNoForUser(String orderNo, Long userId) {
        MallOrder order = findByNo(orderNo);
        if (userId == null || !userId.equals(order.getUserId())) {
            throw new BizException(403, "无权访问该订单");
        }
        return order;
    }

    public List<OrderItem> items(Long orderId) {
        return orderItemMapper.selectList(new QueryWrapper<OrderItem>().eq("order_id", orderId));
    }

    private MallOrder transit(Long orderId, String from, String to, String errMsg) {
        MallOrder order = detail(orderId);
        if (!from.equals(order.getStatus())) {
            throw new BizException(409, errMsg + "（当前状态: " + order.getStatus() + "）");
        }
        order.setStatus(to);
        orderMapper.updateById(order);
        return order;
    }

    private String genOrderNo() {
        return "CY" + LocalDateTime.now().format(DateTimeFormatter.ofPattern("yyyyMMddHHmmss"))
                + ThreadLocalRandom.current().nextInt(100, 999);
    }
}
