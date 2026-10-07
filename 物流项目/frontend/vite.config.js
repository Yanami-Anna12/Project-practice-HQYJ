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
