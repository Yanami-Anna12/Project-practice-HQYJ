import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// dev      默认，通过 Vite 代理把 /api 转发到后端（推荐，无跨域问题）
// 静态部署时用 VITE_API_BASE 指向后端完整地址，并让后端 CORS_ORIGINS 包含前端地址。
export default defineConfig(({ mode }) => ({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    host: '127.0.0.1',
    port: 5175,
    // ★ 端口被占用/被系统保留时自动顺延（5176、5177…），并打印实际地址。
    //   为什么必须开：有些 Windows 机器会把一段端口划给 Hyper-V/WSL 保留
    //   （`netsh int ipv4 show excludedportrange protocol=tcp` 可查），
    //   落在保留段里的端口连 bind 都不允许，直接报
    //   `Error: listen EACCES: permission denied 127.0.0.1:5175` —— 那不是代码问题。
    strictPort: false,
    // 代理模式下后端地址可用 VITE_PROXY_TARGET 覆盖
    proxy:
      mode === 'static'
        ? undefined
        : {
            '/api': {
              target: process.env.VITE_PROXY_TARGET || 'http://127.0.0.1:8000',
              changeOrigin: true,
            },
          },
  },
  build: {
    outDir: 'dist',
    chunkSizeWarningLimit: 1500,
  },
}))
