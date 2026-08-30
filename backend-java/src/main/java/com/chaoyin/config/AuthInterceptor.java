package com.chaoyin.config;

import com.chaoyin.common.ApiResponse;
import com.chaoyin.controller.AuthController;
import com.chaoyin.entity.User;
import com.chaoyin.service.AuthService;
import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import org.springframework.web.servlet.HandlerInterceptor;

import java.nio.charset.StandardCharsets;

@Component
@RequiredArgsConstructor
public class AuthInterceptor implements HandlerInterceptor {
    private final AuthService authService;
    private final ObjectMapper objectMapper;

    @Value("${app.internal-api-key:local-internal-key}")
    private String internalApiKey;

    @Override
    public boolean preHandle(HttpServletRequest request, HttpServletResponse response, Object handler) throws Exception {
        String suppliedInternalKey = request.getHeader("X-Internal-Api-Key");
        if (internalApiKey != null && !internalApiKey.isBlank() && internalApiKey.equals(suppliedInternalKey)) {
            return true;
        }
        try {
            User user = authService.authenticate(AuthController.bearerToken(request));
            request.setAttribute("currentUser", user);
            request.setAttribute("currentUserId", user.getId());
            return true;
        } catch (Exception e) {
            response.setStatus(HttpServletResponse.SC_UNAUTHORIZED);
            response.setCharacterEncoding(StandardCharsets.UTF_8.name());
            response.setContentType("application/json;charset=UTF-8");
            objectMapper.writeValue(response.getWriter(), ApiResponse.fail(401, e.getMessage()));
            return false;
        }
    }
}
