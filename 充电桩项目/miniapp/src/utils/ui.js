/**
 * 页面级的小工具：按角色分流、底部导航条目、未读红点、登录校验。
 *
 * ★ 单独放一个文件是因为「未读红点」在工作台、消息页、我的页面都要刷新，
 *   口径必须一致，散落三处很容易改漏一个；
 *   「按角色进哪个首页 / 底部导航显示哪几项」同理，必须只有一个答案。
 */

import { ref } from 'vue'

import { getStoredProfile, getStoredUser, getToken, clearAuthStorage } from './storage'

/* ------------------------------------------------------------------ *
 * 角色分流（现场作业端 vs 管理端）
 * ------------------------------------------------------------------ *
 * ★ 判定依据用**数据权限**（data_scope），不用角色码：
 *   角色是可配置的（后台能新建角色、改权限），写死 'inspector' 这种角色码，
 *   一旦有人新建了「外委运维」角色就会漏判。
 *   数据权限是后端做数据过滤的最终依据（见 app/core/deps.py 的 apply_data_scope），
 *   前端按同一依据分流，才不会出现「前端放进去、后端只返回空列表」的页面。
 *
 *   个人数据  → 现场作业端（运维人员：接单、巡检录入、故障上报）
 *   站点/项目/平台数据 → 管理端（掌上看板、工单、充电桩状态）
 * ------------------------------------------------------------------ */

/** 现场作业端的数据权限 */
export const FIELD_SCOPE = '个人数据'

/** 权限点常量（与 seed.py 里的权限码一一对应） */
export const PERM = {
  TASK: 'task',
  WORK_ORDER: 'work_order',
  ACCEPT: 'work_order:accept',
  CANCEL: 'work_order:cancel',
  CREATE_ORDER: 'work_order:create',
  INSPECT: 'work_order:inspect',
  FAULT: 'fault',
  FAULT_REPORT: 'fault:report',
  FAULT_VERIFY: 'fault:verify',
  STATISTICS: 'statistics',
  LEDGER: 'ledger',
  MESSAGE: 'message',
  AI_FAULT: 'ai:fault',
  SYSTEM_USER: 'system:user',
}

/**
 * 账号画像：从登录接口存下来的 user + /auth/profile 存下来的权限推导
 * 「这个账号能用哪些页面、能点哪些按钮」。
 *
 * @param {object} [user] 登录接口返回的 user（缺省时读本地缓存）
 */
export function accountProfile(user) {
  const account = user || getStoredUser() || {}
  const profile = getStoredProfile()
  const permissions = profile.permissions || []
  const role = account.role || profile.role || null
  const dataScope = account.data_scope || (role && role.data_scope) || ''

  const has = (code) => permissions.indexOf(code) >= 0

  /** 现场作业端：只有个人数据权限的账号（运维人员） */
  const isField = dataScope === FIELD_SCOPE
  /** 管理端：站点/项目/平台数据权限 */
  const isManager = !isField && permissions.length > 0

  return {
    user: account,
    role,
    dataScope,
    permissions,
    isField,
    isManager,
    /** 巡检录入（现场作业端核心动作） */
    canInspect: has(PERM.INSPECT),
    /** 接受 / 退回工单 */
    canAccept: has(PERM.ACCEPT),
    canCancel: has(PERM.CANCEL),
    /** 创建工单（管理端） */
    canCreateOrder: has(PERM.CREATE_ORDER),
    /** 故障上报 */
    canReportFault: has(PERM.FAULT_REPORT) || isField || isManager,
    /** 故障核查（站点管理员及以上） */
    canVerifyFault: has(PERM.FAULT_VERIFY),
    /** 看统计看板 */
    canViewBoard: has(PERM.STATISTICS) || isManager,
    /** 看充电桩台账 */
    canViewPiles: has(PERM.LEDGER) || isManager,
    /** 看工单列表 */
    canViewOrders: has(PERM.WORK_ORDER) || isField,
    /** 系统管理（用户/角色），小程序端不开放入口，仅用于「我的」页展示身份 */
    isSystemAdmin: has(PERM.SYSTEM_USER),
    /**
     * 登录后的落地页。
     * ★ 现场人员进「工作台」（今天要跑哪几个站、几个桩），
     *   管理人员进「掌上看板」（今天工单/故障/巡检的整体情况）——
     *   两类人一进来最想看到的东西不一样。
     */
    home: isField ? '/pages/home/index' : isManager ? '/pages/board/index' : '/pages/home/index',
  }
}

/** 当前账号的首页（未登录返回空串） */
export function homePathFor(user) {
  return accountProfile(user).home
}

