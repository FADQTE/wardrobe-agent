package com.chaoyin.service;

import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.chaoyin.common.BizException;
import com.chaoyin.entity.AfterSale;
import com.chaoyin.entity.MallOrder;
import com.chaoyin.mapper.AfterSaleMapper;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.math.BigDecimal;
import java.util.concurrent.atomic.AtomicReference;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertSame;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class AfterSaleServiceTest {

    @Mock
    private AfterSaleMapper afterSaleMapper;
    @Mock
    private OrderService orderService;
    @InjectMocks
    private AfterSaleService service;

    @Test
    void pendingOrderMustBeCancelledInsteadOfRefunded() {
        MallOrder order = order(11L, 7L, OrderService.PENDING);
        when(orderService.detailForUser(11L, 7L)).thenReturn(order);

        BizException error = assertThrows(BizException.class,
                () -> service.apply(7L, 11L, "refund", "不想要了"));

        assertEquals(409, error.getCode());
        assertEquals("待支付订单无需退款，请直接取消订单", error.getMessage());
        verifyNoInteractions(afterSaleMapper);
    }

    @Test
    void paidOrderCreatesPendingManualReviewWithoutApprovingRefund() {
        MallOrder order = order(12L, 7L, OrderService.PAID);
        when(orderService.detailForUser(12L, 7L)).thenReturn(order);
        when(afterSaleMapper.selectOne(any(QueryWrapper.class))).thenReturn(null);
        AtomicReference<AfterSale> saved = new AtomicReference<>();
        doAnswer(invocation -> {
            AfterSale value = invocation.getArgument(0);
            value.setId(31L);
            saved.set(value);
            return 1;
        }).when(afterSaleMapper).insert(any(AfterSale.class));
        when(afterSaleMapper.selectById(anyLong())).thenAnswer(invocation -> saved.get());

        AfterSale result = service.apply(7L, 12L, "refund", "尺码不合适");

        assertEquals(AfterSaleService.PENDING, result.getStatus());
        assertEquals("refund", result.getType());
        assertEquals(new BigDecimal("299.00"), result.getAmount());
        assertEquals("尺码不合适", result.getReason());
    }

    @Test
    void repeatedApplicationReturnsExistingActiveRequest() {
        MallOrder order = order(13L, 7L, OrderService.SHIPPED);
        AfterSale existing = new AfterSale();
        existing.setId(32L);
        existing.setStatus(AfterSaleService.PENDING);
        when(orderService.detailForUser(13L, 7L)).thenReturn(order);
        when(afterSaleMapper.selectOne(any(QueryWrapper.class))).thenReturn(existing);

        AfterSale result = service.apply(7L, 13L, "return_refund", "重复点击");

        assertSame(existing, result);
        verify(afterSaleMapper, never()).insert(any(AfterSale.class));
    }

    private MallOrder order(Long id, Long userId, String status) {
        MallOrder order = new MallOrder();
        order.setId(id);
        order.setUserId(userId);
        order.setStatus(status);
        order.setTotalAmount(new BigDecimal("299.00"));
        return order;
    }
}
