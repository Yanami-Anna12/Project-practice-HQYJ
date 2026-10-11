import { fileURLToPath, URL } from 'node:url'
import net from 'node:net'
import { writeFileSync } from 'node:fs'
import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'

// 端口与后端地址均可通过环境变量覆盖，便于与同机其他项目并存：
//   充电桩运维 AI Agent 项目默认 5185 -> 8010
//   车辆智能调度 Agent 项目    默认 5175 -> 8000
// 在前端目录新建 .env.local 写入 VITE_PORT / VITE_API_TARGET 即可改。

// ★ 端口必须先探测再交给 vite：Windows 可能把一段端口划给 Hyper-V/WSL 保留
//   （`netsh int ipv4 show excludedportrange protocol=tcp` 可查），落在保留段里的
//   端口连 bind 都不允许，直接报 `listen EACCES: permission denied 127.0.0.1:5185`。
//   vite 自带的 `strictPort: false` 只在 EADDRINUSE 时顺延，EACCES 是致命错误，
//   所以「自动顺延」救不了——必须在启动前自己探。
function canBind(port) {
  return new Promise((resolve) => {
    const probe = net.createServer()
    probe.once('error', () => resolve(false))
    probe.once('listening', () => probe.close(() => resolve(true)))
    probe.listen(port, '127.0.0.1')
  })
}

async function pickPort(preferred) {
  const candidates = [preferred, 5270, 5280, 5300, 5310, 5320, 5330, 5340, 6258, 6300, 7000]
  for (const port of candidates) {
    if (await canBind(port)) {
      if (port !== preferred) {
        console.log(`\n[port] ${preferred} 不可用（被占用，或被 Windows 保留段挡住），本次改用 ${port}`)
      }
      try {
        writeFileSync(new URL('./.runtime_port', import.meta.url), String(port))
      } catch {
        /* 写不进去不影响启动 */
      }
      return port
    }
  }
  return preferred
}

export default defineConfig(async ({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const port = await pickPort(Number(env.VITE_PORT || 5185))
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
      // 端口已探过：真被抢走就明确报错，别悄悄漂到 .runtime_port 之外
      strictPort: true,
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
