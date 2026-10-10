/**
 * 请求封装（uni.request + uni.uploadFile）。
 *
 * ★ 为什么不直接用 uni.request 散落在页面里：
 *   1. 每个请求都要带 Authorization，集中注入才不会漏；
 *   2. 后端错误体统一是 {"error": "..."}（见 backend/app/errors.py），
 *      以及两种需要特殊处理的错误码：
 *        · 401 未登录 → 清 token 并跳登录页（只跳一次，避免并发请求跳多次）
 *        · 409 冲突   → 打卡重复等业务冲突，交给页面提示，不算「系统错误」
 *   3. 网络失败要能被页面识别（code = 0），才能显示错误态 + 重试按钮而不是白屏。
 */

import { API_BASE, REQUEST_TIMEOUT } from '@/config'
import { closeSocket } from './socket'
import { clearAuthStorage, getToken } from './storage'

/** 跳登录页的「节流阀」：并发 3 个请求同时 401 时只跳一次 */
let redirecting = false

/** 构造带 code 的错误对象，方便页面区分「业务冲突」和「网络不通」 */
function makeError(message, code = 0, raw = null) {
  const err = new Error(message || '请求失败')
  err.code = code
  err.raw = raw
  return err
}

/** 解析响应体：后端错误返回 {"error": "..."}，正常返回业务 JSON */
function parseBody(data) {
  if (data === null || data === undefined || data === '') return null
  if (typeof data === 'object') return data
  try {
    return JSON.parse(data)
  } catch (err) {
    return null
  }
}

/** 跳登录页（清空本地登录态） */
function gotoLogin() {
  clearAuthStorage()
  // ★ 登录态没了就必须断开实时推送：否则连接还挂在旧账号上，
  //   换账号登录前会把上一个司机的消息推到这个页面上。
  closeSocket()
  if (redirecting) return
  redirecting = true
  uni.reLaunch({
    url: '/pages/login/login',
    complete: () => {
      // 留一点时间给跳转，之后允许再次触发
      setTimeout(() => {
        redirecting = false
      }, 1500)
    },
  })
}

/**
 * 统一请求。
 *
 * @param {object} options
 * @param {string} options.url     接口路径，如 /api/mobile/my-trips
 * @param {string} [options.method] GET / POST / PUT / DELETE
 * @param {object} [options.data]  请求体或查询参数
 * @param {boolean} [options.showError] 失败时是否自动 toast（默认不弹，由页面决定）
 * @returns {Promise<any>} 解析后的响应体
 */
export function request({ url, method = 'GET', data = null, header = {}, showError = false } = {}) {
  return new Promise((resolve, reject) => {
    const token = getToken()
    const finalHeader = { 'Content-Type': 'application/json', ...header }
    if (token) {
      finalHeader.Authorization = `Bearer ${token}`
    }

    uni.request({
      url: `${API_BASE}${url}`,
      method: method.toUpperCase(),
      data: data || undefined,
      header: finalHeader,
      timeout: REQUEST_TIMEOUT,
      success: (res) => {
        const body = parseBody(res.data)
        if (res.statusCode >= 200 && res.statusCode < 300) {
          resolve(body)
          return
        }

        const message = (body && body.error) || `请求失败（HTTP ${res.statusCode}）`

        if (res.statusCode === 401) {
          // 未登录 / token 过期：清登录态回登录页
          gotoLogin()
          reject(makeError(message, 401, res))
          return
        }

        if (showError) {
          // 409 是业务冲突（重复打卡等），用 toast 足够，不用弹窗打断
          uni.showToast({ title: message, icon: 'none', duration: 2500 })
        }
        reject(makeError(message, res.statusCode, res))
      },
      fail: (err) => {
        // 网络层失败（后端没起、域名没配、断网）：code = 0，页面显示错误态 + 重试
        const message = `无法连接后端服务（${API_BASE || '当前域名'}），请确认后端已启动`
        if (showError) {
          uni.showToast({ title: message, icon: 'none', duration: 3000 })
        }
        reject(makeError(message, 0, err))
      },
    })
  })
}

/**
 * 文件上传（multipart/form-data）。
 *
 * ★ 必须用 uni.uploadFile 而不是 uni.request：
 *   uni.request 不能可靠地发 multipart（H5 端可以塞 FormData，
 *   但小程序端只有 uploadFile 支持），所以统一用 uploadFile 保证两端一致。
 *
 * @param {object} options
 * @param {string} options.filePath  本地临时文件路径（uni.chooseImage 的返回）
 * @param {string} [options.name]    服务端字段名，后端定义为 file
 * @param {object} [options.formData] 附加表单字段（这里是 biz_type 之外的自定义项）
 * @returns {Promise<object>} 后端返回的 MobileFileOut
 */
export function upload({ filePath, name = 'file', formData = {} } = {}) {
  return new Promise((resolve, reject) => {
    const token = getToken()
    uni.uploadFile({
      url: `${API_BASE}/api/mobile/files`,
      filePath,
      name,
      formData,
      header: token ? { Authorization: `Bearer ${token}` } : {},
      timeout: 60000, // 照片上传放宽超时：弱网下 20 秒经常不够
      success: (res) => {
        const body = parseBody(res.data)
        if (res.statusCode >= 200 && res.statusCode < 300 && body) {
          resolve(body)
          return
        }
        if (res.statusCode === 401) {
          gotoLogin()
        }
        const message = (body && body.error) || `上传失败（HTTP ${res.statusCode}）`
        reject(makeError(message, res.statusCode, res))
      },
      fail: (err) => {
        reject(makeError('照片上传失败，请检查网络后重试', 0, err))
      },
    })
  })
}

export default request
