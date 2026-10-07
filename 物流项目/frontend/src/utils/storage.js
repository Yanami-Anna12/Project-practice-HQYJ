/**
 * Token 与用户信息的本地持久化。
 *
 * ★ 安全提示：
 *   这里保存的 permissions 只影响**界面显示**。真正的把关在后端：
 *   每次请求后端都会重新计算用户的有效权限（见 backend/app/services/rbac.py）。
 *   即使有人手工改了 localStorage 给自己「加权限」，调接口照样 403。
 *
 * ★ 这里**不保存菜单树**：菜单是服务端的授权状态，必须每次向服务端取。
 *   否则后端改了菜单或权限后，用户不重新登录就看不到变化。
 */

const TOKEN_KEY = 'logistics_token'
const USER_KEY = 'logistics_user'

export function getToken() {
  return localStorage.getItem(TOKEN_KEY) || ''
}

export function setToken(token) {
  if (token) localStorage.setItem(TOKEN_KEY, token)
}

export function removeToken() {
  localStorage.removeItem(TOKEN_KEY)
}

export function getStoredUser() {
  try {
    const raw = localStorage.getItem(USER_KEY)
    return raw ? JSON.parse(raw) : null
  } catch {
    // 数据被手工改坏时按「未登录」处理，不抛异常
    return null
  }
}

export function setStoredUser(user) {
  if (user) localStorage.setItem(USER_KEY, JSON.stringify(user))
}

export function clearAuthStorage() {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(USER_KEY)
  // 清理旧版本遗留的菜单缓存（早期版本会把它写进 localStorage）
  localStorage.removeItem('logistics_menus')
}
