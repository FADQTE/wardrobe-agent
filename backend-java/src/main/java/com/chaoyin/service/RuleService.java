package com.chaoyin.service;

import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.chaoyin.common.BizException;
import com.chaoyin.entity.RuleEntity;
import com.chaoyin.mapper.RuleMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestTemplate;

import java.util.List;
import java.util.Map;

/**
 * 规则管理：版本 + 时间窗 + 发布状态。
 * 发布/下线后通知 Agent 增量更新 ES 索引并失效关联缓存（索引与缓存归 Agent 管）。
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class RuleService {

    private final RuleMapper ruleMapper;
    private final RestTemplate restTemplate;

    @Value("${chaoyin.agent-url:http://localhost:8000}")
    private String agentUrl;

    public List<RuleEntity> list(String type, String status) {
        QueryWrapper<RuleEntity> qw = new QueryWrapper<RuleEntity>()
                .eq(type != null && !type.isBlank(), "type", type)
                .eq(status != null && !status.isBlank(), "publish_status", status)
                .orderByDesc("updated_at");
        return ruleMapper.selectList(qw);
    }

    public RuleEntity create(RuleEntity rule) {
        if (rule.getVersion() == null) {
            rule.setVersion(1);
        }
        if (rule.getPublishStatus() == null) {
            rule.setPublishStatus("draft");
        }
        rule.setId(null);
        ruleMapper.insert(rule);
        return rule;
    }

    public RuleEntity update(Long id, RuleEntity patch) {
        RuleEntity exist = get(id);
        patch.setId(id);
        patch.setType(exist.getType());
        ruleMapper.updateById(patch);
        return get(id);
    }

    /** 发布：状态置为 published 并通知 Agent 重建索引（失效同族旧版本）。 */
    public RuleEntity publish(Long id) {
        RuleEntity rule = get(id);
        rule.setPublishStatus("published");
        ruleMapper.updateById(rule);
        notifyAgent(id);
        return rule;
    }

    public RuleEntity offline(Long id) {
        RuleEntity rule = get(id);
        rule.setPublishStatus("offline");
        ruleMapper.updateById(rule);
        notifyAgent(id);
        return rule;
    }

    public RuleEntity get(Long id) {
        RuleEntity rule = ruleMapper.selectById(id);
        if (rule == null) {
            throw new BizException(404, "规则不存在");
        }
        return rule;
    }

    private void notifyAgent(Long ruleId) {
        try {
            restTemplate.postForEntity(agentUrl + "/internal/rules/reindex",
                    Map.of("rule_id", ruleId), String.class);
        } catch (Exception e) {
            // Agent 未启动时降级：索引将在 Agent 端做全量兜底同步
            log.warn("notify agent reindex failed: {}", e.getMessage());
        }
    }
}
