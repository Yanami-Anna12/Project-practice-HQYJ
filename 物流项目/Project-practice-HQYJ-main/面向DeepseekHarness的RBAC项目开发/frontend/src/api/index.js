/**
 * 接口定义，按业务域分文件。
 * 每个函数的注释都标注了它对应的权限点，便于对照需求文档核对。
 */

import request, { rawRequest } from './request'

// ---------------------------------------------------------------------------
// 认证与当前用户
// ---------------------------------------------------------------------------

/**
 * 登录（公开接口）。
 * 返回 access_token 与 permissions —— permissions 仅供前端渲染界面使用。
 */
export function login(data) {
  return request.post('/api/auth/login', data)
}

/** 当前用户信息 */
export function fetchMe() {
  return request.get('/api/me')
}

/**
 * 当前用户的有效权限码（实时查库计算）。
 * @returns {Promise<{permissions: string[], roles: string[]}>}
 */
export function fetchMyPermissions() {
  return request.get('/api/me/permissions')
}

/**
 * 当前用户可见的菜单树。
 * ★ 后端已按权限裁剪，无权限的节点根本不会返回（验收标准 7）。
 */
export function fetchMyMenus() {
  return request.get('/api/me/menus')
}

// ---------------------------------------------------------------------------
// 权限点管理（users:manage）
// ---------------------------------------------------------------------------

export function fetchPermissions() {
  return request.get('/api/permissions')
}

export function createPermission(data) {
  return request.post('/api/permissions', data)
}

/**
 * 启用 / 停用权限点（★ R4 的操作入口）。
 * 停用后持有者下一次请求立即被拒，无需等待 Token 过期。
 */
export function togglePermission(id, isActive) {
  return request.patch(`/api/permissions/${id}`, { is_active: isActive })
}

// ---------------------------------------------------------------------------
// 角色管理（users:manage）
// ---------------------------------------------------------------------------

export function fetchRoles() {
  return request.get('/api/roles')
}

export function createRole(data) {
  return request.post('/api/roles', data)
}

/** 更新角色；permission_codes 为全量覆盖语义 */
export function updateRole(id, data) {
  return request.put(`/api/roles/${id}`, data)
}

/**
 * 删除角色。
 * ★ R3：若仍被用户引用会返回 409，并被 axios 拦截器弹出
 *   「该角色仍绑定 N 个用户，请先改绑」。
 */
export function deleteRole(id) {
  return request.delete(`/api/roles/${id}`)
}

export function fetchRolePermissions(id) {
  return request.get(`/api/roles/${id}/permissions`)
}

// ---------------------------------------------------------------------------
// 用户管理（users:manage）
// ---------------------------------------------------------------------------

export function fetchUsers() {
  return request.get('/api/users')
}

export function fetchUserRoles(id) {
  return request.get(`/api/users/${id}/roles`)
}

/**
 * 用户-角色分配（全量覆盖）。
 * ★ R1：传多个角色时权限为并集，返回值直接给出并集结果。
 */
export function setUserRoles(id, roleCodes) {
  return request.put(`/api/users/${id}/roles`, { role_codes: roleCodes })
}

// ---------------------------------------------------------------------------
// 业务接口
// ---------------------------------------------------------------------------

/** 需要 products:read */
export function fetchProducts() {
  return request.get('/api/products')
}

/** 需要 products:edit（供应商/只读访问会 403 —— 验收标准 2、3） */
export function createProduct(data) {
  return request.post('/api/products', data)
}

/** 需要 orders:read */
export function fetchOrders() {
  return request.get('/api/orders')
}

/** 需要 reports:view */
export function fetchReportSummary() {
  return request.get('/api/reports/summary')
}

/** 需要 users:manage（只读接口） */
export function fetchAuditLogs(params) {
  return request.get('/api/audit-logs', { params })
}

/**
 * R4 验证专用：请求指定接口并**只返回 HTTP 状态码**。
 *
 * 为什么不用上面的 api.fetchXxx()：
 *   默认实例的 axios 拦截器会把 4xx 转成 rejected promise 并弹错误提示。
 *   而这里我们恰恰要「观察 403 本身」，所以走不带拦截器的 rawRequest，
 *   从而拿到纯粹的状态码做停用前后的对比。
 *
 * @returns {Promise<number>} HTTP 状态码（200 / 403 ...）
 */
export async function probe(path) {
  const response = await rawRequest.get(path, { validateStatus: () => true })
  return response.status
}
