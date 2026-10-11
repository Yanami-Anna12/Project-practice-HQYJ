/**
 * 数据访问层 —— 充电桩运维小程序的全部接口。
 *
 * ★ 页面只 import 本模块，不直接碰 uni.request / uni.uploadFile，
 *   所以「后端换地址/换字段」的改动只影响这一个文件。
 * ★ 接口全部来自充电桩后端（backend/app/api/*.py），**没有为小程序新增任何后端接口**：
 *   现场作业用的 /work-orders/subtasks/mine、/work-orders/inspections 本来就存在，
 *   手机端只是换了一个更合适的入口。这样网页端与小程序端永远同一套口径。
 *
 * 返回约定：所有 request() 已把统一响应体 { code, message, data } 拆到 data，
 *   需要后端提示语的地方用 requestFull()（见下面 loadProfile 的说明）。
 */

import { STATIC_BASE } from '@/config'
import { request, requestFull, uploadImage } from '@/utils/request'

/* ================================================================== *
 * 认证与个人资料
 * ================================================================== */

/** 账号密码登录 → { access_token, expires_in, user } */
export function login({ username, password }) {
  return request({
    url: '/auth/login',
    method: 'POST',
    data: { username, password },
  })
}

/**
 * 当前账号的资料 + 权限点 + 角色。
 *
 * ★ 登录响应里**没有权限点**（只有 user），权限点必须再取一次这个接口。
 *   小程序的「按角色分流」「按钮显隐」全部依赖它，
 *   所以登录成功后必须紧接着调一次，别只看 user.role.code。
 */
export function loadProfile() {
  return request({ url: '/auth/profile' })
}

/** 修改个人资料（姓名/电话/邮箱/头像） */
export function updateProfile(data) {
  return request({ url: '/auth/profile', method: 'PUT', data })
}

/** 修改密码 → { changed: true } */
export function changePassword({ oldPassword, newPassword }) {
  return request({
    url: '/auth/change-password',
    method: 'POST',
    data: { old_password: oldPassword, new_password: newPassword },
  })
}

/** 退出登录（后端只记一条审计日志，前端负责清本地登录态） */
export function logout() {
  return request({ url: '/auth/logout', method: 'POST' })
}

/* ================================================================== *
 * 工单与作业任务（现场作业端主线）
 * ================================================================== */

/**
 * 工单首页统计。
 * ★ 后端按数据权限自动过滤（个人/站点/项目/平台），前端不用传任何过滤条件，
 *   所以运维人员拿到的是「我的工单」，管理员拿到的是全量 —— 同一个接口两种口径。
 */
export function fetchWorkOrderHome() {
  return request({ url: '/work-orders/home' })
}

/**
 * 我的作业任务（= 一个站点的一次巡检/消缺动作）。
 *
 * @param {object} [params]
 * @param {string} [params.status]   待完成 / 巡检中 / 已完成 / 已取消
 * @param {string} [params.keyword]  工单编号/名称/站点 模糊查询
 * @param {string} [params.orderType] 巡视 / 特巡 / 消缺 / 设备检查 / 其他
 * @param {boolean} [params.scopeAll] 管理员看全部（个人数据权限的账号传了也无效）
 * @param {number} [params.page]
 * @param {number} [params.pageSize]
 * @returns {Promise<{items:object[], meta:object}>}
 */
export function fetchMySubtasks(params = {}) {
  return request({
    url: '/work-orders/subtasks/mine',
    method: 'GET',
    data: {
      status: params.status || undefined,
      keyword: params.keyword || undefined,
      order_type: params.orderType || undefined,
      scope_all: params.scopeAll ? true : undefined,
      page: params.page || 1,
      page_size: params.pageSize || 20,
    },
  })
}

/**
 * 更新作业任务（状态 / 计划日期 / 执行人 / 时段）。
 * 现场最常用的是把状态从「待完成」推到「巡检中」。
 */
export function updateSubtask(subtaskId, payload) {
  return request({
    url: `/work-orders/subtasks/${subtaskId}`,
    method: 'PUT',
    data: payload,
  })
}

/**
 * 工单列表。
 * @param {object} [params]
 * @param {string} [params.status]     待接单 / 待完成 / 已完成 / 已取消 / 已退回
 * @param {string} [params.keyword]    工单编号/名称/站点
 * @param {string} [params.timeStatus] 正常 / 紧急 / 逾期
 * @param {boolean} [params.mine]      只看与我相关
 */
export function fetchWorkOrders(params = {}) {
  return request({
    url: '/work-orders',
    method: 'GET',
    data: {
      keyword: params.keyword || undefined,
      status: params.status || undefined,
      time_status: params.timeStatus || undefined,
      order_type: params.orderType || undefined,
      mine: params.mine ? true : undefined,
      page: params.page || 1,
      page_size: params.pageSize || 20,
    },
  })
}

