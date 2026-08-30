package com.chaoyin.service;

import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.chaoyin.common.BizException;
import com.chaoyin.entity.AfterSale;
import com.chaoyin.entity.MallOrder;
import com.chaoyin.mapper.AfterSaleMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.List;
import java.util.concurrent.ThreadLocalRandom;

@Service
@RequiredArgsConstructor
public class AfterSaleService {

    public static final String PENDING = "pending";
    public static final String APPROVED = "approved";
    public static final String REJECTED = "rejected";
    public static final String COMPLETED = "completed";

    private final AfterSaleMapper afterSaleMapper;
    private final OrderService orderService;

    public record Policy(String unpaidOrder, String paidUnshipped, String shippedOrCompleted,
                         String exclusions, String processing, String safetyBoundary) {
    }

    public Policy policy() {
        return new Policy(
                "待支付订单可直接取消，取消后恢复库存。",
                "已支付但未发货的订单可申请仅退款。",
                "已发货或已完成订单可申请退货退款；演示系统按 7 天无理由规则受理，商品需保持完好。",
                "定制商品、已拆封的贴身用品以及影响二次销售的商品不适用无理由退换。",
                "提交后进入人工审核，本演示不会自动操作真实资金。",
                "AI 只能查询政策和引导申请，不能承诺审核通过或退款到账。"
        );
    }

    @Transactional
    public AfterSale apply(Long userId, Long orderId, String type, String reason) {
        MallOrder order = orderService.detailForUser(orderId, userId);
        if (OrderService.PENDING.equals(order.getStatus())) {
            throw new BizException(409, "待支付订单无需退款，请直接取消订单");
        }
        if (OrderService.CANCELLED.equals(order.getStatus())) {
            throw new BizException(409, "已取消订单不能申请售后");
        }

        AfterSale existing = afterSaleMapper.selectOne(new QueryWrapper<AfterSale>()
                .eq("order_id", orderId)
                .in("status", PENDING, APPROVED, COMPLETED)
                .orderByDesc("id").last("LIMIT 1"));
        if (existing != null) {
            return existing;
        }

        String normalizedType = StringUtils.hasText(type) ? type : "refund";
        if (!List.of("refund", "return_refund", "exchange").contains(normalizedType)) {
            throw new BizException(400, "不支持的售后类型");
        }
        AfterSale afterSale = new AfterSale();
        afterSale.setRequestNo(genRequestNo());
        afterSale.setOrderId(orderId);
        afterSale.setUserId(userId);
        afterSale.setType(normalizedType);
        afterSale.setStatus(PENDING);
        afterSale.setReason(StringUtils.hasText(reason) ? reason.trim() : "用户从商城订单页申请");
        afterSale.setAmount(order.getTotalAmount());
        afterSaleMapper.insert(afterSale);
        return afterSaleMapper.selectById(afterSale.getId());
    }

    public List<AfterSale> listByUser(Long userId) {
        return afterSaleMapper.selectList(new QueryWrapper<AfterSale>()
                .eq("user_id", userId).orderByDesc("id"));
    }

    public AfterSale findByOrder(Long orderId, Long userId) {
        return afterSaleMapper.selectOne(new QueryWrapper<AfterSale>()
                .eq("order_id", orderId).eq("user_id", userId)
                .orderByDesc("id").last("LIMIT 1"));
    }

    private String genRequestNo() {
        return "AS" + LocalDateTime.now().format(DateTimeFormatter.ofPattern("yyyyMMddHHmmss"))
                + ThreadLocalRandom.current().nextInt(100, 999);
    }
}
