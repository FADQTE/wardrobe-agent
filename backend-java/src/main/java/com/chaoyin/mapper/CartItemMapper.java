package com.chaoyin.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.chaoyin.entity.CartItem;
import org.apache.ibatis.annotations.Mapper;

@Mapper
public interface CartItemMapper extends BaseMapper<CartItem> {
}