/** 工单详情 → { work_order, subtasks, subtask_stats, stations, permissions } */
export function fetchWorkOrder(orderId) {
  return request({ url: `/work-orders/${orderId}` })
}

/**
 * 接受工单。
 * ★ 与「确认接单」不同：接受的是**整张工单**（含它的全部子任务），
 *   子任务级别没有单独的接单动作，现场直接开工即可。
 */
export function acceptWorkOrder(orderId) {
  return requestFull({ url: `/work-orders/${orderId}/accept`, method: 'POST' })
}

/** 退回工单（需填原因，退回后回到派单人手上） */
export function rejectWorkOrder(orderId, reason) {
  return requestFull({
    url: `/work-orders/${orderId}/reject`,
    method: 'POST',
    data: { reason },
  })
}

/** 取消工单 */
export function cancelWorkOrder(orderId, reason) {
  return requestFull({
    url: `/work-orders/${orderId}/cancel`,
    method: 'POST',
    data: { reason },
  })
}

/** 某工单下的全部子任务 */
export function fetchOrderSubtasks(orderId) {
  return request({ url: `/work-orders/${orderId}/subtasks` })
}

/* ================================================================== *
 * 巡检（PDF 3.4：分类巡检项、正常/异常勾选、200 字备注、多图上传）
 * ================================================================== */

/**
 * 巡检项模板（按工单类型给不同清单）。
 * @returns {Promise<{order_type:string, template:{group:string,name:string}[],
 *                    max_remark_length:number, result_options:string[]}>}
 */
export function fetchInspectionTemplate(orderType = '巡视') {
  return request({
    url: '/work-orders/inspections/template',
    method: 'GET',
    data: { order_type: orderType },
  })
}

/**
 * 提交巡检记录。
 *
 * @param {object} payload
 * @param {string} payload.subtaskId    作业任务 ID（必填）
 * @param {Array}  payload.items        [{ item_name, item_group, result, remark, images }]
 * @param {string[]} [payload.images]   整单现场照片
 * @param {string} [payload.remark]     巡检备注（≤200 字）
 * @param {object} [payload.checkin]    { location, lng, lat } 到店打卡
 * @param {object} [payload.checkout]   { location, lng, lat } 离店打卡
 * @param {boolean} [payload.finish]    true = 提交即完成（子任务置「已完成」）
 */
export function createInspection(payload) {
  const checkin = payload.checkin || {}
  const checkout = payload.checkout || {}
  return requestFull({
    url: '/work-orders/inspections',
    method: 'POST',
    data: {
      subtask_id: payload.subtaskId,
      items: (payload.items || []).map((item) => ({
        item_name: item.item_name,
        item_group: item.item_group || null,
        result: item.result || '正常',
        remark: item.remark || '',
        images: item.images || [],
        pile_asset_code: item.pile_asset_code || null,
      })),
      images: payload.images || [],
      remark: payload.remark || '',
      checkin_location: checkin.location || null,
      checkin_lng: checkin.lng ?? null,
      checkin_lat: checkin.lat ?? null,
      checkout_location: checkout.location || null,
      checkout_lng: checkout.lng ?? null,
      checkout_lat: checkout.lat ?? null,
      finish: payload.finish !== false,
    },
  })
}

/** 巡检记录列表（按工单 / 只看我的 / 关键词） */
export function fetchInspections(params = {}) {
  return request({
    url: '/work-orders/inspections',
    method: 'GET',
    data: {
      work_order_id: params.workOrderId || undefined,
      station_id: params.stationId || undefined,
      keyword: params.keyword || undefined,
      mine: params.mine ? true : undefined,
      page: params.page || 1,
      page_size: params.pageSize || 20,
    },
  })
}

/** 某工单的巡检详情（含分类明细与照片） */
export function fetchOrderInspection(orderId) {
  return request({ url: `/work-orders/${orderId}/inspection` })
}

/* ================================================================== *
 * 故障（PDF 3.5：级联下拉、多图、草稿、核查）
 * ================================================================== */

/** 故障等级/状态字典 → { levels, statuses, verify_results, level_sla_hours, level_color } */
export function fetchFaultDicts() {
  return request({ url: '/faults/levels' })
}

/** 故障首页统计 → { total, verified, pending, rejected, verify_rate, cards } */
export function fetchFaultHome() {
  return request({ url: '/faults/home' })
}

/** 故障卡片（含 SLA 超期标记） */
export function fetchFaultCards(limit = 10) {
  return request({ url: '/faults/cards', method: 'GET', data: { limit } })
}

