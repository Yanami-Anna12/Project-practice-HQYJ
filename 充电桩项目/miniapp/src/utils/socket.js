/**
 * 消息中心的实时未读推送。
 *
 * 后端端点：`GET /api/v1/ws/notifications?token=<JWT>`（见 backend/app/api/ws.py）
 * 推送报文：`{ type: 'unread', unread_count: 3, latest: { id, title, msg_type, created_at } }`
 *
 * ★ 为什么还要一个「轮询兜底」：
 *   uni.connectSocket 在 **H5 端本机实测不返回 SocketTask**（拿到的不是任务对象，
 *   是 { errMsg } 之类），没有 task 就没有 onMessage/onClose，实时推送直接失效。
 *   这是 H5 实现的既有行为，不是本项目引入的。
 *   微信小程序端走原生 socket，一切正常。
 *   所以这里统一封装：能拿到 SocketTask 就用长连接，拿不到就退化成
 *   **定时拉未读数**（30 秒一次）—— 用户看到的效果一样（红点会亮），
 *   只是延迟大一些，且不会因为 H5 上连不上就把功能整个砍掉。
 *
 * ★ 订阅者只管「收到一次推送」，不关心底层是长连接还是轮询。
 */

import { WS_BASE, wsUrl } from '@/config'
import { getToken } from './storage'

/** 已注册的订阅者 */
const handlers = new Set()

/** socket 任务实例（拿不到就是 null，此时走轮询） */
let socketTask = null
/** 轮询定时器 */
let pollTimer = null
/** 当前连接是否已建立（避免重复 connect） */
let connecting = false

/** 广播一条报文给所有订阅者（单个订阅者报错不影响其它订阅者） */
function emit(payload) {
  handlers.forEach((handler) => {
    try {
      handler(payload)
    } catch (err) {
      console.warn('[socket] 订阅回调异常', err)
    }
  })
}

/** 轮询兜底：定时查一次未读数，包成与 WebSocket 相同的报文结构 */
function startPolling() {
  if (pollTimer) return
  console.log('[socket] 当前平台未返回 SocketTask，实时推送不可用，改用定时刷新未读数')
  pollTimer = setInterval(async () => {
    if (!getToken()) return
    // 动态 import 避免和 api 层形成循环依赖（api → request → socket → api）
    const api = await import('@/api')
    try {
      const data = await api.fetchMessageList({ page: 1, page_size: 1 })
      emit({
        type: 'unread',
        unread_count: (data && data.unread_count) || 0,
        latest: (data && data.items && data.items[0]) || null,
        via: 'polling',
      })
    } catch (err) {
      console.warn('[socket] 轮询未读数失败', err)
    }
  }, 30000)
}

/** 停止轮询 */
function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

/**
 * 建立通知连接（幂等：已连或正在连时什么都不做）。
 * 登录成功后、App onShow 时都可以安全调用。
 */
export function connectNotificationSocket() {
  if (socketTask || connecting) return
  const token = getToken()
  if (!token) return

  connecting = true
  const url = wsUrl(`/api/v1/ws/notifications?token=${encodeURIComponent(token)}`)

  let task = null
  try {
    task = uni.connectSocket({ url, complete: () => {} })
  } catch (err) {
    console.warn('[socket] 建立连接失败', err)
  }

  // ★ 关键判断：拿不到 SocketTask 就没有 onMessage，必须走兜底
  if (!task || typeof task.onMessage !== 'function') {
    connecting = false
    startPolling()
    return
  }

  socketTask = task
  connecting = false

  task.onMessage((res) => {
    let payload = res && res.data
    if (typeof payload === 'string') {
      try {
        payload = JSON.parse(payload)
      } catch (err) {
        return
      }
    }
    if (payload) emit(payload)
  })

  task.onClose(() => {
    socketTask = null
    // 断线后 5 秒重连一次（不做指数退避：现场演示只需要它自己回来）
    setTimeout(() => {
      if (getToken()) connectNotificationSocket()
    }, 5000)
  })

  task.onError(() => {
    socketTask = null
    startPolling()
  })
}

/** 断开连接并停掉轮询（退出登录 / 401 时调用） */
export function closeNotificationSocket() {
  stopPolling()
  if (socketTask) {
    try {
      socketTask.close({ code: 1000 })
    } catch (err) {
      /* 忽略关闭异常 */
    }
    socketTask = null
  }
  connecting = false
}

/**
 * 订阅通知。
 * @param {(payload:object)=>void} handler
 * @returns {() => void} 取消订阅
 */
export function subscribeNotifications(handler) {
  handlers.add(handler)
  return () => handlers.delete(handler)
}

export default { connectNotificationSocket, closeNotificationSocket, subscribeNotifications }
