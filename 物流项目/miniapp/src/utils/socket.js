/**
 * WebSocket 实时推送客户端（司机端）。
 *
 * 对应后端 `GET /api/ws/notifications?token=<JWT>`（见 backend/app/routers/ws.py）。
 * 目标：管理员在网页端点「下发执行」时，司机端**当场**有反应 ——
 * 未读红点 +1、正在看的消息页直接刷新、新任务下发还会弹一条轻提示。
 *
 * ★ 五个必须处理好的点（都是小程序 WebSocket 的坑）：
 *
 *   1. **token 走 query 而不是 header**：小程序 `uni.connectSocket` 不能可靠地
 *      自定义请求头，所以后端同时支持 `?token=`（见 routers/ws.py 的注释）。
 *
 *   2. **一个进程只连一条**：连接是全应用共享的，页面通过 subscribeNotifications()
 *      订阅，绝不能每个页面各连一条（小程序对并发连接数有限制，超过会被掐）。
 *
 *   3. **断线必须自动重连**：切后台、切网络、后端重启都会断。用指数退避
 *      （1s → 2s → 4s … 封顶 30s），并且监听网络恢复事件立刻重连，
 *      不然司机从电梯里出来要等到下一个退避周期才有实时性。
 *
 *   4. **退出登录必须断开**：否则上一个账号还能收到推送（共享设备上是隐私问题）。
 *
 *   5. **握手被拒时拿不到 4401**：服务端对无效 token 是 `close(4401)`，
 *      但那发生在 accept 之前，客户端看到的只是「连接失败 / code 1006」。
 *      所以这里不靠关闭码判断登录失效：token 没了就停止重连，
 *      token 过期由 utils/request.js 的 401 兜底（跳登录页）。
 */

import { wsUrl } from '@/config'
import { getToken } from './storage'

/** 后端约定的推送路径 */
const WS_PATH = '/api/ws/notifications'

/** 重连退避：首次 1s，之后每次翻倍，封顶 30s */
const RECONNECT_BASE_MS = 1000
const RECONNECT_MAX_MS = 30000

/** 业务报文订阅者（{type: 'connected' | 'notification', ...}） */
const messageHandlers = new Set()
/** 连接状态订阅者（connecting / open / reconnecting / closed） */
const statusHandlers = new Set()

let task = null
/** 正在建连（connectSocket 返回前）时为 true，避免重复发起 */
let connecting = false
/** 主动断开（退出登录）标记：为 true 时不再自动重连 */
let manualClosed = false
let retryCount = 0
let retryTimer = null

/* ------------------------------------------------------------------ *
 * 订阅 / 广播
 * ------------------------------------------------------------------ */

/**
 * 订阅推送报文。返回「取消订阅」函数（页面在 onUnload 里调用）。
 * @param {(payload: object) => void} handler
 */
export function subscribeNotifications(handler) {
  messageHandlers.add(handler)
  return () => messageHandlers.delete(handler)
}

/** 订阅连接状态变化。返回取消订阅函数。 */
export function onSocketStatus(handler) {
  statusHandlers.add(handler)
  return () => statusHandlers.delete(handler)
}

function emitMessage(payload) {
  messageHandlers.forEach((handler) => {
    try {
      handler(payload)
    } catch (err) {
      // 单个订阅者出错不能影响其它订阅者（例如消息页抛错不该拖累趟次页）
      console.warn('[socket] 订阅回调异常', err)
    }
  })
}

function emitStatus(status, detail) {
  statusHandlers.forEach((handler) => {
    try {
      handler(status, detail || {})
    } catch (err) {
      console.warn('[socket] 状态回调异常', err)
    }
  })
}

/* ------------------------------------------------------------------ *
 * 连接
 * ------------------------------------------------------------------ */

/** 当前是否已连上（页面可据此决定「要不要等推送」还是「干脆自己拉一次」） */
export function isSocketOpen() {
  return !!task && task.readyState === 1
}

/**
 * 建立连接（幂等：已连 / 正在连 / 等待重连时直接返回）。
 *
 * ★ 调用时机：登录成功、App 启动、App 从后台回前台、页面 onShow。
 *   都调一次没关系，重复调用不会产生第二条连接。
 */