/* ------------------------------------------------------------------ *
 * 底部导航：按角色渲染不同的一组条目
 * ------------------------------------------------------------------ *
 * ★ 为什么不用 pages.json 的 tabBar：
 *   小程序 tabBar 是**静态配置** —— 条目的数量与 pagePath 在编译期就定死，
 *   运行时既不能增删条目，也不能可靠地改 pagePath（微信基础库忽略该字段）。
 *   而且这里有两类角色（现场作业端 / 管理端），硬塞进同一组固定位置就会出现
 *   「运维人员看到一个点进去空空的看板」这种页面 —— 用户的原话是
 *   「这个没有权限的页面能不显示吗，很怪」。
 *   所以：**删掉 pages.json 的 tabBar，自己画一个 BottomNav 组件**。
 *
 * ★ 代价：这些页面不再是 tabBar 页面，`uni.switchTab` 会失效，
 *   跳转必须一律用 `uni.redirectTo`（保栈深度 1，避免越点越深）。
 * ------------------------------------------------------------------ */

/**
 * 当前角色的底部导航条目。
 *
 *   现场作业端（个人数据） → 工作台 / 任务 / 故障 / 消息 / 我的
 *   管理端（站点·项目·平台）→ 看板 / 工单 / 故障 / 消息 / 我的
 *
 * ★ 「我的」在两种角色下都排最后：同一个页面，位置一致才不会出现
 *   「换个账号登录，退出按钮跑到别处去了」。
 *
 * @param {object} [user] 登录接口返回的 user（缺省时读本地缓存）
 * @returns {{key: string, text: string, path: string}[]}
 */
export function roleTabs(user) {
  const profile = accountProfile(user)
  const tail = [
    { key: 'messages', text: '消息', path: '/pages/messages/index' },
    { key: 'profile', text: '我的', path: '/pages/profile/index' },
  ]

  if (profile.isField) {
    return [
      { key: 'home', text: '工作台', path: '/pages/home/index' },
      { key: 'tasks', text: '任务', path: '/pages/tasks/index' },
      { key: 'fault', text: '故障', path: '/pages/fault/index' },
      ...tail,
    ]
  }

  if (profile.isManager) {
    return [
      { key: 'board', text: '看板', path: '/pages/board/index' },
      { key: 'orders', text: '工单', path: '/pages/board/orders' },
      { key: 'fault', text: '故障', path: '/pages/fault/index' },
      ...tail,
    ]
  }

  return []
}

/* ------------------------------------------------------------------ *
 * 未读数（模块级响应式，供 BottomNav 显示红点）
 * ------------------------------------------------------------------ *
 * ★ 为什么放在模块级而不是组件里：工作台、消息页、App.vue 的实时推送
 *   都要更新它，底部导航是**另一个组件**。放模块级就只有一个真相来源，
 *   不用 prop 层层传递，也不会出现「两个页面各算一份、数字不一样」。
 * ------------------------------------------------------------------ */

/** 当前未读消息数（响应式） */
export const unreadCount = ref(0)

/** 更新未读数（负数按 0 处理，展示用 99+ 由组件决定） */
export function setUnread(count) {
  const safe = Number(count) || 0
  unreadCount.value = safe > 0 ? safe : 0
}

/**
 * 从实时推送报文里取出未读数。
 * 后端报文字段是 `unread_count`（见 app/api/ws.py），不是 `unread`；
 * 这里两者都认，避免以后后端改名时前端静默失效。
 *
 * @returns {number|null} null 表示报文里没有未读数，调用方应自己去查一次
 */
export function unreadFromPayload(payload) {
  if (!payload || typeof payload !== 'object') return null
  if (typeof payload.unread_count === 'number') return payload.unread_count
  if (typeof payload.unread === 'number') return payload.unread
  return null
}

/* ------------------------------------------------------------------ *
 * 登录校验
 * ------------------------------------------------------------------ */

/**
 * 页面级登录校验：没有 token 就跳登录页。
 * @returns {boolean} true 表示已登录，可以继续加载数据
 */
export function requireLogin() {
  if (getToken()) return true
  clearAuthStorage()
  uni.reLaunch({ url: '/pages/login/login' })
  return false
}

/**
 * 统一的错误提示：把 err 变成一句人话。
 * ★ 现场人员在弱网下最需要知道的是「刚才那一下到底成没成」，
 *   所以网络不通（code 0）与业务失败（code 4xx）的文案必须分开。
 */
export function errorText(err, fallback = '操作失败') {
  if (!err) return fallback
  if (err.code === 0) return '网络不通，操作可能未提交成功，请重试'
  if (err.code === 401) return '登录已失效，请重新登录'
  if (err.code === 403) return '当前账号没有该操作的权限'
  return err.message || fallback
}
