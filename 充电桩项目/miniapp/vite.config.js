import net from 'node:net'
import { writeFileSync } from 'node:fs'
import { defineConfig } from 'vite'
import uni from '@dcloudio/vite-plugin-uni'

/**
 * Vite 配置。
 *
 * ★ H5 开发走 /api、/static 代理转发到充电桩后端（8010），浏览器天然没有跨域；
 *   小程序端没有同源策略，直接用 src/config.js 里的绝对地址。
 *
 * ★ 端口必须先探测再交给 vite（与充电桩 frontend/vite.config.js 同一套路）：
 *   Windows 可能把一段端口划给 Hyper-V/WSL 保留，落在保留段里的端口连 bind 都不允许，
 *   直接报 `listen EACCES: permission denied 127.0.0.1:5173`。
 *   vite 自带的 `strictPort: false` 只在 EADDRINUSE 时顺延，EACCES 是致命错误，
 *   所以「自动顺延」救不了 —— 必须在监听前自己探一次。
 */
const PREFERRED_PORT = Number(process.env.VITE_PORT || 5190)
const PORT_CANDIDATES = [PREFERRED_PORT, 5265, 5275, 5285, 5295, 5305, 6310, 7001]

function canBind(port) {
  return new Promise((resolve) => {
    const probe = net.createServer()
    probe.once('error', () => resolve(false))
    probe.once('listening', () => probe.close(() => resolve(true)))
    probe.listen(port, '127.0.0.1')
  })
}

async function pickPort(writeRuntimeFile) {
  for (const port of PORT_CANDIDATES) {
    if (await canBind(port)) {
      if (port !== PREFERRED_PORT) {
        console.log(
          `\n[port] ${PREFERRED_PORT} 不可用（被占用，或被 Windows 保留段挡住），本次改用 ${port}`,
        )
      }
      // ★ 只在 dev（serve）时写 .runtime_port：构建（build）也走这个函数，
      //   若不判断就会用「构建那一刻恰好空着的端口」覆盖掉 dev 真实在跑的端口，
      //   之后 start/stop 脚本读到的就是错的值。实测踩过：构建把 5265 写了进去，
      //   而 dev 其实跑在 5190。
      if (writeRuntimeFile) {
        try {
          writeFileSync(new URL('./.runtime_port', import.meta.url), String(port))
        } catch {
          /* 写不进去就算了，不影响启动 */
        }
      }
      return port
    }
  }
  console.log(`\n[port] ${PORT_CANDIDATES.join(' / ')} 全部不可用，交回 vite 自己报错`)
  return PREFERRED_PORT
}

const API_TARGET = process.env.VITE_API_TARGET || 'http://127.0.0.1:8010'

export default defineConfig(async ({ command }) => ({
  plugins: [uni()],
  server: {
    host: '127.0.0.1',
    port: await pickPort(command === 'serve'),
    strictPort: true,
    proxy: {
      // ★ ws: true 必须开：消息中心的未读推送走 /api/v1/ws/notifications，
      //   不开的话 WebSocket 升级请求会被 Vite 当普通 HTTP 请求 404 掉。
      '/api': {
        target: API_TARGET,
        changeOrigin: true,
        ws: true,
      },
      // 上传的现场照片由后端 /static/data/uploads 提供，H5 下同样需要代理，
      // 否则 <image> 拿到的是相对路径，在 5190 上 404。
      '/static': {
        target: API_TARGET,
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist/build/h5',
  },
}))
