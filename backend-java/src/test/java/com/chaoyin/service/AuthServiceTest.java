package com.chaoyin.service;

import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.chaoyin.common.BizException;
import com.chaoyin.entity.User;
import com.chaoyin.entity.UserAuthToken;
import com.chaoyin.mapper.UserAuthTokenMapper;
import com.chaoyin.mapper.UserMapper;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.time.LocalDateTime;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

@ExtendWith(MockitoExtension.class)
class AuthServiceTest {
    @Mock UserMapper userMapper;
    @Mock UserAuthTokenMapper tokenMapper;
    @InjectMocks AuthService authService;

    @Test
    void legacyPlaintextPasswordIsUpgradedAndTokenIssued() {
        User user = user(1L, "user", "user123");
        when(userMapper.selectOne(any(QueryWrapper.class))).thenReturn(user);

        AuthService.LoginResult result = authService.login(" User ", "user123");

        assertEquals(1L, result.user().getId());
        assertTrue(result.token().startsWith("auth_"));
        assertTrue(user.getPassword().startsWith("$2"));
        verify(userMapper).updateById(user);
        verify(tokenMapper).insert(any(UserAuthToken.class));
    }

    @Test
    void wrongPasswordDoesNotIssueToken() {
        when(userMapper.selectOne(any(QueryWrapper.class))).thenReturn(user(1L, "user", "user123"));

        BizException error = assertThrows(BizException.class, () -> authService.login("user", "wrong"));

        assertEquals(401, error.getCode());
        verify(tokenMapper, never()).insert(any(UserAuthToken.class));
    }

    @Test
    void expiredTokenIsRejectedAndRemoved() {
        UserAuthToken expired = new UserAuthToken();
        expired.setId(9L);
        expired.setExpiresAt(LocalDateTime.now().minusMinutes(1));
        when(tokenMapper.selectOne(any(QueryWrapper.class))).thenReturn(expired);

        BizException error = assertThrows(BizException.class, () -> authService.authenticate("expired"));

        assertEquals(401, error.getCode());
        verify(tokenMapper).deleteById(9L);
    }

    @Test
    void duplicateUsernameCannotRegister() {
        when(userMapper.selectCount(any(QueryWrapper.class))).thenReturn(1L);

        BizException error = assertThrows(BizException.class,
                () -> authService.register("user", "user123", "用户"));

        assertEquals(409, error.getCode());
        verify(userMapper, never()).insert(any(User.class));
    }

    private static User user(Long id, String username, String password) {
        User user = new User();
        user.setId(id);
        user.setUsername(username);
        user.setPassword(password);
        user.setNickname("小潮");
        return user;
    }
}