/**
 * 故障列表。
 * @param {object} [params]
 * @param {string} [params.tab]        全部 / 待核查 / 已核查
 * @param {string} [params.keyword]    故障编号/站点/桩资产码
 * @param {string} [params.faultLevel] 一般 / 严重 / 危急
 * @param {boolean} [params.mine]      只看我上报的
 */
export function fetchFaults(params = {}) {
  return request({
    url: '/faults',
    method: 'GET',
    data: {
      tab: params.tab === '全部' ? undefined : params.tab || undefined,
      keyword: params.keyword || undefined,
      fault_level: params.faultLevel || undefined,
      status: params.status || undefined,
      mine: params.mine ? true : undefined,
      page: params.page || 1,
      page_size: params.pageSize || 20,
    },
  })
}

/** 故障详情 → { fault, verifications, station, pile, sla_hours, permissions } */
export function fetchFault(faultId) {
  return request({ url: `/faults/${faultId}` })
}

/**
 * 上报故障（支持存草稿）。
 * @param {object} payload
 * @param {string} payload.projectId
 * @param {string} payload.stationId
 * @param {string} [payload.pileId]
 * @param {string} payload.faultType
 * @param {string} [payload.faultLevel]  不传则后端按描述关键词自动判定
 * @param {string} payload.description
 * @param {string[]} [payload.images]
 * @param {string} [payload.occurredAt]  发生时间 YYYY-MM-DD HH:mm:ss
 * @param {boolean} [payload.isDraft]
 */
export function reportFault(payload) {
  return requestFull({
    url: '/faults',
    method: 'POST',
    data: {
      project_id: payload.projectId || null,
      station_id: payload.stationId || null,
      pile_id: payload.pileId || null,
      fault_type: payload.faultType || null,
      fault_level: payload.faultLevel || null,
      description: payload.description || null,
      images: payload.images || [],
      occurred_at: payload.occurredAt || null,
      is_draft: !!payload.isDraft,
    },
  })
}

/** 草稿确认上报 */
export function confirmFault(faultId) {
  return requestFull({ url: `/faults/${faultId}/confirm`, method: 'POST' })
}

/**
 * 故障核查（PDF 3.5）。
 * @param {object} payload
 * @param {string} payload.verifyStatus 核查通过 / 核查驳回
 * @param {string} [payload.verifyLevel] 核查后等级
 * @param {string} payload.verifyDesc   核查描述（必填）
 * @param {string[]} [payload.images]
 * @param {boolean} [payload.needDefectOrder] 是否需要生成消缺工单
 */
export function verifyFault(faultId, payload) {
  return requestFull({
    url: `/faults/${faultId}/verify`,
    method: 'POST',
    data: {
      verify_status: payload.verifyStatus,
      verify_level: payload.verifyLevel || null,
      verify_desc: payload.verifyDesc,
      images: payload.images || [],
      need_defect_order: !!payload.needDefectOrder,
    },
  })
}

/** 充电桩下拉选项（级联联动：项目 → 站点 → 资产码；扫码查桩也用它） */
export function fetchPileOptions({ projectId, stationId, keyword } = {}) {
  return request({
    url: '/faults/piles/options',
    method: 'GET',
    data: {
      project_id: projectId || undefined,
      station_id: stationId || undefined,
      keyword: keyword || undefined,
    },
  })
}

/* ================================================================== *
 * 消息中心（PDF 3.8）
 * ================================================================== */

/**
 * 消息列表 → { items, meta, unread_count }
 * @param {object} [params]
 * @param {string} [params.msgType] 工单下发提醒 / 紧急工单提醒 / ... / 系统消息
 * @param {boolean} [params.isRead]
 */
export function fetchMessageList(params = {}) {
  return request({
    url: '/messages',
    method: 'GET',
    data: {
      msg_type: params.msgType || undefined,
      is_read: typeof params.isRead === 'boolean' ? params.isRead : undefined,
      keyword: params.keyword || undefined,
      page: params.page || 1,
      page_size: params.pageSize || 20,
    },
  })
}

/** 消息类型统计 → [{ type, total, unread }] */
export function fetchMessageTypes() {
  return request({ url: '/messages/types' })
}

/** 消息详情（后端会顺带标记已读） */
export function fetchMessage(messageId) {
  return request({ url: `/messages/${messageId}` })
}

/** 标记单条已读 */
export function markMessageRead(messageId) {
  return request({ url: `/messages/${messageId}/read`, method: 'POST' })
}

/** 全部标记已读 → { updated } */
export function markAllMessagesRead() {
  return request({ url: '/messages/read-all', method: 'POST' })
}

