import { fileURLToPath, URL } from 'node:url'
import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'

// 端口与后端地址均可通过环境变量覆盖，便于与同机其他项目并存：
//   充电桩运维 AI Agent 项目默认 5185 -> 8010
//   车辆智能调度 Agent 项目    默认 5175 -> 8000
// 在前端目录新建 .env.local 写入 VITE_PORT / VITE_API_TARGET 即可改。
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const port = Number(env.VITE_PORT || 5185)
  const apiTarget = env.VITE_API_TARGET || 'http://127.0.0.1:8010'

  return {
    plugins: [vue()],
    resolve: {
      alias: {
        '@': fileURLToPath(new URL('./src', import.meta.url)),
      },
    },
    server: {
      host: '127.0.0.1',
      port,
      strictPort: false,
      proxy: {
        // 后端 FastAPI（含 WebSocket 进度推送）
        '/api': {
          target: apiTarget,
          changeOrigin: true,
          ws: true,
        },
        '/static': {
          target: apiTarget,
          changeOrigin: true,
        },
      },
    },
    build: {
      chunkSizeWarningLimit: 1500,
      rollupOptions: {
        output: {
          manualChunks: {
            echarts: ['echarts'],
            antd: ['ant-design-vue', '@ant-design/icons-vue'],
          },
        },
      },
    },
  }
})
