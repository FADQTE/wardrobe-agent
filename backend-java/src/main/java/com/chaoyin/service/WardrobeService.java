package com.chaoyin.service;

import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.chaoyin.common.BizException;
import com.chaoyin.entity.WardrobeItem;
import com.chaoyin.mapper.WardrobeItemMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

import java.util.List;

@Service
@RequiredArgsConstructor
public class WardrobeService {

    private final WardrobeItemMapper itemMapper;

    public List<WardrobeItem> listByUser(Long userId) {
        return itemMapper.selectList(new QueryWrapper<WardrobeItem>()
                .eq("user_id", userId).orderByDesc("id"));
    }

    public WardrobeItem add(WardrobeItem item) {
        if (item.getSource() == null) {
            item.setSource("upload");
        }
        item.setId(null);
        itemMapper.insert(item);
        return item;
    }

    public WardrobeItem update(Long id, WardrobeItem patch) {
        WardrobeItem exist = getOwned(id, patch.getUserId());
        patch.setId(id);
        patch.setUserId(exist.getUserId());
        itemMapper.updateById(patch);
        return itemMapper.selectById(id);
    }

    public void delete(Long id) {
        if (itemMapper.deleteById(id) == 0) {
            throw new BizException("衣橱单品不存在");
        }
    }

    public WardrobeItem getOwned(Long id, Long userId) {
        WardrobeItem item = itemMapper.selectById(id);
        if (item == null || !item.getUserId().equals(userId)) {
            throw new BizException(404, "衣橱单品不存在");
        }
        return item;
    }
}
