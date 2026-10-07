/**
 * axios 实例与拦截器。
 *
 * 两个拦截器的职责分工，对应后端的两种错误：
 *   401 → 未登录（Token 缺失/过期/用户被停用）→ 清空登录态，跳登录页
 *   403 → 已登录但无权限 → 不跳转，弹提示即可（用户是登录状态，跳登录页没意义）
 *
 * ★ 刻意不做「403 自动降级/隐藏」之类的处理：403 是「前端界面与后端权限不一致」
 *   的信号，把它藏起来只会让权限 bug 更难发现。
 */

import axios from 'axios'
import { ElMessage } from 'element-plus'
import { clearAuthStorage, getToken } from '@/utils/storage'

// 默认走相对路径 /api，由 Vite 代理转发到后端；
// 静态部署时用 VITE_API_BASE 指向后端完整地址。
const baseURL = import.meta.env.VITE_API_BASE || ''

const request = axios.create({
  baseURL,
  timeout: 20000,
})

// 请求拦截器：注入 Bearer Token
request.interceptors.request.use(
  (config) => {
    const token = getToken()
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => Promise.reject(error),
)

// 响应拦截器：统一错误处理
request.interceptors.response.use(
  (response) => response.data,
  (error) => {
    const { response } = error
    // 后端所有错误都遵循 {"error": "..."} 格式（见 backend/app/errors.py）
    const message = response?.data?.error || error.message || '请求失败'

    // 构造带 code 的错误，让调用方能判断（utils/error.js 依赖这一点）
    const wrapped = new Error(message)
    wrapped.code = response?.status ?? 0
    wrapped.raw = error

    if (!response) {
      ElMessage.error('无法连接后端服务，请确认后端已启动（python run.py）')
      return Promise.reject(wrapped)
    }

    if (response.status === 401) {
      // 未登录：清理本地状态并回登录页
      clearAuthStorage()
      ElMessage.error(message)
      // 用 location 而不是 router，避免在拦截器里引入 router 造成循环依赖
      if (!window.location.pathname.startsWith('/login')) {
        window.location.href = '/login'
      }
    } else if (response.status === 403) {
      // ★ 已登录但无权限。这正是「前端隐藏按钮只是体验优化」的兜底体现：
      //   即使有人绕过界面直接调接口，也会走到这里。
      ElMessage.error(`${message}（后端接口拒绝了本次请求）`)
    } else {
      ElMessage.error(message)
    }

    return Promise.reject(wrapped)
  },
)

export default request
