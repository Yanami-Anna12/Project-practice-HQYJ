import net from 'node:net'
import { writeFileSync } from 'node:fs'
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

// ---------- 端口自动选择（与物流 frontend/vite.config.js 同一套路）----------
// Windows 可能把一段端口划给 Hyper-V/WSL 保留（`netsh int ipv4 show excludedportrange
// protocol=tcp` 可查，本机是 5041-5240）：落在保留段里的端口连 bind 都不允许，
// 直接报 `Error: listen EACCES: permission denied 127.0.0.1:5173`。
// ★ vite 的 `strictPort: false` 只在 EADDRINUSE 时顺延，EACCES 是致命错误，
//   所以必须在启动前自己探一次。
const PREFERRED_PORT = Number(process.env.VITE_PORT || 5173)
const PORT_CANDIDATES = [PREFERRED_PORT, 5250, 5260, 5300, 5310, 5320, 5330, 5340, 6258, 6300, 7000]

function canBind(port) {
  return new Promise((resolve) => {
    const probe = net.createServer()
    probe.once('error', () => resolve(false))
    probe.once('listening', () => probe.close(() => resolve(true)))
    probe.listen(port, '127.0.0.1')
  })
}

async function pickPort() {
  for (const port of PORT_CANDIDATES) {
    if (await canBind(port)) {
      if (port !== PREFERRED_PORT) {
        console.log(
          `\n[port] ${PREFERRED_PORT} 不可用（被占用，或被 Windows 保留段挡住），本次改用 ${port}`,
        )
      }
      try {
        writeFileSync(new URL('./.runtime_port', import.meta.url), String(port))
      } catch {
        /* 写不进去就算了，不影响启动 */
      }
      return port
    }
  }
  console.log(`\n[port] ${PORT_CANDIDATES.join(' / ')} 全部不可用，交回 vite 自己报错`)
  return PREFERRED_PORT
}

export default defineConfig(async () => ({
  plugins: [uni()],
  server: {
    host: '127.0.0.1',
    port: await pickPort(),
    strictPort: true,
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
}))