export function connectSocket() {
  const token = getToken()
  if (!token) return
  if (task || connecting || retryTimer) return

  manualClosed = false
  connecting = true
  emitStatus('connecting')

  const url = `${wsUrl(WS_PATH)}?token=${encodeURIComponent(token)}`
  let socket = null
  try {
    // 不传 success/fail/complete，直接拿 SocketTask（H5 与微信小程序都支持）
    socket = uni.connectSocket({ url })
  } catch (err) {
    connecting = false
    console.warn('[socket] 建立连接失败', err)
    scheduleReconnect()
    return
  }

  if (!socket || typeof socket.onOpen !== 'function') {
    // 兜底：个别平台/低版本基础库不返回 SocketTask。
    // 这里选择「不推送也要能用」——页面 onShow 仍会拉数据，只是没有实时性。
    connecting = false
    console.warn('[socket] 当前平台未返回 SocketTask，实时推送不可用')
    return
  }

  task = socket

  socket.onOpen(() => {
    connecting = false
    retryCount = 0
    console.log('[socket] 已连接实时推送')
    emitStatus('open')
  })

  socket.onMessage((res) => {
    handleFrame(res && res.data)
  })

  // ★ onError 与 onClose 在两端都可能**都**触发（H5 是 error→close，
  //   微信小程序在握手失败时也只给 onError），所以统一走 handleDown，
  //   并靠 `task !== socket` 做去重，避免安排两次重连。
  socket.onClose((res) => {
    handleDown(socket, { code: res && res.code, reason: res && res.reason })
  })

  socket.onError((err) => {
    handleDown(socket, { error: (err && (err.errMsg || err.message)) || '未知错误' })
  })
}

/** 连接断开（正常关闭 / 报错 / 网络掉线）：清理并按退避重连 */
function handleDown(socket, detail) {
  if (task !== socket) return // 已经处理过（error + close 双触发）
  task = null
  connecting = false
  if (manualClosed) {
    emitStatus('closed', detail)
    return
  }
  emitStatus('reconnecting', detail)
  scheduleReconnect()
}

/** 按指数退避安排下一次重连 */
function scheduleReconnect() {
  if (manualClosed || retryTimer) return
  if (!getToken()) return // 已退出登录：不再重连
  const delay = Math.min(RECONNECT_BASE_MS * 2 ** retryCount, RECONNECT_MAX_MS)
  retryCount += 1
  retryTimer = setTimeout(() => {
    retryTimer = null
    connectSocket()
  }, delay)
}

/**
 * 主动断开（退出登录、切换账号）。
 * ★ 会把 manualClosed 置真，因此不会再自动重连。
 */
export function closeSocket() {
  manualClosed = true
  retryCount = 0
  if (retryTimer) {
    clearTimeout(retryTimer)
    retryTimer = null
  }
  const socket = task
  task = null
  connecting = false
  if (socket) {
    try {
      socket.close({ code: 1000, reason: 'client logout' })
    } catch (err) {
      console.warn('[socket] 关闭连接失败', err)
    }
  }
  emitStatus('closed', { reason: 'manual' })
}

/** 账号切换时用：断开并清掉退避计数，下一次 connectSocket 立刻重连 */
export function resetSocket() {
  closeSocket()
  manualClosed = false
  retryCount = 0
}

/* ------------------------------------------------------------------ *
 * 收报文
 * ------------------------------------------------------------------ */

/** 发一条 JSON（连接不可用时静默丢弃：心跳丢了不值得打扰用户） */
function sendJson(payload) {
  if (!task) return
  try {
    task.send({ data: JSON.stringify(payload) })
  } catch (err) {
    console.warn('[socket] 发送失败', err)
  }
}

/**
 * 处理后端报文。
 *
 * 后端会发三种：connected（首帧）/ notification（业务）/ ping（保活）。
 * 这里把 connected 与 notification 广播给订阅者（页面按 type 自行判断），
 * ping 直接回 pong，不打扰页面。
 */
function handleFrame(raw) {
  let payload = raw
  if (typeof payload === 'string') {
    try {
      payload = JSON.parse(payload)
    } catch (err) {
      console.warn('[socket] 报文不是合法 JSON，已忽略', raw)
      return
    }
  }
  if (!payload || typeof payload !== 'object') return

  if (payload.type === 'ping') {
    sendJson({ type: 'pong' })
    return
  }
  if (payload.type === 'pong') return

  emitMessage(payload)
}

/* ------------------------------------------------------------------ *
 * 网络恢复
 * ------------------------------------------------------------------ */

let networkBound = false

/**
 * 监听网络恢复：从 4G 切回 WiFi、断网重连后立刻建连，
 * 不用等退避计时器（司机端最常见的场景就是路上信号断断续续）。
 */
export function bindNetworkWatcher() {
  if (networkBound) return
  networkBound = true
  try {
    uni.onNetworkStatusChange((res) => {
      if (!res || !res.isConnected) return
      if (manualClosed || !getToken()) return
      retryCount = 0
      if (retryTimer) {
        clearTimeout(retryTimer)
        retryTimer = null
      }
      connectSocket()
    })
  } catch (err) {
    console.warn('[socket] 网络状态监听注册失败', err)
  }
}
