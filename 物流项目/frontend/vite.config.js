import { fileURLToPath, URL } from 'node:url'
import net from 'node:net'
import { writeFileSync } from 'node:fs'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// dev      默认，通过 Vite 代理把 /api 转发到后端（推荐，无跨域问题）
// 静态部署时用 VITE_API_BASE 指向后端完整地址，并让后端 CORS_ORIGINS 包含前端地址。

// ---------- 端口自动选择（别删，这是台机器上跑不起来的根因修复）----------
// 有些 Windows 机器会把一段端口划给 Hyper-V/WSL 保留，
//   `netsh int ipv4 show excludedportrange protocol=tcp` 可查（本机是 5041-5240）；
//   落在保留段里的端口连 bind 都不允许，直接报
//   `Error: listen EACCES: permission denied 127.0.0.1:5175`。
// ★ 关键：vite 自带的 `strictPort: false` 只在 EADDRINUSE（端口被普通进程占用）时
//   顺延到下一个端口，**EACCES 是致命错误、直接退出**，所以「自动顺延」救不了 5175。
//   必须在启动前自己探一次，探不过就跳过。
const PREFERRED_PORT = Number(process.env.VITE_PORT || 5175)
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
      // 写给 start.bat：让它打开真正在用的地址（与后端 backend/.runtime_port 同一套路）
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

export default defineConfig(async ({ mode }) => ({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    host: '127.0.0.1',
    port: await pickPort(),
    // 端口已经探过了，这里设 true：万一真被抢走就明确报错，
    // 不要悄悄漂到别的端口（否则 .runtime_port 与实际地址不一致）
    strictPort: true,
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
