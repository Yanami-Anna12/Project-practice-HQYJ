import axios from 'axios'
import { message } from 'ant-design-vue'

const http = axios.create({
  baseURL: '/api/v1',
  timeout: 180000,
})

// ---------------- 请求拦截：附带 JWT ----------------
http.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// ---------------- 响应拦截：统一拆包与错误提示 ----------------
http.interceptors.response.use(
  (response) => {
    const body = response.data
    // 二进制下载直接返回
    if (response.config.responseType === 'blob') return response
    if (body && typeof body === 'object' && 'code' in body) {
      if (body.code === 0) return body
      message.error(body.message || '请求失败')
      return Promise.reject(new Error(body.message || '请求失败'))
    }
    return body
  },
  (error) => {
    const status = error?.response?.status
    const detail = error?.response?.data?.message
    if (status === 401) {
      localStorage.removeItem('token')
      if (!location.hash.includes('/login')) {
        message.error(detail || '登录已过期，请重新登录')
        setTimeout(() => {
          location.hash = '#/login'
        }, 600)
      }
    } else if (status === 403) {
      message.error(detail || '无权访问该数据')
    } else if (status >= 500) {
      message.error(detail || '服务器异常，请查看后端日志')
    } else if (error.code === 'ECONNABORTED') {
      message.error('请求超时，请稍后重试')
    } else {
      message.error(detail || error.message || '网络异常')
    }
    return Promise.reject(error)
  },
)

export default http

// ================================================================ 认证
export const authApi = {
  login: (data) => http.post('/auth/login', data),
  wechatLogin: (data) => http.post('/auth/wechat-login', data),
  profile: () => http.get('/auth/profile'),
  updateProfile: (data) => http.put('/auth/profile', data),
  changePassword: (data) => http.post('/auth/change-password', data),
  logout: () => http.post('/auth/logout'),
}

// ================================================================ 工单
export const workOrderApi = {
  home: (params) => http.get('/work-orders/home', { params }),
  list: (params) => http.get('/work-orders', { params }),
  detail: (id) => http.get(`/work-orders/${id}`),
  create: (data) => http.post('/work-orders', data),
  update: (id, data) => http.put(`/work-orders/${id}`, data),
  accept: (id) => http.post(`/work-orders/${id}/accept`),
  reject: (id, data) => http.post(`/work-orders/${id}/reject`, data),
  cancel: (id, data) => http.post(`/work-orders/${id}/cancel`, data),
  redispatch: (id, data) => http.post(`/work-orders/${id}/redispatch`, data),
  subtasks: (id, params) => http.get(`/work-orders/${id}/subtasks`, { params }),
  mySubtasks: (params) => http.get('/work-orders/subtasks/mine', { params }),
  updateSubtask: (id, data) => http.put(`/work-orders/subtasks/${id}`, data),
  inspectionDetail: (id) => http.get(`/work-orders/${id}/inspection`),
  inspectionTemplate: (params) => http.get('/work-orders/inspections/template', { params }),
  createInspection: (data) => http.post('/work-orders/inspections', data),
  listInspections: (params) => http.get('/work-orders/inspections', { params }),
}

// ================================================================ 故障
export const faultApi = {
  dicts: () => http.get('/faults/levels'),
  home: (params) => http.get('/faults/home', { params }),
  cards: (params) => http.get('/faults/cards', { params }),
  statistics: (params) => http.get('/faults/statistics', { params }),
  pileOptions: (params) => http.get('/faults/piles/options', { params }),
  list: (params) => http.get('/faults', { params }),
  detail: (id) => http.get(`/faults/${id}`),
  report: (data) => http.post('/faults', data),
  confirm: (id) => http.post(`/faults/${id}/confirm`),
  verify: (id, data) => http.post(`/faults/${id}/verify`, data),
}

// ================================================================ 消息 / 统计
export const messageApi = {
  list: (params) => http.get('/messages', { params }),
  types: () => http.get('/messages/types'),
  detail: (id) => http.get(`/messages/${id}`),
  read: (id) => http.post(`/messages/${id}/read`),
  readAll: () => http.post('/messages/read-all'),
}

