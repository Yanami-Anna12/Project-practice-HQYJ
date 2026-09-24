/**
 * API 调用的统一错误处理。
 *
 * 与 RBAC 项目里的 axios 拦截器职责相同，只是首版没有 axios，
 * 所以把「401 跳登录 / 403 提示 / 其余弹错误」集中在这里，
 * 避免每个页面的 catch 里各写一份。
 */

import { ElMessage } from 'element-plus'
import { clearAuthStorage } from './storage'

/**
 * 包装一次接口调用：
 *   - 成功返回数据
 *   - 失败弹提示，并返回 fallback（默认 null），页面不必再写 catch
 *
 * @param {Function} fn 返回 Promise 的接口调用
 * @param {*} fallback 失败时的返回值
 * @param {object} options { silent: 不弹提示 }
 */
export async function withError(fn, fallback = null, options = {}) {
  try {
    return await fn()
  } catch (err) {
    const code = err?.code
    const message = err?.message || '请求失败'

    if (code === 401) {
      // 登录态失效：清理本地状态并回登录页
      clearAuthStorage()
      if (!window.location.pathname.startsWith('/login')) {
        window.location.href = '/login'
      }
    } else if (!options.silent) {
      ElMessage.error(code === 403 ? `${message}（无权限）` : message)
    }
    return fallback
  }
}

/**
 * 用于「关键写操作」：失败时抛出，让调用方能判断是否继续（例如关闭对话框）。
 * 返回 true 表示成功。
 */
export async function tryAction(fn, successMessage) {
  try {
    const result = await fn()
    if (successMessage) ElMessage.success(successMessage)
    return { ok: true, result }
  } catch (err) {
    const message = err?.message || '操作失败'
    ElMessage.error(err?.code === 403 ? `${message}（无权限）` : message)
    return { ok: false, error: err }
  }
}
