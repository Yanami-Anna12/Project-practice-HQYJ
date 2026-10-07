/**
 * 数据访问层 —— 调用 FastAPI 后端。
 *
 * ★ 页面组件与 store 只 import 本模块，不直接碰 axios，
 *   所以「换数据来源」只影响这一个文件（首版是 mock，现在是真实后端）。
 *
 * 所有接口路径与 backend/app/routers/ 一一对应。
 */

import request from './request'

/* ------------------------------------------------------------------ *
 * 认证
 * ------------------------------------------------------------------ */

export async function login({ username, password }) {
  const data = await request.post('/api/auth/login', { username, password })
  return { token: data.token, user: data.user }
}

export async function logout() {
  return request.post('/api/auth/logout')
}

export async function fetchMe() {
  return request.get('/api/me')
}

export async function fetchMenus() {
  return request.get('/api/me/menus')
}

/* ------------------------------------------------------------------ *
 * 用户管理
 * ------------------------------------------------------------------ */

export async function fetchUsers() {
  return request.get('/api/users')
}

export async function setUserRoles(id, roleCodes) {
  return request.put(`/api/users/${id}/roles`, { roles: roleCodes })
}

export async function toggleUserActive(id) {
  return request.put(`/api/users/${id}/active`)
}

export async function resetUserPassword(id) {
  return request.post(`/api/users/${id}/reset-password`)
}

/* ------------------------------------------------------------------ *
 * 角色管理
 * ------------------------------------------------------------------ */

export async function fetchRoles() {
  return request.get('/api/roles')
}

export async function createRole({ code, name, description, permission_codes }) {
  return request.post('/api/roles', { code, name, description, permission_codes })
}

export async function updateRole(id, { name, description, permission_codes, is_active }) {
  return request.put(`/api/roles/${id}`, { name, description, permission_codes, is_active })
}

export async function deleteRole(id) {
  return request.delete(`/api/roles/${id}`)
}

/* ------------------------------------------------------------------ *
 * 权限点管理
 * ------------------------------------------------------------------ */

export async function fetchPermissions() {
  return request.get('/api/permissions')
}

export async function createPermission({ code, name, module, action }) {
  return request.post('/api/permissions', { code, name, module, action })
}

export async function togglePermission(id) {
  return request.put(`/api/permissions/${id}/active`)
}

export async function deletePermission(id) {
  return request.delete(`/api/permissions/${id}`)
}

/* ------------------------------------------------------------------ *
 * 字典管理
 * ------------------------------------------------------------------ */

export async function fetchDictTypes() {
  return request.get('/api/dicts/types')
}

export async function fetchDictItems(typeCode) {
  return request.get(`/api/dicts/types/${typeCode}/items`)
}

export async function createDictType({ code, name, description }) {
  return request.post('/api/dicts/types', { code, name, description })
}

export async function toggleDictType(id) {
  return request.put(`/api/dicts/types/${id}/active`)
}

export async function deleteDictType(id) {
  return request.delete(`/api/dicts/types/${id}`)
}

export async function createDictItem({ type_code, label, value, sort, remark }) {
  return request.post(`/api/dicts/types/${type_code}/items`, { label, value, sort, remark })
}

export async function updateDictItem(id, { label, value, sort, remark, is_active }) {
  return request.put(`/api/dicts/items/${id}`, { label, value, sort, remark, is_active })
}

export async function deleteDictItem(id) {
  return request.delete(`/api/dicts/items/${id}`)
}

/* ------------------------------------------------------------------ *
 * 参数管理
 * ------------------------------------------------------------------ */

export async function fetchParams() {
  return request.get('/api/params')
}

export async function updateParam(id, { value }) {
  return request.put(`/api/params/${id}`, { value })
}

export async function toggleParam(id) {
  return request.put(`/api/params/${id}/active`)
}

/* ------------------------------------------------------------------ *
 * 附件管理
 * ------------------------------------------------------------------ */

export async function fetchAttachments({ keyword = '', biz_type = '' } = {}) {
  return request.get('/api/attachments', { params: { keyword, biz_type } })
}

