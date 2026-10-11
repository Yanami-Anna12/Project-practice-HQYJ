/**
 * 请求封装（uni.request + uni.uploadFile）。
 *
 * ★ 为什么不直接用 uni.request 散落在页面里：
 *   1. 每个请求都要带 Authorization，集中注入才不会漏；
 *   2. 后端响应体统一是 `{ code, message, data }`（见 backend/app/core/response.py），
 *      code === 0 才是成功；错误体是 `{ code: 401/403/404/409/422/500, message }`
 *      （见 backend/app/core/errors.py），集中拆包页面就不用各自判断；
 *   3. 网络失败要能被页面识别（err.code = 0），才能显示错误态 + 重试按钮而不是白屏。
 *
 * ★ 返回值约定：**request() 直接把解包后的 data 返回**，页面不用写 res.data.data。
 *   需要后端提示语（如「故障上报成功，等待核查」）的地方，用 requestFull()，
 *   它返回完整响应体 { code, message, data }。
 */

import { API_BASE, REQUEST_TIMEOUT } from '@/config'
import { closeNotificationSocket } from './socket'
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

/**
 * 清理 GET 查询参数：剔除 undefined / null / 空字符串。
 *
 * ★ 这不是洁癖，是本机实测踩到的真 bug：
 *   uni.request 在 GET 时把 data 对象拼成 query string，而它对 `undefined`
 *   的处理是**序列化成空串**而不是丢掉，于是请求变成
 *   `/work-orders/subtasks/mine?status=&scope_all=&page=1`。
 *   字符串参数（status/keyword）拿到空串等价于没传，没问题；
 *   但**布尔型参数**（scope_all / mine / is_read）收到空串，
 *   FastAPI 会直接返回 422「Input should be a valid boolean,
 *   unable to interpret input」—— 表现是任务列表、工单列表、消息中心
 *   三个页面同时变成一片错误态，看起来像后端挂了，其实只是参数序列化。
 *
 * ★ 只对 GET 生效：POST/PUT 的请求体里 `''` 与「不传」语义可能不同
 *   （例如把备注清空成空串），不能在请求体上做同样的过滤。
 */
function cleanQuery(data) {
  if (!data || typeof data !== 'object') return data
  const out = {}
  Object.keys(data).forEach((key) => {
    const value = data[key]
    if (value === undefined || value === null || value === '') return
    out[key] = value
  })
  return Object.keys(out).length ? out : undefined
}

/** 解析响应体：后端一定返回 JSON 字符串或对象 */
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
  // ★ 登录态没了就必须断开实时推送：否则连接还挂在旧账号上。
  closeNotificationSocket()
  if (redirecting) return
  redirecting = true
  uni.reLaunch({
    url: '/pages/login/login',
    complete: () => {
      setTimeout(() => {
        redirecting = false
      }, 1500)
    },
  })
}

/**
 * 统一请求（返回完整响应体 { code, message, data }）。
 *
 * @param {object} options
 * @param {string} options.url     接口路径，如 /auth/login（会在前面拼 API_BASE + /api/v1）
 * @param {string} [options.method] GET / POST / PUT / DELETE
 * @param {object} [options.data]  请求体或查询参数
 * @param {boolean} [options.showError] 失败时是否自动 toast（默认不弹，由页面决定）
 * @returns {Promise<{code:number,message:string,data:any}>}
 */
export function requestFull({ url, method = 'GET', data = null, header = {}, showError = false } = {}) {
  return new Promise((resolve, reject) => {
    const token = getToken()
    const finalHeader = { 'Content-Type': 'application/json', ...header }
    if (token) {
      finalHeader.Authorization = `Bearer ${token}`
    }

    const method_ = method.toUpperCase()
    // ★ GET 必须清一遍空参数，否则布尔查询参数会被序列化成空串触发 422（见 cleanQuery 注释）
    const payload = method_ === 'GET' ? cleanQuery(data) : data || undefined

    uni.request({
      url: `${API_BASE}/api/v1${url}`,
      method: method_,
      data: payload,
      header: finalHeader,
      timeout: REQUEST_TIMEOUT,
      success: (res) => {
        const body = parseBody(res.data)

        if (res.statusCode === 401) {
          gotoLogin()
          reject(makeError((body && body.message) || '登录已失效，请重新登录', 401, res))
          return
        }

        if (res.statusCode >= 200 && res.statusCode < 300 && body && body.code === 0) {
          resolve(body)
          return
        }

        const message = (body && body.message) || `请求失败（HTTP ${res.statusCode}）`
        if (showError) {
          // 409 是业务冲突（重复提交等），用 toast 足够，不用弹窗打断
          uni.showToast({ title: message, icon: 'none', duration: 2500 })
        }
        reject(makeError(message, (body && body.code) || res.statusCode, res))
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

/** 统一请求（只返回 data，页面最常用的形式） */
export async function request(options) {
  const body = await requestFull(options)
  return body.data
}

/**
 * 文件上传（multipart/form-data）。
 *
 * ★ 必须用 uni.uploadFile 而不是 uni.request：
 *   uni.request 不能可靠地发 multipart（H5 端可以塞 FormData，
 *   但小程序端只有 uploadFile 支持），所以统一用 uploadFile 保证两端一致。
 *
 * ★ 一次一张：后端 /uploads/images 支持一次多张（上限 12），但现场是弱网，
 *   逐张传能给出「第几张/共几张」的进度，失败了也只重传那一张。
 *
 * @param {object} options
 * @param {string} options.filePath   本地临时文件路径（uni.chooseImage 的返回）
 * @param {string} [options.bizType]  inspection / fault / verify / station
 * @param {string} [options.bizId]    业务单据 ID，可稍后回填
 * @returns {Promise<{id:string,url:string,file_name:string,size:number}>} 单张图片信息
 */
export function uploadImage({ filePath, bizType = 'inspection', bizId } = {}) {
  return new Promise((resolve, reject) => {
    const token = getToken()
    const query = [`biz_type=${encodeURIComponent(bizType)}`]
    if (bizId) query.push(`biz_id=${encodeURIComponent(bizId)}`)

    uni.uploadFile({
      url: `${API_BASE}/api/v1/uploads/images?${query.join('&')}`,
      filePath,
      name: 'files', // ★ 后端参数名是 files（复数），写错会返回 422 参数校验失败
      header: token ? { Authorization: `Bearer ${token}` } : {},
      timeout: 60000, // 照片上传放宽超时：弱网下 20 秒经常不够
      success: (res) => {
        const body = parseBody(res.data)
        if (res.statusCode >= 200 && res.statusCode < 300 && body && body.code === 0) {
          const first = (body.data && body.data.files && body.data.files[0]) || null
          if (!first) {
            reject(makeError('上传成功但没有返回图片地址', 0, res))
            return
          }
          resolve(first)
          return
        }
        if (res.statusCode === 401) {
          gotoLogin()
        }
        reject(makeError((body && body.message) || `上传失败（HTTP ${res.statusCode}）`, res.statusCode, res))
      },
      fail: (err) => {
        reject(makeError('照片上传失败，请检查网络后重试', 0, err))
      },
    })
  })
}

export default request
