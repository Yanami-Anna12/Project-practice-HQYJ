/**
 * Token 与用户信息的本地持久化。
 *
 * 为什么单独抽一个文件：为了让「存了什么、键名是什么」只有一个定义，
 * 避免 axios 拦截器、Pinia store、路由守卫各自手写 localStorage 键名而写错。
 *
 * ★ 安全提示（很重要）：
 *   这里保存的 permissions 可以被用户随意修改。它只影响界面显示，
 *   不影响后端鉴权 —— 后端每次请求都会重新查库计算真实权限。
 *   把这一点想清楚，是理解「前端隐藏 ≠ 安全控制」的关键。
 */

const TOKEN_KEY = 'rbac_token'
const USER_KEY = 'rbac_user'
const MENUS_KEY = 'rbac_menus'

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
    // 数据被手工改坏时不抛异常，按"未登录"处理即可
    return null
  }
}

export function setStoredUser(user) {
  if (user) localStorage.setItem(USER_KEY, JSON.stringify(user))
}

/** 缓存菜单树，避免每次刷新页面都重新请求（菜单变化由登录/改权限触发） */
export function getStoredMenus() {
  try {
    const raw = localStorage.getItem(MENUS_KEY)
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

export function setStoredMenus(menus) {
  if (menus) localStorage.setItem(MENUS_KEY, JSON.stringify(menus))
}

export function clearAuthStorage() {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(USER_KEY)
  localStorage.removeItem(MENUS_KEY)
}
