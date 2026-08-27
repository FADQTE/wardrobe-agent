package com.chaoyin.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.math.BigDecimal;
import java.time.LocalDateTime;

@Data
@TableName("product")
public class Product {
    @TableId(type = IdType.AUTO)
    private Long id;
    private String name;
    private String imageUrl;
    private String category;
    private String color;
    private String season;
    private String style;
    /** JSON 数组字符串 */
    private String tags;
    private BigDecimal price;
    private Integer stock;
    /** 1 上架 0 下架 */
    private Integer status;
    private Integer sales;
    private String detail;
    private LocalDateTime createdAt;
}