/* ================================================================== *
 * 统计看板（管理端）
 * ================================================================== */

/**
 * 统计看板（PDF 3.9）。
 * @param {object} [params]
 * @param {string} [params.period] day / week / month / quarter / year
 * @returns {Promise<object>} { period, work_order, order_type_dist, time_status_dist,
 *                              project_rank, defect_station_rank, trend, fault,
 *                              inspection, data_scope }
 */
export function fetchDashboard(params = {}) {
  return request({
    url: '/statistics/dashboard',
    method: 'GET',
    data: { period: params.period || 'month' },
  })
}

/** 排行榜（人员/站点工作量） */
export function fetchRankings(params = {}) {
  return request({
    url: '/statistics/rankings',
    method: 'GET',
    data: { period: params.period || 'month' },
  })
}

/* ================================================================== *
 * 台账 / 充电桩 / 基础选项
 * ================================================================== */

/** 充电桩台账列表 */
export function fetchPiles(params = {}) {
  return request({
    url: '/admin/piles',
    method: 'GET',
    data: {
      station_id: params.stationId || undefined,
      keyword: params.keyword || undefined,
      status: params.status || undefined,
      page: params.page || 1,
      page_size: params.pageSize || 20,
    },
  })
}

/** 充电桩状态汇总 → { status_dist: [{name,value}], gun_total } */
export function fetchPileStatusSummary() {
  return request({ url: '/admin/piles/status-summary' })
}

/** 项目下拉选项 */
export function fetchProjects() {
  return request({ url: '/admin/projects' })
}

/** 站点下拉选项 → [{ id, code, name, project_id, address, terrain }] */
export function fetchStationOptions() {
  return request({ url: '/admin/stations/options' })
}

/* ================================================================== *
 * AI Agent（现场辅助）
 * ================================================================== */

/** AI 健康检查（未配 Key 时会降级为规则引擎，仍可用） */
export function fetchAiHealth() {
  return request({ url: '/ai/health' })
}

/**
 * AI 故障诊断（PDF 3.11）—— 现场人员在报修前先问一句「这大概是什么问题、要不要停机」。
 * @param {object} payload
 * @param {string} [payload.faultType]
 * @param {string} [payload.faultLevel]
 * @param {string} [payload.description]
 * @param {string} [payload.pileAssetCode]
 * @param {string} [payload.stationId]
 * @param {string} [payload.faultId] 已有故障单时传，AI 会读历史
 */
export function aiDiagnoseFault(payload) {
  return requestFull({
    url: '/ai/fault/diagnose',
    method: 'POST',
    data: {
      fault_id: payload.faultId || null,
      fault_type: payload.faultType || null,
      fault_level: payload.faultLevel || null,
      description: payload.description || null,
      pile_asset_code: payload.pileAssetCode || null,
      station_id: payload.stationId || null,
    },
  })
}

/* ================================================================== *
 * 图片上传
 * ================================================================== */

/**
 * 逐张上传现场照片（PDF 3.4 / 3.5 多图上传）。
 *
 * ★ 为什么逐张而不是一次多张：现场是弱网，逐张能给出「第 2/3 张…」的进度，
 *   失败时只重传那一张，不会因为一张图让整批回滚。
 *
 * @param {object} options
 * @param {string[]} options.filePaths uni.chooseImage 返回的本地路径数组
 * @param {string} [options.bizType]   inspection / fault / verify / station
 * @param {function} [options.onProgress] (done, total) => void
 * @returns {Promise<{url:string,id:string}[]>}
 */
export async function uploadImages({ filePaths, bizType = 'inspection', bizId, onProgress } = {}) {
  const paths = (filePaths || []).filter(Boolean)
  const done = []
  for (let i = 0; i < paths.length; i += 1) {
    if (onProgress) onProgress(i, paths.length)
    // eslint-disable-next-line no-await-in-loop
    const file = await uploadImage({ filePath: paths[i], bizType, bizId })
    done.push(file)
  }
  if (onProgress) onProgress(paths.length, paths.length)
  return done
}

/**
 * 把后端返回的相对图片地址补成可直接显示的绝对地址。
 * ★ 小程序里 <image src> 必须是绝对地址：后端给的是 /static/data/uploads/...，
 *   不补前缀在微信端是一张空白图（H5 端因为走代理反而正常，极易漏测）。
 */
export function absoluteUrl(url) {
  if (!url) return ''
  if (/^https?:\/\//i.test(url)) return url
  return `${STATIC_BASE}${url}`
}

/** 批量补全（详情页的图片九宫格用） */
export function absoluteUrls(list) {
  return (list || []).filter(Boolean).map(absoluteUrl)
}
