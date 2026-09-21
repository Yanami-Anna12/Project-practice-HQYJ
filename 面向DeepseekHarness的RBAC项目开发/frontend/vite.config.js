import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 两种运行模式：
//   dev         默认，通过 Vite 代理把 /api 转发到后端（推荐，无跨域问题）
//   dev:static  直接构建成静态文件，用任意静态服务器托管；
//               此时 VITE_API_BASE 需指向后端完整地址，且后端 .env 的
//               CORS_ORIGINS 要包含前端地址
export default defineConfig(({ mode }) => ({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    host: '127.0.0.1',
    port: mode === 'static' ? 5174 : 5173,
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
