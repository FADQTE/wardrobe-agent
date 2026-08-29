package com.chaoyin.service;

import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.chaoyin.entity.AgentMemory;
import com.chaoyin.mapper.AgentMemoryMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;
import java.util.List;

/**
 * 长期记忆写入治理：
 * - 同谓词同值 → 去重（提升置信度与访问计数，不新增行）；
 * - 同谓词不同值 → 旧值置 superseded，新值带冲突链，保证"之前是什么"仍可回答；
 * - episode 追加不冲突；agent_inference 不覆盖 user_explicit（防错误记忆闭环）。
 */
@Service
@RequiredArgsConstructor
public class MemoryService {

    public static final String TYPE_EPISODE = "episode";
    public static final String TYPE_SEMANTIC = "semantic";
    public static final String TYPE_PROFILE = "profile";
    public static final String STATUS_ACTIVE = "active";
    public static final String STATUS_SUPERSEDED = "superseded";
    public static final String STATUS_ARCHIVED = "archived";
    public static final String STATUS_INVALID = "invalid";
    public static final String SOURCE_EXPLICIT = "user_explicit";
    public static final String SOURCE_INFERENCE = "agent_inference";

    private final AgentMemoryMapper mapper;

    public enum WriteAction { CREATED, DEDUPED, SUPERSEDED }

    public record WriteResult(AgentMemory memory, WriteAction action) {}

    public WriteResult write(AgentMemory incoming) {
        normalize(incoming);
        if (TYPE_EPISODE.equals(incoming.getMemoryType())) {
            mapper.insert(incoming);
            return new WriteResult(incoming, WriteAction.CREATED);
        }
        List<AgentMemory> actives = activeByPredicate(incoming.getUserId(), incoming.getSubject(), incoming.getPredicate());
        for (AgentMemory old : actives) {
            if (sameValue(old, incoming)) {
                // 去重：重复表达同一事实 → 只强化证据，不产生重复记忆
                old.setConfidence(mergeConfidence(old, incoming));
                old.setImportance(maxOf(old.getImportance(), incoming.getImportance(), 0.5f));
                old.setAccessCount((old.getAccessCount() == null ? 0 : old.getAccessCount()) + 1);
                old.setSourceId(firstNonBlank(incoming.getSourceId(), old.getSourceId()));
                mapper.updateById(old);
                return new WriteResult(old, WriteAction.DEDUPED);
            }
        }
        // 语义/画像事实：一次只能有一个 active 值，其余降级为 superseded
        AgentMemory latest = null;
        for (AgentMemory old : actives) {
            old.setStatus(STATUS_SUPERSEDED);
            mapper.updateById(old);
            if (latest == null || (old.getUpdatedAt() != null && old.getUpdatedAt().isAfter(latest.getUpdatedAt()))) {
                latest = old;
            }
        }
        if (latest != null) {
            incoming.setSupersedesMemoryId(latest.getId());
        }
        mapper.insert(incoming);
        return new WriteResult(incoming, WriteAction.SUPERSEDED);
    }

    /** 结构化精确查询：predicate 命中直接取值，不走向量检索（能精确查就不模糊搜）。 */
    public List<AgentMemory> facts(Long userId, List<String> predicates) {
        QueryWrapper<AgentMemory> qw = new QueryWrapper<AgentMemory>()
                .eq("user_id", userId)
                .eq("status", STATUS_ACTIVE)
                .in("memory_type", TYPE_SEMANTIC, TYPE_PROFILE);
        if (predicates != null && !predicates.isEmpty()) {
            qw.in("predicate", predicates);
        }
        qw.orderByDesc("importance").orderByDesc("updated_at").last("LIMIT 20");
        return mapper.selectList(qw);
    }

    public List<AgentMemory> list(Long userId, String memoryType, String status, int limit) {
        QueryWrapper<AgentMemory> qw = new QueryWrapper<AgentMemory>();
        if (userId != null) {
            qw.eq("user_id", userId);
        }
        if (memoryType != null && !memoryType.isBlank()) {
            qw.eq("memory_type", memoryType);
        }
        qw.eq("status", status == null || status.isBlank() ? STATUS_ACTIVE : status);
        qw.orderByDesc("id").last("LIMIT " + Math.max(1, Math.min(limit, 200)));
        return mapper.selectList(qw);
    }

