package com.chaoyin.service;

import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.chaoyin.common.BizException;
import com.chaoyin.entity.ChatMessage;
import com.chaoyin.entity.ChatSession;
import com.chaoyin.mapper.ChatMessageMapper;
import com.chaoyin.mapper.ChatSessionMapper;
import com.chaoyin.mapper.TraceEventMapper;
import com.chaoyin.mapper.TryonTaskMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.util.Collections;
import java.util.List;
import java.util.UUID;

@Service
@RequiredArgsConstructor
public class ChatSessionService {
    private final ChatSessionMapper sessionMapper;
    private final ChatMessageMapper messageMapper;
    private final TraceEventMapper traceEventMapper;
    private final TryonTaskMapper tryonTaskMapper;

    public List<ChatSession> list(Long userId) {
        return sessionMapper.selectList(new QueryWrapper<ChatSession>()
                .eq("user_id", userId).orderByDesc("updated_at").orderByDesc("created_at"));
    }

    public ChatSession create(Long userId) {
        LocalDateTime now = LocalDateTime.now();
        ChatSession session = new ChatSession();
        session.setId("s" + UUID.randomUUID().toString().replace("-", "").substring(0, 24));
        session.setUserId(userId);
        session.setTitle("新对话");
        session.setState("{}");
        session.setCreatedAt(now);
        session.setUpdatedAt(now);
        sessionMapper.insert(session);
        return session;
    }

    public ChatSession rename(String id, Long userId, String title) {
        ChatSession session = requireOwned(id, userId);
        String normalized = title == null ? "" : title.trim();
        if (normalized.isBlank()) throw new BizException(400, "会话名称不能为空");
        session.setTitle(normalized.substring(0, Math.min(normalized.length(), 60)));
        session.setUpdatedAt(LocalDateTime.now());
        sessionMapper.updateById(session);
        return session;
    }

    @Transactional
    public void delete(String id, Long userId) {
        requireOwned(id, userId);
        messageMapper.delete(new QueryWrapper<ChatMessage>().eq("session_id", id));
        traceEventMapper.delete(new QueryWrapper<com.chaoyin.entity.TraceEvent>().eq("session_id", id));
        tryonTaskMapper.delete(new QueryWrapper<com.chaoyin.entity.TryonTask>().eq("session_id", id));
        sessionMapper.deleteById(id);
    }

    public List<ChatMessage> messages(String id, Long userId, int limit) {
        requireOwned(id, userId);
        return internalMessages(id, limit);
    }

    public ChatSession requireOwned(String id, Long userId) {
        ChatSession session = sessionMapper.selectById(id);
        if (session == null || userId == null || !userId.equals(session.getUserId())) {
            throw new BizException(404, "会话不存在");
        }
        return session;
    }

    public boolean belongsTo(String id, Long userId) {
        ChatSession session = sessionMapper.selectById(id);
        return session != null && userId != null && userId.equals(session.getUserId());
    }

    public ChatSession internalUpsert(ChatSession incoming) {
        if (incoming.getId() == null || incoming.getId().isBlank() || incoming.getUserId() == null) {
            throw new BizException(400, "会话 id 和 userId 不能为空");
        }
        LocalDateTime now = LocalDateTime.now();
        ChatSession existing = sessionMapper.selectById(incoming.getId());
        if (existing == null) {
            incoming.setTitle(incoming.getTitle() == null || incoming.getTitle().isBlank()
                    ? "新对话" : incoming.getTitle().trim());
            incoming.setState(incoming.getState() == null ? "{}" : incoming.getState());
            incoming.setCreatedAt(now);
            incoming.setUpdatedAt(now);
            sessionMapper.insert(incoming);
            return incoming;
        }
        if (!existing.getUserId().equals(incoming.getUserId())) {
            throw new BizException(403, "会话归属不匹配");
        }
        if (incoming.getTitle() != null && !incoming.getTitle().isBlank()
                && "新对话".equals(existing.getTitle())) {
            String nextTitle = incoming.getTitle().trim();
            existing.setTitle(nextTitle.substring(0, Math.min(nextTitle.length(), 60)));
        }
        if (incoming.getState() != null) existing.setState(incoming.getState());
        existing.setUpdatedAt(now);
        sessionMapper.updateById(existing);
        return existing;
    }

    public ChatSession internalGet(String id) {
        return sessionMapper.selectById(id);
    }

    public List<ChatMessage> internalMessages(String id, int limit) {
        List<ChatMessage> rows = messageMapper.selectList(new QueryWrapper<ChatMessage>()
                .eq("session_id", id).orderByDesc("id")
                .last("LIMIT " + Math.max(1, Math.min(limit, 500))));
        Collections.reverse(rows);
        return rows;
    }

    public void internalAppend(ChatMessage message) {
        ChatSession session = sessionMapper.selectById(message.getSessionId());
        if (session == null) throw new BizException(404, "写入消息前必须先创建会话");
        message.setId(null);
        message.setCreatedAt(LocalDateTime.now());
        messageMapper.insert(message);
        session.setUpdatedAt(LocalDateTime.now());
        sessionMapper.updateById(session);
    }
}