export const statisticsApi = {
  dashboard: (params) => http.get('/statistics/dashboard', { params }),
  trend: (params) => http.get('/statistics/trend', { params }),
  rankings: (params) => http.get('/statistics/rankings', { params }),
  buildDaily: (data) => http.post('/statistics/build-daily', data),
}

// ================================================================ 导出（任务式，带进度）
export const exportApi = {
  tasks: (params) => http.get('/exports/tasks', { params }),
  task: (id) => http.get(`/exports/tasks/${id}`),
  downloadUrl: (id) => `/api/v1/exports/tasks/${id}/download`,
  createWorkOrders: (data) => http.post('/exports/work-orders', data),
  createLedger: (data) => http.post('/exports/ledger', data),
  createStatistics: (data) => http.post('/exports/statistics', data),
  /** 轮询导出进度，返回最终任务对象 */
  poll: async (taskId, onProgress) => {
    for (let i = 0; i < 200; i += 1) {
      const res = await http.get(`/exports/tasks/${taskId}`)
      const task = res.data
      if (onProgress) onProgress(task)
      if (task.status === 'success' || task.status === 'failed') return task
      await new Promise((r) => setTimeout(r, 400))
    }
    throw new Error('导出超时')
  },
  /** 触发浏览器下载（带鉴权头） */
  download: async (taskId, fileName) => {
    const resp = await http.get(`/exports/tasks/${taskId}/download`, {
      responseType: 'blob',
    })
    const blob = new Blob([resp.data])
    const url = window.URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = fileName || 'export.xlsx'
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    window.URL.revokeObjectURL(url)
  },
}

// ================================================================ 附件上传
export const uploadApi = {
  info: () => http.get('/uploads/info'),
  /** 批量上传图片（巡检 / 故障 / 核查现场照片），返回 urls */
  uploadImages: (files, { bizType = 'inspection', bizId } = {}) => {
    const form = new FormData()
    files.forEach((f) => form.append('files', f))
    return http.post('/uploads/images', form, {
      params: { biz_type: bizType, biz_id: bizId },
      headers: { 'Content-Type': 'multipart/form-data' },
    })
  },
  uploadFiles: (files, { bizType = 'knowledge', bizId } = {}) => {
    const form = new FormData()
    files.forEach((f) => form.append('files', f))
    return http.post('/uploads/files', form, {
      params: { biz_type: bizType, biz_id: bizId },
      headers: { 'Content-Type': 'multipart/form-data' },
    })
  },
  attachments: (params) => http.get('/uploads/attachments', { params }),
}

// ================================================================ 管理后台
export const adminApi = {
  roles: (params) => http.get('/admin/roles', { params }),
  createRole: (data) => http.post('/admin/roles', data),
  updateRole: (id, data) => http.put(`/admin/roles/${id}`, data),
  deleteRole: (id) => http.delete(`/admin/roles/${id}`),
  rolePermissions: (id) => http.get(`/admin/roles/${id}/permissions`),
  permissions: () => http.get('/admin/permissions'),
  permissionTree: () => http.get('/admin/permissions/tree'),
  users: (params) => http.get('/admin/users', { params }),
  createUser: (data) => http.post('/admin/users', data),
  updateUser: (id, data) => http.put(`/admin/users/${id}`, data),
  deleteUser: (id) => http.delete(`/admin/users/${id}`),
  projects: () => http.get('/admin/projects'),
  stations: (params) => http.get('/admin/stations', { params }),
  stationOptions: (params) => http.get('/admin/stations/options', { params }),
  updateStationExtensions: (id, data) => http.put(`/admin/stations/${id}/extensions`, data),
  stationNavigation: (id) => http.get(`/admin/stations/${id}/navigation`),
  piles: (params) => http.get('/admin/piles', { params }),
  pileStatusSummary: () => http.get('/admin/piles/status-summary'),
  ledger: (params) => http.get('/admin/ledger', { params }),
  syncLedger: () => http.post('/admin/ledger/sync'),
  configs: (params) => http.get('/admin/configs', { params }),
  updateConfig: (key, data) => http.put(`/admin/configs/${key}`, data),
  rules: () => http.get('/admin/rules'),
  activeRule: () => http.get('/admin/rules/active'),
  operationLogs: (params) => http.get('/admin/logs/operations', { params }),
  loginLogs: (params) => http.get('/admin/logs/logins', { params }),
  shifts: (params) => http.get('/admin/shifts', { params }),
  upsertShift: (data) => http.post('/admin/shifts', data),
}

