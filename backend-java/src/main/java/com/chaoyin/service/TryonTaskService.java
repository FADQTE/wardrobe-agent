package com.chaoyin.service;

import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.chaoyin.common.BizException;
import com.chaoyin.entity.TryonTask;
import com.chaoyin.mapper.TryonTaskMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;
import java.util.List;

/**
 * 换装任务（mock）：Agent 创建任务并上报进度/结果，这里统一持久化管理。
 */
@Service
@RequiredArgsConstructor
public class TryonTaskService {

    private final TryonTaskMapper taskMapper;

    public TryonTask create(TryonTask task) {
        task.setId(null);
        task.setStatus(task.getStatus() == null ? "pending" : task.getStatus());
        taskMapper.insert(task);
        return task;
    }

    public TryonTask updateStatus(Long id, String status, String resultUrl, String errorMsg) {
        TryonTask task = taskMapper.selectById(id);
        if (task == null) {
            throw new BizException(404, "换装任务不存在");
        }
        task.setStatus(status);
        if (resultUrl != null) {
            task.setResultUrl(resultUrl);
        }
        if (errorMsg != null) {
            task.setErrorMsg(errorMsg);
        }
        if ("done".equals(status) || "failed".equals(status)) {
            task.setFinishedAt(LocalDateTime.now());
        }
        taskMapper.updateById(task);
        return task;
    }

    public TryonTask get(Long id) {
        return taskMapper.selectById(id);
    }

    public List<TryonTask> listBySession(String sessionId) {
        return taskMapper.selectList(new QueryWrapper<TryonTask>()
                .eq("session_id", sessionId).orderByDesc("id"));
    }
}