/**
 * 演示模式：只登记元信息，后端不做真实文件落盘。
 * 接真实上传时改为 FormData + POST /api/attachments。
 */
export async function registerAttachment({ name, biz_type, size }) {
  return request.post('/api/attachments', { name, biz_type, size })
}

export async function deleteAttachment(id) {
  return request.delete(`/api/attachments/${id}`)
}

/* ------------------------------------------------------------------ *
 * 审计日志（只读）
 * ------------------------------------------------------------------ */

export async function fetchAuditLogs({ action = '', target_type = '', limit = 200 } = {}) {
  return request.get('/api/audit-logs', { params: { action, target_type, limit } })
}

export async function fetchAuditActions() {
  return request.get('/api/audit-logs/actions')
}

/* ------------------------------------------------------------------ *
 * 业务基础数据
 * ------------------------------------------------------------------ */

// 门店
export async function fetchStores() {
  return request.get('/api/stores')
}
export async function createStore(payload) {
  return request.post('/api/stores', payload)
}
export async function updateStore(id, payload) {
  return request.put(`/api/stores/${id}`, payload)
}
export async function deleteStore(id) {
  return request.delete(`/api/stores/${id}`)
}

// 线路
export async function fetchRoutes() {
  return request.get('/api/routes')
}
export async function createRoute(payload) {
  return request.post('/api/routes', payload)
}
export async function updateRoute(id, payload) {
  return request.put(`/api/routes/${id}`, payload)
}
export async function deleteRoute(id) {
  return request.delete(`/api/routes/${id}`)
}

// 门店线路映射
export async function fetchMappings() {
  return request.get('/api/mappings')
}
export async function createMapping(payload) {
  return request.post('/api/mappings', payload)
}
export async function deleteMapping(id) {
  return request.delete(`/api/mappings/${id}`)
}

// 车辆类型
export async function fetchVehicleTypes() {
  return request.get('/api/vehicle-types')
}
export async function updateVehicleType(id, payload) {
  return request.put(`/api/vehicle-types/${id}`, payload)
}

// 车辆
export async function fetchVehicles() {
  return request.get('/api/vehicles')
}
export async function createVehicle(payload) {
  return request.post('/api/vehicles', payload)
}
export async function updateVehicle(id, payload) {
  return request.put(`/api/vehicles/${id}`, payload)
}
export async function deleteVehicle(id) {
  return request.delete(`/api/vehicles/${id}`)
}

// 司机
export async function fetchDrivers() {
  return request.get('/api/drivers')
}
export async function createDriver(payload) {
  return request.post('/api/drivers', payload)
}
export async function updateDriver(id, payload) {
  return request.put(`/api/drivers/${id}`, payload)
}
export async function deleteDriver(id) {
  return request.delete(`/api/drivers/${id}`)
}

// 地形规则与通行矩阵
export async function fetchTerrainRules() {
  return request.get('/api/terrain-rules')
}
export async function fetchTerrainMatrix() {
  return request.get('/api/terrain-matrix')
}
export async function updateTerrainMatrix(id, payload) {
  return request.put(`/api/terrain-matrix/${id}`, payload)
}

/* ------------------------------------------------------------------ *
 * 门店货量需求（调度的输入）
 * ------------------------------------------------------------------ */

export async function fetchDemands(scheduleDate) {
  return request.get('/api/demands', { params: { schedule_date: scheduleDate } })
}

export async function fetchDemandSummary(scheduleDate) {
  return request.get('/api/demands/summary', { params: { schedule_date: scheduleDate } })
}

export async function upsertDemand(payload) {
  return request.put('/api/demands', payload)
}

export async function generateDemands({ schedule_date, overwrite = false }) {
  return request.post('/api/demands/generate', { schedule_date, overwrite })
}

export async function deleteDemand(id) {
  return request.delete(`/api/demands/${id}`)
}

/* ------------------------------------------------------------------ *
 * 智能调度
 * ------------------------------------------------------------------ */

export async function fetchFeasibility(scheduleDate, timeWindow = 'FULL') {
  return request.get('/api/scheduling/feasibility', {
    params: { schedule_date: scheduleDate, time_window: timeWindow },
  })
}

