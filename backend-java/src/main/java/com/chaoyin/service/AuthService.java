package com.chaoyin.service;

import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.chaoyin.common.BizException;
import com.chaoyin.entity.User;
import com.chaoyin.entity.UserAuthToken;
import com.chaoyin.mapper.UserMapper;
import com.chaoyin.mapper.UserAuthTokenMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.stereotype.Service;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.LocalDateTime;
import java.util.Base64;
import java.util.HexFormat;
import java.util.UUID;

@Service
@RequiredArgsConstructor
public class AuthService {

    private final UserMapper userMapper;
    private final UserAuthTokenMapper tokenMapper;
    private final BCryptPasswordEncoder passwordEncoder = new BCryptPasswordEncoder();

    @Value("${app.auth.token-hours:168}")
    private long tokenHours = 168;

    public record LoginResult(String token, User user, LocalDateTime expiresAt) {
    }

    public LoginResult login(String username, String password) {
        String normalized = normalizeUsername(username);
        User user = userMapper.selectOne(
                new QueryWrapper<User>().eq("username", normalized));
        if (user == null || !passwordMatches(password, user.getPassword())) {
            throw new BizException(401, "用户名或密码错误");
        }
        // 兼容历史明文密码：首次成功登录后无感升级为 BCrypt。
        if (!isBcrypt(user.getPassword())) {
            user.setPassword(passwordEncoder.encode(password));
            userMapper.updateById(user);
        }
        return issueToken(user);
    }

    public LoginResult register(String username, String password, String nickname) {
        String normalized = normalizeUsername(username);
        if (!normalized.matches("[A-Za-z0-9_]{3,32}")) {
            throw new BizException(400, "用户名需为 3-32 位字母、数字或下划线");
        }
        if (password == null || password.length() < 6 || password.length() > 72) {
            throw new BizException(400, "密码长度需为 6-72 位");
        }
        if (userMapper.selectCount(new QueryWrapper<User>().eq("username", normalized)) > 0) {
            throw new BizException(409, "用户名已存在");
        }
        User user = new User();
        user.setUsername(normalized);
        user.setPassword(passwordEncoder.encode(password));
        user.setNickname(nickname == null || nickname.isBlank() ? normalized : nickname.trim());
        userMapper.insert(user);
        return issueToken(user);
    }

    public User authenticate(String rawToken) {
        if (rawToken == null || rawToken.isBlank()) {
            throw new BizException(401, "请先登录");
        }
        UserAuthToken token = tokenMapper.selectOne(new QueryWrapper<UserAuthToken>()
                .eq("token_hash", hashToken(rawToken)));
        if (token == null || token.getExpiresAt() == null || token.getExpiresAt().isBefore(LocalDateTime.now())) {
            if (token != null) {
                tokenMapper.deleteById(token.getId());
            }
            throw new BizException(401, "登录已过期，请重新登录");
        }
        User user = userMapper.selectById(token.getUserId());
        if (user == null) {
            tokenMapper.deleteById(token.getId());
            throw new BizException(401, "用户不存在");
        }
        return user;
    }

    public void logout(String rawToken) {
        if (rawToken != null && !rawToken.isBlank()) {
            tokenMapper.delete(new QueryWrapper<UserAuthToken>().eq("token_hash", hashToken(rawToken)));
        }
    }

    private LoginResult issueToken(User user) {
        String random = UUID.randomUUID() + ":" + UUID.randomUUID();
        String rawToken = "auth_" + Base64.getUrlEncoder().withoutPadding()
                .encodeToString(random.getBytes(StandardCharsets.UTF_8));
        LocalDateTime expiresAt = LocalDateTime.now().plusHours(Math.max(1, tokenHours));
        UserAuthToken token = new UserAuthToken();
        token.setUserId(user.getId());
        token.setTokenHash(hashToken(rawToken));
        token.setExpiresAt(expiresAt);
        tokenMapper.insert(token);
        return new LoginResult(rawToken, user, expiresAt);
    }

    private boolean passwordMatches(String raw, String encoded) {
        if (raw == null || encoded == null) {
            return false;
        }
        return isBcrypt(encoded) ? passwordEncoder.matches(raw, encoded) : encoded.equals(raw);
    }

    private static boolean isBcrypt(String value) {
        return value != null && (value.startsWith("$2a$") || value.startsWith("$2b$") || value.startsWith("$2y$"));
    }

    private static String normalizeUsername(String username) {
        return username == null ? "" : username.trim().toLowerCase();
    }

    private static String hashToken(String token) {
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256")
                    .digest(token.getBytes(StandardCharsets.UTF_8)));
        } catch (Exception e) {
            throw new IllegalStateException("无法计算令牌哈希", e);
        }
    }
}
