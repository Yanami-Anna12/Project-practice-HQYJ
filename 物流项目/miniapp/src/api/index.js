/**
 * 数据访问层 —— 司机端接口，与 backend/app/routers/mobile.py 一一对应。
 *
 * ★ 页面只 import 本模块，不直接碰 uni.request，
 *   所以「后端换地址/换字段」的改动只影响这一个文件。
 *
 * 接口清单（前缀 /api/mobile）：
 *   GET  /profile                               司机档案 + 名下车辆
 *   GET  /my-trips?schedule_date=YYYY-MM-DD     我的趟次
 *   GET  /trips/{trip_key}                      趟次详情（站点序列）
 *   POST /trips/{trip_key}/accept               司机确认接单（幂等）
 *   POST /checkin                               到店 / 离店 / 完成打卡
 *   POST /exceptions                            异常上报
 *   POST /files                                 multipart 图片上传
 *   GET  /notifications                         消息列表
 *   GET  /notifications/unread-count            未读数
 *   POST /notifications/{id}/read               标记已读
 *
 * 管理端只读首页（小程序「今日看板」）走的是**网页端同名的调度接口**
 * （/api/scheduling/*，权限点 scheduling:read 与网页端完全一致），
 * 只有聚合数字用司机端前缀下的 /api/mobile/manager/overview：
 *   GET  /manager/overview                      今日看板聚合数字
 */

import { request, upload as uploadFile } from '@/utils/request'
import { UPLOAD_BASE } from '@/config'

/* ------------------------------------------------------------------ *
 * 认证（复用管理端的登录接口）
 * ------------------------------------------------------------------ */

/** 账号密码登录，返回 { token, user } */
export function login({ username, password }) {
  return request({
    url: '/api/auth/login',
    method: 'POST',
    data: { username, password },
  })
}

/**
 * 当前登录用户信息（角色 / 权限）。
 *
 * ★ 登录响应里其实已经带了一份同样的 user，为什么还要这个方法：
 *   登录后按角色分流是本项目「一个包服务两类角色」的关键判断，
 *   用服务端**此刻**的结果再取一次，可以避免「本地缓存的旧角色
 *   把人带进没有权限的页面」这类只有在现场演示时才暴露的问题。
 */
export function fetchMe() {
  return request({ url: '/api/me' })
}

/* ------------------------------------------------------------------ *
 * 司机档案
 * ------------------------------------------------------------------ */

/** 当前司机档案（含名下车辆）。非司机账号返回 is_driver = false，不报错 */
export function fetchProfile() {
  return request({ url: '/api/mobile/profile' })
}

/* ------------------------------------------------------------------ *
 * 我的趟次
 * ------------------------------------------------------------------ */

/**
 * 我的趟次列表。
 * @param {string} [schedule_date] 调度日期 YYYY-MM-DD；不传返回全部已下发趟次
 */
export function fetchMyTrips(scheduleDate) {
  return request({
    url: '/api/mobile/my-trips',
    method: 'GET',
    data: scheduleDate ? { schedule_date: scheduleDate } : undefined,
  })
}

/** 趟次详情：trip_key 形如 3:5:12:1（任务:方案:车辆:趟次） */
export function fetchTripDetail(tripKey) {
  return request({ url: `/api/mobile/trips/${encodeURIComponent(tripKey)}` })
}

/**
 * 司机确认接单（确认收到该趟任务）。
 *
 * ★ 后端是**幂等**的：重复调用返回 200，`already_accepted=true`，
 *   且 `accepted_at` 始终是首次确认时间。所以页面不需要额外防重逻辑，
 *   连点两次也只会留下一个确认时间（按钮仍会禁用，那是体验优化）。
 *
 * @returns {Promise<object>} { accepted, accepted_at, already_accepted, message, ... }
 */
export function acceptTrip(tripKey) {
  return request({
    url: `/api/mobile/trips/${encodeURIComponent(tripKey)}/accept`,
    method: 'POST',
  })
}

/* ------------------------------------------------------------------ *
 * 现场打卡
 * ------------------------------------------------------------------ */

/**
 * 现场打卡。
 *
 * ★ 后端对重复打卡返回 409（例如连点两次「到店」），
 *   这个错误由页面捕获后给出友好提示，不作为系统异常处理。
 *
 * @param {object} payload
 * @param {number} payload.plan_detail_id 计划明细 id（详情里每站的 plan_detail_id）
 * @param {string} payload.action         arrive 到店 / depart 离店 / complete 完成
 * @param {number} [payload.latitude]     打卡定位纬度
 * @param {number} [payload.longitude]    打卡定位经度
 * @param {string} [payload.remark]       备注
 * @param {number[]} [payload.photo_attachment_ids] 现场照片附件 id
 */
