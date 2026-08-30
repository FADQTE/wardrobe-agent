package com.chaoyin.mcp;

import com.chaoyin.entity.MallOrder;
import com.chaoyin.entity.Product;
import com.chaoyin.entity.WardrobeItem;
import com.chaoyin.mapper.FavoriteMapper;
import com.chaoyin.service.CartService;
import com.chaoyin.service.OrderService;
import com.chaoyin.service.ProductService;
import com.chaoyin.service.WardrobeService;
import com.chaoyin.service.AfterSaleService;
import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.chaoyin.entity.Favorite;
import lombok.RequiredArgsConstructor;
import org.springframework.ai.tool.annotation.Tool;
import org.springframework.ai.tool.annotation.ToolParam;
import org.springframework.stereotype.Component;

import java.math.BigDecimal;
import java.util.List;

/**
 * 商城/衣橱 MCP 工具：由 Agent（Python MCP Client）通过 SSE 调用。
 * 写操作（下单/扣库存）在 Java 侧完成权限、状态与事务校验。
 */
@Component
@RequiredArgsConstructor
public class MallTools {

    private final WardrobeService wardrobeService;
    private final ProductService productService;
    private final OrderService orderService;
    private final AfterSaleService afterSaleService;
    private final CartService cartService;
    private final FavoriteMapper favoriteMapper;

    public record ProductPage(List<Product> products, long total) {
    }

    public record StockInfo(long productId, String name, int stock) {
    }

    public record LogisticsInfo(String orderNo, String status, String logisticsNo, String hint) {
    }

    @Tool(description = "查询指定用户的个人衣橱单品列表（已有衣物），返回类目/颜色/季节/风格等标签")
    public List<WardrobeItem> listWardrobe(@ToolParam(description = "用户ID") long userId) {
        return wardrobeService.listByUser(userId);
    }

    @Tool(description = "按关键词与类目/颜色/季节/风格/最高价筛选商城在售商品，返回商品列表与总数")
    public ProductPage searchProducts(
            @ToolParam(description = "商品关键词，如 白衬衫") String keyword,
            @ToolParam(description = "类目: top/bottom/outerwear/dress/shoes/accessory，可为空") String category,
            @ToolParam(description = "颜色，可为空") String color,
            @ToolParam(description = "季节: 春/夏/秋/冬，可为空") String season,
            @ToolParam(description = "风格: 通勤/休闲/运动/约会/正式，可为空") String style,
            @ToolParam(description = "最高价格上限，可为空") BigDecimal maxPrice,
            @ToolParam(description = "页码，从1开始") int page) {
        var p = productService.page(keyword, category, color, season, style, maxPrice, page, 10);
        return new ProductPage(p.getRecords(), p.getTotal());
    }

    @Tool(description = "查询商品详情（含价格与库存）")
    public Product getProduct(@ToolParam(description = "商品ID") long productId) {
        return productService.detail(productId);
    }

    @Tool(description = "查询商品实时库存")
    public StockInfo checkStock(@ToolParam(description = "商品ID") long productId) {
        Product p = productService.detail(productId);
        return new StockInfo(p.getId(), p.getName(), p.getStock());
    }

    @Tool(description = "把商品加入用户收藏")
    public String addFavorite(@ToolParam(description = "用户ID") long userId,
                              @ToolParam(description = "商品ID") long productId) {
        Favorite exist = favoriteMapper.selectOne(new QueryWrapper<Favorite>()
                .eq("user_id", userId).eq("product_id", productId));
        if (exist == null) {
            Favorite f = new Favorite();
            f.setUserId(userId);
            f.setProductId(productId);
            favoriteMapper.insert(f);
        }
        return "已收藏商品 #" + productId;
    }

    @Tool(description = "创建订单（校验库存并事务扣减）。items 为商品ID与数量列表")
    public MallOrder createOrder(
            @ToolParam(description = "用户ID") long userId,
            @ToolParam(description = "商品列表") List<OrderService.ItemReq> items,
            @ToolParam(description = "收货人") String receiverName,
            @ToolParam(description = "收货电话") String receiverPhone,
            @ToolParam(description = "收货地址") String receiverAddress) {
        return orderService.create(userId, items, receiverName, receiverPhone, receiverAddress);
    }

    @Tool(description = "查询指定用户的订单列表，按最新订单优先返回")
    public List<MallOrder> listOrders(@ToolParam(description = "用户ID") long userId) {
        return orderService.listByUser(userId);
    }

    @Tool(description = "按订单号查询当前用户的订单状态")
    public MallOrder queryOrder(@ToolParam(description = "用户ID") long userId,
                                @ToolParam(description = "订单号") String orderNo) {
        return orderService.findByNoForUser(orderNo, userId);
    }

    @Tool(description = "按订单号查询物流信息")
    public LogisticsInfo queryLogistics(@ToolParam(description = "用户ID") long userId,
                                        @ToolParam(description = "订单号") String orderNo) {
        MallOrder order = orderService.findByNoForUser(orderNo, userId);
        String hint = switch (order.getStatus()) {
            case OrderService.PENDING -> "订单待支付，尚未发货";
            case OrderService.PAID -> "已支付，等待发货";
            case OrderService.SHIPPED -> "已发货，运输中";
            case OrderService.DONE -> "已签收";
            default -> "订单状态: " + order.getStatus();
        };
        return new LogisticsInfo(order.getOrderNo(), order.getStatus(), order.getLogisticsNo(), hint);
    }

    @Tool(description = "查询商城退货退款政策。只返回政策与处理边界，不代表退款申请已通过")
    public AfterSaleService.Policy getAfterSalePolicy() {
        return afterSaleService.policy();
    }

    @Tool(description = "查询指定用户的售后申请记录，按最新申请优先返回")
    public List<com.chaoyin.entity.AfterSale> listAfterSales(
            @ToolParam(description = "用户ID") long userId) {
        return afterSaleService.listByUser(userId);
    }

    @Tool(description = "为当前用户的指定订单创建售后申请（退货退款/仅退款）。只创建申请进入人工审核，"
            + "不会直接退款；type 按订单状态选 refund(未发货)或 return_refund(已发货/已完成)")
    public com.chaoyin.entity.AfterSale applyAfterSale(
            @ToolParam(description = "用户ID") long userId,
            @ToolParam(description = "订单号，如 CY202608150001") String orderNo,
            @ToolParam(description = "类型: refund 仅退款 | return_refund 退货退款 | exchange 换货") String type) {
        MallOrder order = orderService.findByNoForUser(orderNo, userId);
        return afterSaleService.apply(userId, order.getId(), type, "AI 客服代提交");
    }

    @Tool(description = "把商品加入用户购物车（同商品数量累加，校验在售与库存）")
    public String addToCart(@ToolParam(description = "用户ID") long userId,
                            @ToolParam(description = "商品ID") long productId,
                            @ToolParam(description = "数量，默认1") int quantity) {
        var line = cartService.add(userId, productId, quantity <= 0 ? 1 : quantity);
        return "已把「" + line.product().getName() + "」×" + line.quantity() + "加入购物车";
    }

    @Tool(description = "查询用户购物车列表（商品名/单价/数量/小计）")
    public List<CartLineInfo> listCart(@ToolParam(description = "用户ID") long userId) {
        return cartService.list(userId).stream()
                .map(line -> new CartLineInfo(line.productId(), line.product().getName(),
                        line.product().getPrice(), line.quantity()))
                .toList();
    }

    public record CartLineInfo(long productId, String name, java.math.BigDecimal price, int quantity) {
    }
}