// ================================================================ AI Agent
export const aiApi = {
  health: () => http.get('/ai/health'),
  graph: () => http.get('/ai/graph'),
  center: () => http.get('/ai/agent/center'),

  generateWorkOrder: (data) => http.post('/ai/work-order/generate', data),
  diagnoseFault: (data) => http.post('/ai/fault/diagnose', data),
  inspectionReport: (data) => http.post('/ai/inspection/report', data),
  maintenanceSuggest: (data) => http.post('/ai/maintenance/suggest', data),
  riskCheck: (data) => http.post('/ai/risk/check', data),
  dataAnalysis: (data) => http.post('/ai/data-analysis', data),
  assistantAsk: (data) => http.post('/ai/assistant/ask', data),

  taskList: (params) => http.get('/ai/agent/tasks', { params }),
  taskState: (id) => http.get(`/ai/agent/tasks/${id}`),
  confirmTask: (id, data) => http.post(`/ai/agent/tasks/${id}/confirm`, data),
  replanTask: (id, data) => http.post(`/ai/agent/tasks/${id}/replan`, data),

  exceptions: (params) => http.get('/ai/exceptions', { params }),
  scanExceptions: () => http.post('/ai/exceptions/scan'),

  knowledgeList: (params) => http.get('/ai/knowledge', { params }),
  knowledgeCreate: (data) => http.post('/ai/knowledge', data),
  knowledgeCategories: () => http.get('/ai/knowledge/categories'),
  knowledgeAsk: (data) => http.post('/ai/knowledge/ask', data),

  reportGenerate: (data) => http.post('/ai/report/generate', data),
  reportList: (params) => http.get('/ai/report/list', { params }),
  reportDetail: (id) => http.get(`/ai/report/${id}`),
  reportFollowUp: (id, data) => http.post(`/ai/report/${id}/follow-up`, data),
  reportCompare: (type, params) => http.get(`/ai/report/compare/${type}`, { params }),
  reportPush: (id, data) => http.post(`/ai/report/${id}/push`, data),

  feedback: (data) => http.post('/ai/feedback', data),
  feedbackStats: () => http.get('/ai/feedback/stats'),
  jobs: () => http.get('/ai/jobs'),
  runJob: (code) => http.post(`/ai/jobs/${code}/run`),
}

/** 轮询 Agent 任务直到进入终止状态 */
export async function pollAgentTask(taskId, onTick, { interval = 1000, maxTry = 180 } = {}) {
  const terminal = ['waiting_confirmation', 'failed', 'completed', 'dispatched', 'cancelled']
  for (let i = 0; i < maxTry; i += 1) {
    const res = await aiApi.taskState(taskId)
    const state = res.data
    if (onTick) onTick(state)
    if (terminal.includes(state?.task?.status)) return state
    await new Promise((r) => setTimeout(r, interval))
  }
  throw new Error('Agent 任务轮询超时')
}

/** 打开 Agent 任务进度 WebSocket */
export function openTaskSocket(taskId, onMessage) {
  const token = localStorage.getItem('token')
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  const url = `${proto}://${location.host}/api/v1/ws/agent/tasks/${taskId}?token=${token}`
  const ws = new WebSocket(url)
  ws.onmessage = (evt) => {
    try {
      onMessage(JSON.parse(evt.data))
    } catch {
      /* 忽略非 JSON 消息 */
    }
  }
  return ws
}