export function checkin(payload) {
  return request({
    url: '/api/mobile/checkin',
    method: 'POST',
    data: {
      plan_detail_id: payload.plan_detail_id,
      action: payload.action || 'arrive',
      latitude: payload.latitude ?? null,
      longitude: payload.longitude ?? null,
      remark: payload.remark || '',
      photo_attachment_ids: payload.photo_attachment_ids || [],
    },
  })
}

/* ------------------------------------------------------------------ *
 * 异常上报
 * ------------------------------------------------------------------ */

/**
 * 异常上报（服务端复用 scheduling 的 exception_event 表）。
 *
 * @param {object} payload
 * @param {number} payload.task_id   关联调度任务（必填，异常要能触发重排）
 * @param {string} payload.event_type 异常类型
 * @param {number} [payload.plan_detail_id]
 * @param {number} [payload.store_id]
 * @param {string} [payload.trip_key]
 * @param {string} [payload.remark]
 * @param {number[]} [payload.photo_attachment_ids]
 */
export function reportException(payload) {
  return request({
    url: '/api/mobile/exceptions',
    method: 'POST',
    data: {
      task_id: payload.task_id,
      event_type: payload.event_type,
      plan_detail_id: payload.plan_detail_id ?? null,
      store_id: payload.store_id ?? null,
      trip_key: payload.trip_key || '',
      latitude: payload.latitude ?? null,
      longitude: payload.longitude ?? null,
      remark: payload.remark || '',
      photo_attachment_ids: payload.photo_attachment_ids || [],
    },
  })
}

/* ------------------------------------------------------------------ *
 * 文件上传
 * ------------------------------------------------------------------ */

/**
 * 上传一张图片，返回 { attachment_id, name, size, url, ... }。
 *
 * ★ 后端只接受 jpg / jpeg / png / webp，且 ≤ 10MB：
 *   微信开发者工具里选择非图片文件、或选了超大原图都会被拒，
 *   所以 chooseImage 时就用 sizeType: ['compressed'] 压一下。
 */
export function uploadImage(filePath, bizType = '司机端') {
  return uploadFile({
    filePath,
    name: 'file',
    formData: { biz_type: bizType },
  })
}

/**
 * 把后端返回的相对 url（/uploads/xxx.png）拼成可直接显示/上传的完整地址。
 * ★ 小程序里 <image src> 必须是绝对地址，相对路径显示不出来。
 */
export function absoluteUrl(url) {
  if (!url) return ''
  if (/^https?:\/\//i.test(url)) return url
  return `${UPLOAD_BASE}${url}`
}

/* ------------------------------------------------------------------ *
 * 站内消息
 * ------------------------------------------------------------------ */

/** 消息列表 */
export function fetchNotifications({ onlyUnread = false, limit = 50 } = {}) {
  return request({
    url: '/api/mobile/notifications',
    method: 'GET',
    data: { only_unread: onlyUnread, limit },
  })
}

/** 未读数（底部导航红点用） */
export function fetchUnreadCount() {
  return request({ url: '/api/mobile/notifications/unread-count' })
}

/** 标记单条已读，返回 { id, is_read, unread } */
export function markNotificationRead(id) {
  return request({ url: `/api/mobile/notifications/${id}/read`, method: 'POST' })
}

/* ------------------------------------------------------------------ *
 * 管理端只读首页（今日看板）
 * ------------------------------------------------------------------ *
 * ★ 为什么看板直接调网页端的 /api/scheduling/* 而不是再抄一套司机端接口：
 *   那些接口本来就对调度/管理员开放（权限点 scheduling:read），
 *   另开一套会出现「小程序和管理网页看到的任务不一样」的双口径。
 *   只有需要「一次拿全所有数字」的首页用聚合接口。
 * ------------------------------------------------------------------ */

/** 今日看板聚合数字（一次请求拿全：任务/趟次/接单/在途/异常） */
export function fetchManagerOverview() {
  return request({ url: '/api/mobile/manager/overview' })
}

/** 调度任务列表（只读） */
export function fetchSchedulingTasks({ limit = 50 } = {}) {
  return request({ url: '/api/scheduling/tasks', method: 'GET', data: { limit } })
}

/** 调度任务详情（只读）：任务 + 多套方案 */
export function fetchSchedulingTask(taskId) {
  return request({ url: `/api/scheduling/tasks/${taskId}` })
}

/** 某方案的明细（只读）：每行含 accepted / accepted_at（该趟司机是否已确认接单） */
export function fetchPlanDetails(planId) {
  return request({ url: `/api/scheduling/plans/${planId}/details` })
}

/** 异常事件列表（只读） */
export function fetchExceptions(taskId) {
  return request({
    url: '/api/scheduling/exceptions',
    method: 'GET',
    data: taskId ? { task_id: taskId } : undefined,
  })
}
