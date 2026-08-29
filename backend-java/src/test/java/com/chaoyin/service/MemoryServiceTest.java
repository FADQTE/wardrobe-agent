package com.chaoyin.service;

import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.chaoyin.entity.AgentMemory;
import com.chaoyin.mapper.AgentMemoryMapper;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.time.LocalDateTime;
import java.util.List;
import java.util.concurrent.atomic.AtomicLong;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.atLeastOnce;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class MemoryServiceTest {

    @Mock
    private AgentMemoryMapper mapper;
    @InjectMocks
    private MemoryService service;

    @Test
    void samePredicateDifferentValueSupersedesOldMemoryAndKeepsChain() {
        AgentMemory old = memory(87L, "shoe_size", "42", "user_explicit", 1.0f);
        old.setUpdatedAt(LocalDateTime.now());
        when(mapper.selectList(any(QueryWrapper.class))).thenReturn(List.of(old));

        MemoryService.WriteResult result = service.write(
                memory(null, "shoe_size", "43", "user_explicit", 1.0f));

        assertEquals(MemoryService.WriteAction.SUPERSEDED, result.action());
        assertEquals(MemoryService.STATUS_SUPERSEDED, old.getStatus());
        assertEquals(87L, result.memory().getSupersedesMemoryId());
    }

    @Test
    void duplicateValueDedupesInsteadOfCreatingDuplicateMemory() {
        AgentMemory old = memory(87L, "preferred_color", "black", "user_explicit", 0.9f);
        when(mapper.selectList(any(QueryWrapper.class))).thenReturn(List.of(old));

        MemoryService.WriteResult result = service.write(
                memory(null, "preferred_color", "black", "user_explicit", 1.0f));

        assertEquals(MemoryService.WriteAction.DEDUPED, result.action());
        assertEquals(87L, result.memory().getId());
        assertEquals(MemoryService.STATUS_ACTIVE, old.getStatus());
        // 重复确认提升置信度，但不超过 1
        assertTrue(old.getConfidence() > 0.9f && old.getConfidence() <= 1.0f);
        verify(mapper, never()).insert(any(AgentMemory.class));
    }

    @Test
    void agentInferenceConfidenceIsCappedAndCannotPromoteItself() {
        AgentMemory inferred = memory(null, "preferred_color", "black", "agent_inference", 0.9f);

        service.write(inferred);

        assertTrue(inferred.getConfidence() <= 0.7f);
    }

    @Test
    void inferenceCannotDegradeUserExplicitFact() {
        AgentMemory explicit = memory(87L, "shoe_size", "43", "user_explicit", 1.0f);
        when(mapper.selectList(any(QueryWrapper.class))).thenReturn(List.of(explicit));

        MemoryService.WriteResult result = service.write(
                memory(null, "shoe_size", "43", "agent_inference", 0.6f));

        // 同值推断只是重复确认，去重处理且不得降低用户明确记忆的置信度
        assertEquals(MemoryService.WriteAction.DEDUPED, result.action());
        assertEquals(1.0f, explicit.getConfidence());
        verify(mapper, never()).insert(any(AgentMemory.class));
    }

    @Test
    void userExplicitHighConfidenceFactIsExemptFromDecay() {
        AtomicLong seq = new AtomicLong(100);
        when(mapper.insert(any(AgentMemory.class))).thenAnswer(invocation -> {
            invocation.getArgument(0, AgentMemory.class).setId(seq.incrementAndGet());
            return 1;
        });

        MemoryService.WriteResult explicit = service.write(
                memory(null, "shoe_size", "43", "user_explicit", 1.0f));
        MemoryService.WriteResult inferred = service.write(
                memory(null, "preferred_style", "minimal", "agent_inference", 0.6f));

        assertEquals(0, explicit.memory().getDecayEnabled());
        assertEquals(1, inferred.memory().getDecayEnabled());
    }

    @Test
    void episodeAppendsWithoutConflictResolution() {
        AgentMemory episode = memory(null, "tryon_image", "生成效果图", "user_behavior", 0.6f);
        episode.setMemoryType("episode");

        MemoryService.WriteResult result = service.write(episode);

        assertEquals(MemoryService.WriteAction.CREATED, result.action());
        verify(mapper).insert(episode);
        verify(mapper, never()).selectList(any(QueryWrapper.class));
    }

    @Test
    void invalidTypeAndBlankPredicateAreRejected() {
        AgentMemory badType = memory(null, "size", "43", "user_explicit", 1.0f);
        badType.setMemoryType("short_term");
        assertThrows(IllegalArgumentException.class, () -> service.write(badType));

        AgentMemory blankPredicate = memory(null, " ", "43", "user_explicit", 1.0f);
        assertThrows(IllegalArgumentException.class, () -> service.write(blankPredicate));
    }

    @Test
    void touchBumpsAccessEvidenceForDecayStrength() {
        AgentMemory memory = memory(87L, "shoe_size", "43", "user_explicit", 1.0f);
        memory.setAccessCount(3);
        when(mapper.selectById(87L)).thenReturn(memory);

        service.touch(87L);

        ArgumentCaptor<AgentMemory> captor = ArgumentCaptor.forClass(AgentMemory.class);
        verify(mapper, atLeastOnce()).updateById(captor.capture());
        assertEquals(4, captor.getValue().getAccessCount());
        assertTrue(captor.getValue().getLastAccessedAt() != null);
    }

    @Test
    void decayArchivesStaleWeakMemoriesButProtectsStrongOrRecentOnes() {
        AgentMemory staleWeak = memory(1L, "preferred_style", "minimal", "agent_inference", 0.5f);
        staleWeak.setImportance(0.4f);
        staleWeak.setLastAccessedAt(LocalDateTime.now().minusDays(60));

        AgentMemory strong = memory(2L, "preferred_color", "black", "agent_inference", 0.6f);
        strong.setImportance(0.9f);
        strong.setLastAccessedAt(LocalDateTime.now().minusDays(60));

        AgentMemory recent = memory(3L, "preferred_style", "sporty", "agent_inference", 0.5f);
        recent.setImportance(0.4f);
        recent.setLastAccessedAt(LocalDateTime.now().minusDays(1));

        when(mapper.selectList(any(QueryWrapper.class)))
                .thenReturn(List.of(staleWeak, strong, recent));

        int archived = service.decay(30);

        assertEquals(1, archived);
        assertEquals(MemoryService.STATUS_ARCHIVED, staleWeak.getStatus());
        assertEquals(MemoryService.STATUS_ACTIVE, strong.getStatus());
        assertEquals(MemoryService.STATUS_ACTIVE, recent.getStatus());
    }

    @Test
    void decayNeverTouchesExemptMemories() {
        AgentMemory explicit = memory(1L, "shoe_size", "43", "user_explicit", 1.0f);
        explicit.setDecayEnabled(0);
        explicit.setLastAccessedAt(LocalDateTime.now().minusDays(365));
        when(mapper.selectList(any(QueryWrapper.class))).thenReturn(List.of(explicit));

        assertEquals(0, service.decay(30));
        assertEquals(MemoryService.STATUS_ACTIVE, explicit.getStatus());
        verify(mapper, never()).updateById(any(AgentMemory.class));
    }

    private AgentMemory memory(Long id, String predicate, String value,
                               String sourceType, float confidence) {
        AgentMemory memory = new AgentMemory();
        memory.setId(id);
        memory.setUserId(7L);
        memory.setMemoryType("semantic");
        memory.setSubject("user");
        memory.setPredicate(predicate);
        memory.setValue("\"" + value + "\"");
        memory.setSourceType(sourceType);
        memory.setConfidence(confidence);
        memory.setStatus(MemoryService.STATUS_ACTIVE);
        return memory;
    }
}
