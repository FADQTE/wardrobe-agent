package com.chaoyin.service;

import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.chaoyin.common.BizException;
import com.chaoyin.entity.ChatMessage;
import com.chaoyin.entity.ChatSession;
import com.chaoyin.mapper.ChatMessageMapper;
import com.chaoyin.mapper.ChatSessionMapper;
import com.chaoyin.mapper.TraceEventMapper;
import com.chaoyin.mapper.TryonTaskMapper;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

@ExtendWith(MockitoExtension.class)
class ChatSessionServiceTest {
    @Mock ChatSessionMapper sessionMapper;
    @Mock ChatMessageMapper messageMapper;
    @Mock TraceEventMapper traceEventMapper;
    @Mock TryonTaskMapper tryonTaskMapper;
    @InjectMocks ChatSessionService service;

    @Test
    void createAssignsAuthenticatedOwnerAndSafeDefaults() {
        ChatSession created = service.create(7L);

        assertTrue(created.getId().startsWith("s"));
        assertEquals(7L, created.getUserId());
        assertEquals("新对话", created.getTitle());
        assertEquals("{}", created.getState());
        verify(sessionMapper).insert(created);
    }

    @Test
    void anotherUserCannotReadOrDeleteSession() {
        when(sessionMapper.selectById("s1")).thenReturn(session("s1", 8L, "别人的对话"));

        BizException readError = assertThrows(BizException.class, () -> service.messages("s1", 7L, 200));
        BizException deleteError = assertThrows(BizException.class, () -> service.delete("s1", 7L));

        assertEquals(404, readError.getCode());
        assertEquals(404, deleteError.getCode());
        verify(messageMapper, never()).delete(any(QueryWrapper.class));
        verify(traceEventMapper, never()).delete(any(QueryWrapper.class));
        verify(tryonTaskMapper, never()).delete(any(QueryWrapper.class));
        verify(sessionMapper, never()).deleteById(any(java.io.Serializable.class));
    }

    @Test
    void deletingOwnedSessionAlsoDeletesItsMessages() {
        when(sessionMapper.selectById("s1")).thenReturn(session("s1", 7L, "通勤搭配"));

        service.delete("s1", 7L);

        verify(messageMapper).delete(any(QueryWrapper.class));
        verify(traceEventMapper).delete(any(QueryWrapper.class));
        verify(tryonTaskMapper).delete(any(QueryWrapper.class));
        verify(sessionMapper).deleteById("s1");
    }

    @Test
    void agentUpsertCannotMoveSessionToAnotherUser() {
        when(sessionMapper.selectById("s1")).thenReturn(session("s1", 7L, "原会话"));
        ChatSession incoming = session("s1", 8L, "伪造会话");

        BizException error = assertThrows(BizException.class, () -> service.internalUpsert(incoming));

        assertEquals(403, error.getCode());
        verify(sessionMapper, never()).updateById(any(ChatSession.class));
    }

    @Test
    void appendingMessageRequiresExistingSession() {
        ChatMessage message = new ChatMessage();
        message.setSessionId("missing");

        assertThrows(BizException.class, () -> service.internalAppend(message));
        verify(messageMapper, never()).insert(any(ChatMessage.class));
    }

    private static ChatSession session(String id, Long userId, String title) {
        ChatSession session = new ChatSession();
        session.setId(id);
        session.setUserId(userId);
        session.setTitle(title);
        session.setState("{}");
        return session;
    }
}