export async function createSchedulingTask(payload) {
  return request.post('/api/scheduling/tasks', payload)
}

export async function fetchSchedulingTasks(limit = 50) {
  return request.get('/api/scheduling/tasks', { params: { limit } })
}

export async function fetchSchedulingTask(taskId) {
  return request.get(`/api/scheduling/tasks/${taskId}`)
}

export async function fetchPlanDetails(planId) {
  return request.get(`/api/scheduling/plans/${planId}/details`)
}

export async function confirmPlan(taskId, payload) {
  return request.post(`/api/scheduling/tasks/${taskId}/confirm`, payload)
}

export async function dispatchPlan(taskId, planId) {
  return request.post(`/api/scheduling/tasks/${taskId}/dispatch`, null, {
    params: { plan_id: planId },
  })
}

export async function fetchExceptions(taskId) {
  return request.get('/api/scheduling/exceptions', {
    params: taskId ? { task_id: taskId } : {},
  })
}

export async function createException(payload) {
  return request.post('/api/scheduling/exceptions', payload)
}

export async function replanTask(taskId, { eventId = null, scope = 'local' } = {}) {
  return request.post(`/api/scheduling/tasks/${taskId}/replan`, null, {
    params: { event_id: eventId, scope },
  })
}

export async function fetchTaskReport(taskId) {
  return request.get(`/api/scheduling/tasks/${taskId}/report`)
}

/* ------------------------------------------------------------------ *
 * 报表与看板
 * ------------------------------------------------------------------ */

export async function fetchReportDates() {
  return request.get('/api/reports/dates')
}

/** 一次拿到全部报表数据，避免前端串行等待 5 个请求 */
export async function fetchReportOverview(scheduleDate) {
  return request.get('/api/reports/overview', {
    params: scheduleDate ? { schedule_date: scheduleDate } : {},
  })
}

export async function fetchAttendanceReport(scheduleDate) {
  return request.get('/api/reports/attendance', {
    params: scheduleDate ? { schedule_date: scheduleDate } : {},
  })
}

export async function fetchTripReport(scheduleDate) {
  return request.get('/api/reports/trip-achievement', {
    params: scheduleDate ? { schedule_date: scheduleDate } : {},
  })
}

export async function fetchLoadRateReport(scheduleDate) {
  return request.get('/api/reports/load-rate', {
    params: scheduleDate ? { schedule_date: scheduleDate } : {},
  })
}

export async function fetchStoreReport(scheduleDate) {
  return request.get('/api/reports/store', {
    params: scheduleDate ? { schedule_date: scheduleDate } : {},
  })
}

export async function fetchCostReport(scheduleDate) {
  return request.get('/api/reports/cost', {
    params: scheduleDate ? { schedule_date: scheduleDate } : {},
  })
}

/* ------------------------------------------------------------------ *
 * 调度规则配置
 * ------------------------------------------------------------------ */

export async function fetchRulesOverview() {
  return request.get('/api/rules/overview')
}

export async function fetchRuleConflicts() {
  return request.get('/api/rules/conflicts')
}

export async function fetchRuleVersions() {
  return request.get('/api/rules/versions')
}

export async function fetchRuleVersion(id) {
  return request.get(`/api/rules/versions/${id}`)
}

export async function publishRuleVersion({ version = null, description = '' }) {
  return request.post('/api/rules/versions', { version, description })
}

export async function rollbackRuleVersion(id) {
  return request.post(`/api/rules/versions/${id}/rollback`)
}

/* ------------------------------------------------------------------ *
 * 集成与监控
 * ------------------------------------------------------------------ */

export async function fetchMonitorSystem() {
  return request.get('/api/monitor/system')
}

export async function fetchMonitorAlerts() {
  return request.get('/api/monitor/alerts')
}

export async function fetchMonitorDashboard(days = 7) {
  return request.get('/api/monitor/dashboard', { params: { days } })
}

export async function fetchIntegrations() {
  return request.get('/api/monitor/integrations')
}

export async function fetchDataPlatform() {
  return request.get('/api/monitor/data-platform')
}
