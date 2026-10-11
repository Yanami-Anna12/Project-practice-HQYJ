/**
 * 本地缓存读写。
 *
 * ★ 集中在一个文件里，是为了让「登录态存在哪」只有一个答案：
 *   页面和 api 层都不直接碰 uni.getStorageSync。
 *
 * ★ 充电桩后端登录接口只返回 access_token + user（**不含权限点**），
 *   权限点要再调一次 GET /auth/profile 才拿得到。所以这里存三样东西：
 *   token / user / 权限画像（permissions + role），三者一起写、一起清。
 */

const TOKEN_KEY = 'cp_token'
const USER_KEY = 'cp_user'
const PROFILE_KEY = 'cp_profile'

function read(key) {
  try {
    return uni.getStorageSync(key) || null
  } catch (err) {
    console.warn(`[storage] 读取 ${key} 失败`, err)
    return null
  }
}

function write(key, value) {
  try {
    uni.setStorageSync(key, value)
  } catch (err) {
    console.warn(`[storage] 写入 ${key} 失败`, err)
  }
}

/** 读取 token（没有返回空串，调用方不用处理 null） */
export function getToken() {
  return read(TOKEN_KEY) || ''
}

/** 写入 token */
export function setToken(token) {
  write(TOKEN_KEY, token || '')
}

/** 读取登录用户信息（登录/资料接口返回的 user 对象） */
export function getStoredUser() {
  return read(USER_KEY)
}

/** 写入登录用户信息 */
export function setStoredUser(user) {
  write(USER_KEY, user || null)
}

/** 读取账号画像：{ permissions: string[], role: object|null } */
export function getStoredProfile() {
  return read(PROFILE_KEY) || { permissions: [], role: null }
}

/** 写入账号画像（/auth/profile 的 permissions + role） */
export function setStoredProfile(profile) {
  write(PROFILE_KEY, {
    permissions: (profile && profile.permissions) || [],
    role: (profile && profile.role) || null,
  })
}

/** 清空登录态（401 与退出登录都走这里，保证清理口径一致） */
export function clearAuthStorage() {
  try {
    uni.removeStorageSync(TOKEN_KEY)
    uni.removeStorageSync(USER_KEY)
    uni.removeStorageSync(PROFILE_KEY)
  } catch (err) {
    console.warn('[storage] 清理登录态失败', err)
  }
}
