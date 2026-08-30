import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 16548,
    proxy: {
      // Java 业务服务（REST + MCP SSE 端点）
      '/api': { target: 'http://localhost:16545', changeOrigin: true },
      '/mcp': { target: 'http://localhost:16545', changeOrigin: true },
      // Python Agent 服务（SSE 聊天等），/agent 前缀转发到 16546 并去掉前缀
      '/agent': { target: 'http://localhost:16546', changeOrigin: true, rewrite: (p) => p.replace(/^\/agent/, '') },
      // Netty WS 推送网关（Java 16547）
      '/ws': { target: 'ws://localhost:16547', ws: true },
    },
  },
})
