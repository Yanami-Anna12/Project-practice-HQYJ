import { defineConfig } from 'vite'
import uni from '@dcloudio/vite-plugin-uni'

/**
 * Vite 配置。
 *
 * ★ H5 开发时用 /api 代理转发到后端，避免浏览器跨域；
 *   小程序端不走代理（小程序没有浏览器同源限制），直接请求 config.js 里的绝对地址。
 *
 * ★ `/api` 代理必须开 `ws: true`：WebSocket 实时推送
 *   （/api/ws/notifications?token=...）也走这个前缀，不开的话
 *   升级请求会被 Vite 当成普通 HTTP 请求处理，握手直接 404。
 */
export default defineConfig({
  plugins: [uni()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        ws: true,
      },
      // 上传后的照片由后端的 /uploads 静态目录提供，H5 下同样需要代理
      '/uploads': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist/build/h5',
  },
})
