package com.chaoyin.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 个人衣橱单品：与商品(Product)同构的标签体系，支撑"已有单品+在售商品"混合搭配。
 */
@Data
@TableName("wardrobe_item")
public class WardrobeItem {
    @TableId(type = IdType.AUTO)
    private Long id;
    private Long userId;
    private String name;
    private String imageUrl;
    private String category;
    private String color;
    private String season;
    private String style;
    /** JSON 数组字符串 */
    private String tags;
    private String note;
    private String source;
    private LocalDateTime createdAt;
}