    /** 记忆被召回使用后回写访问证据，供遗忘衰减计算 Memory Strength。 */
    public void touch(Long id) {
        AgentMemory memory = mapper.selectById(id);
        if (memory == null) {
            return;
        }
        memory.setAccessCount((memory.getAccessCount() == null ? 0 : memory.getAccessCount()) + 1);
        memory.setLastAccessedAt(LocalDateTime.now());
        mapper.updateById(memory);
    }

    /** 用户/运营纠错：标记 invalid，防止错误记忆继续被召回强化。 */
    public void invalidate(Long id) {
        AgentMemory memory = mapper.selectById(id);
        if (memory != null) {
            memory.setStatus(STATUS_INVALID);
            mapper.updateById(memory);
        }
    }

    private void normalize(AgentMemory memory) {
        String type = memory.getMemoryType();
        if (!TYPE_EPISODE.equals(type) && !TYPE_SEMANTIC.equals(type) && !TYPE_PROFILE.equals(type)) {
            throw new IllegalArgumentException("memory_type 必须是 episode|semantic|profile");
        }
        if (memory.getPredicate() == null || memory.getPredicate().isBlank()) {
            throw new IllegalArgumentException("predicate 不能为空");
        }
        if (memory.getSubject() == null || memory.getSubject().isBlank()) {
            memory.setSubject("user");
        }
        memory.setStatus(STATUS_ACTIVE);
        memory.setSourceType(memory.getSourceType() == null || memory.getSourceType().isBlank()
                ? SOURCE_EXPLICIT : memory.getSourceType());
        if (memory.getConfidence() == null) {
            memory.setConfidence(1.0f);
        }
        // 防错误记忆闭环：Agent 推断的置信度封顶 0.7，且不允许覆盖用户明确记忆
        if (SOURCE_INFERENCE.equals(memory.getSourceType())) {
            memory.setConfidence(Math.min(memory.getConfidence(), 0.7f));
        }
        if (memory.getImportance() == null) {
            memory.setImportance(0.5f);
        }
        if (memory.getAccessCount() == null) {
            memory.setAccessCount(0);
        }
        // 用户明确表达的稳定事实/偏好禁止自动衰减（关键售后历史同理，由调用方置 0）
        memory.setDecayEnabled(SOURCE_EXPLICIT.equals(memory.getSourceType())
                && !TYPE_EPISODE.equals(memory.getMemoryType())
                && memory.getConfidence() >= 0.95f ? 0 : 1);
    }

    private List<AgentMemory> activeByPredicate(Long userId, String subject, String predicate) {
        return mapper.selectList(new QueryWrapper<AgentMemory>()
                .eq("user_id", userId)
                .eq("subject", subject)
                .eq("predicate", predicate)
                .eq("status", STATUS_ACTIVE));
    }

    private boolean sameValue(AgentMemory a, AgentMemory b) {
        String va = a.getValue() == null ? "" : a.getValue().trim();
        String vb = b.getValue() == null ? "" : b.getValue().trim();
        return va.equals(vb);
    }

    private float mergeConfidence(AgentMemory existing, AgentMemory incoming) {
        // 重复确认提升置信度但不超过 1；推断来源不能抬高用户明确记忆的置信度
        if (SOURCE_INFERENCE.equals(incoming.getSourceType())
                && !SOURCE_INFERENCE.equals(existing.getSourceType())) {
            return existing.getConfidence();
        }
        return Math.min(1.0f, Math.max(existing.getConfidence(),
                existing.getConfidence() + 0.05f * (1 - existing.getConfidence())));
    }

    private Float maxOf(Float a, Float b, float fallback) {
        return Float.compare(a == null ? fallback : a, b == null ? fallback : b) >= 0
                ? (a == null ? fallback : a) : (b == null ? fallback : b);
    }

    private String firstNonBlank(String a, String b) {
        return a != null && !a.isBlank() ? a : b;
    }
}
