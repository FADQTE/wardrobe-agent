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

import java.math.BigDecimal;
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
                "已发货或已完成订单可申请退货退款；按 7 天无理由规则受理，商品需保持完好。",
                "定制商品、已拆封的贴身用品以及影响二次销售的商品不适用无理由退换。",
                "提交后进入人工审核，当前环境不会自动操作真实资金。",
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
        // 自动审核引擎：符合规则的自动通过（模型可退），不符合的转人工处理
        autoReview(afterSale, order);
        afterSaleMapper.updateById(afterSale);
        return afterSaleMapper.selectById(afterSale.getId());
    }

    /** 自动退款上限：小额订单才允许规则自动通过，大额一律人工。 */
    public static final BigDecimal AUTO_REFUND_LIMIT = new BigDecimal("1000");

    /**
     * 自动审核规则（可解释、可追问）：
     * 通过 = 退款类型与订单状态匹配（paid→仅退款 / shipped·done→退货退款）且金额 ≤ 上限；
     * 其余（类型不匹配、超额）保持 pending 转人工，并记录原因供人工客服页面展示。
     */
    private void autoReview(AfterSale sale, MallOrder order) {
        String expectedType = switch (order.getStatus()) {
            case OrderService.PAID -> "refund";
            case OrderService.SHIPPED, OrderService.DONE -> "return_refund";
            default -> "";
        };
        boolean typeMatches = expectedType.equals(sale.getType());
        boolean withinLimit = sale.getAmount() != null
                && sale.getAmount().compareTo(AUTO_REFUND_LIMIT) <= 0;
        if (typeMatches && withinLimit) {
            sale.setStatus(APPROVED);
            sale.setReviewSource("auto");
            sale.setReviewReason("符合自动退款规则：类型与订单状态匹配，金额 ¥"
                    + sale.getAmount() + " ≤ 上限 ¥" + AUTO_REFUND_LIMIT + "，系统自动通过");
        } else {
            sale.setReviewSource("manual");
            String why = typeMatches
                    ? "金额 ¥" + sale.getAmount() + " 超过自动退款上限 ¥" + AUTO_REFUND_LIMIT
                    : "退款类型与订单状态不匹配（" + order.getStatus() + " 订单应选择 "
                      + (expectedType.isEmpty() ? "人工核实的类型" : expectedType) + "）";
            sale.setReviewReason(why + "，转人工审核");
        }
    }

    /** 人工客服：待审核列表（最新优先）。 */
    public List<AfterSale> listByStatus(String status) {
        QueryWrapper<AfterSale> query = new QueryWrapper<AfterSale>().orderByDesc("id");
        if (StringUtils.hasText(status)) {
            query.eq("status", status);
        }
        return afterSaleMapper.selectList(query);
    }

    /** 人工客服：通过（仅 pending 可操作），记录人工结论。 */
    public AfterSale approve(Long id, String reason) {
        AfterSale sale = requirePending(id);
        sale.setStatus(APPROVED);
        sale.setReviewSource("manual");
        sale.setReviewReason("人工审核通过" + (StringUtils.hasText(reason) ? "：" + reason.trim() : ""));
        afterSaleMapper.updateById(sale);
        return sale;
    }

    /** 人工客服：驳回（仅 pending 可操作）。 */
    public AfterSale reject(Long id, String reason) {
        AfterSale sale = requirePending(id);
        sale.setStatus(REJECTED);
        sale.setReviewSource("manual");
        sale.setReviewReason("人工审核驳回" + (StringUtils.hasText(reason) ? "：" + reason.trim() : ""));
        afterSaleMapper.updateById(sale);
        return sale;
    }

    private AfterSale requirePending(Long id) {
        AfterSale sale = afterSaleMapper.selectById(id);
        if (sale == null) throw new BizException(404, "售后单不存在");
        if (!PENDING.equals(sale.getStatus())) {
            throw new BizException(409, "该售后单已处理（" + sale.getStatus() + "），不能重复操作");
        }
        return sale;
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
