/**
 * 本地缓存读写。
 *
 * ★ 集中在一个文件里，是为了让「登录态存在哪」只有一个答案：
 *   页面和 api 层都不直接碰 uni.getStorageSync。
 */

const TOKEN_KEY = 'logistics_token'
const USER_KEY = 'logistics_user'

/** 读取 token（没有返回空串，调用方不用处理 null） */
export function getToken() {
  try {
    return uni.getStorageSync(TOKEN_KEY) || ''
  } catch (err) {
    console.warn('[storage] 读取 token 失败', err)
    return ''
  }
}

/** 写入 token */
export function setToken(token) {
  try {
    uni.setStorageSync(TOKEN_KEY, token || '')
  } catch (err) {
    console.warn('[storage] 写入 token 失败', err)
  }
}

/** 读取登录用户信息（登录接口返回的 user 对象） */
export function getStoredUser() {
  try {
    return uni.getStorageSync(USER_KEY) || null
  } catch (err) {
    console.warn('[storage] 读取用户信息失败', err)
    return null
  }
}

/** 写入登录用户信息 */
export function setStoredUser(user) {
  try {
    uni.setStorageSync(USER_KEY, user || null)
  } catch (err) {
    console.warn('[storage] 写入用户信息失败', err)
  }
}

/** 清空登录态（401 与退出登录都走这里，保证清理口径一致） */
export function clearAuthStorage() {
  try {
    uni.removeStorageSync(TOKEN_KEY)
    uni.removeStorageSync(USER_KEY)
  } catch (err) {
    console.warn('[storage] 清理登录态失败', err)
  }
}
