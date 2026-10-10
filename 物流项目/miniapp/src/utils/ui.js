/**
 * 页面级的小工具：底部导航的条目与红点、按角色分流、登录校验。
 *
 * ★ 单独放一个文件是因为「未读红点」在趟次首页、消息页、我的页面都要刷新，
 *   口径必须一致，散落三处很容易改漏一个；
 *   「按角色进哪个首页 / 底部导航显示哪几项」同理，必须只有一个答案。
 */

import { ref } from 'vue'

import { clearAuthStorage, getStoredUser, getToken } from './storage'

/* ------------------------------------------------------------------ *
 * 角色分流（司机端 vs 管理端只读看板）
 * ------------------------------------------------------------------ */

/** 调度查看权限点：有它就能看管理端看板（与网页端 /api/scheduling/* 同一口径） */
export const SCHEDULING_READ = 'scheduling:read'
/** 司机端准入权限点 */
export const MOBILE_USE = 'mobile:use'

/**
 * 账号画像：从登录接口存下来的 user 对象推导「这个账号能用哪些页面」。
 *
 * ★ 为什么用**权限点**而不是角色码判断：
 *   角色是可配置的（后台能改角色权限），写死 'dispatcher' 这种角色码，
 *   一旦有人新建了「调度主管」角色就会漏判。权限点是后端的最终判定依据
 *   （见 app/deps.py 的 require_permission），前端按同一依据分流，
 *   才不会出现「前端放进去、后端 403」的页面。
 *
 * @param {object} [user] 登录接口返回的 user（缺省时读本地缓存）
 */
export function accountProfile(user) {
  const account = user || getStoredUser() || {}
  const roles = account.roles || []
  const permissions = account.permissions || []
  const hasMobile = permissions.indexOf(MOBILE_USE) >= 0
  const hasDriverRole = roles.indexOf('driver') >= 0
  const canViewBoard = permissions.indexOf(SCHEDULING_READ) >= 0
  /**
   * ★ 司机身份的判定顺序很重要（实测踩过）：
   *   管理员角色的权限是 `*`，后端展开后**包含** mobile:use（见 seed.py 的 ROLES）。
   *   如果只看权限点，admin 就会被当成司机、登录后进「我的趟次」，
   *   而它名下根本没有车 —— 页面只会显示「未绑定司机档案」。
   *   所以：**先看角色码里有没有 driver**，有 driver 角色才是司机；
   *   没有 driver 角色但持有 mobile:use（理论上不该出现）才退回权限点判断。
   */
  const isDriver = hasDriverRole || (hasMobile && !roles.length)
  return {
    user: account,
    roles,
    permissions,
    isDriver,
    canViewBoard,
    /**
     * 登录后的落地页。
     * ★ 多角色账号（如 multi = 调度员 + 只读观察者）走 canViewBoard → 看板；
     *   一个账号同时有 driver 与其他角色时**司机优先**：能干活的身份优先
     *   （司机有具体的趟次要跑，看板只是「了解情况」）。
     */
    home: isDriver ? '/pages/trips/index' : canViewBoard ? '/pages/board/index' : '',
  }
}

/** 当前账号的首页（未登录返回空串） */
export function homePathFor(user) {
  return accountProfile(user).home
}

/* ------------------------------------------------------------------ *
 * 底部导航：按角色渲染不同的一组条目
 * ------------------------------------------------------------------ *
 * ★ 为什么不用 pages.json 的 tabBar（本次改造的核心决定）：
 *   小程序 tabBar 是**静态配置** —— 条目的数量与 pagePath 在编译期就定死，
 *   运行时既不能增删条目，也不能可靠地改 pagePath（微信基础库忽略该字段），
 *   uni.setTabBarItem 只能改文字。
 *   上一轮因此把两种角色硬塞进同一组固定位置，结果：
 *     司机看到「趟次 / 消息 / 消息 / 看板 / 我的」——多出一个没权限的「看板」；
 *     管理者看到「看板 / 看板 / 任务 / 看板 / 我的」——「看板」重复三次。
 *   用户的原话是「这个没有权限的页面能不显示吗，很怪」。
 *
 *   所以：**删掉 pages.json 的 tabBar，自己画一个 BottomNav 组件**。
 *   条目按角色动态生成，不存在的入口根本不出现；H5 与微信小程序行为一致
 *   （原生「自定义 tabBar」在 H5 上不可靠，所以不用它）。
 *
 * ★ 代价：这些页面不再是 tabBar 页面，`uni.switchTab` 会失效，
 *   跳转必须一律用 `uni.redirectTo`（保栈深度 1，避免越点越深）。
 * ------------------------------------------------------------------ */

/**
 * 当前角色的底部导航条目。
 *
 *   司机        → 趟次 / 消息 / 我的
 *   调度·管理员 → 看板 / 任务 / 消息 / 我的
 *   两者都不是  → 空数组（不渲染导航，登录页已挡住这类账号）
 *
 * ★ 「我的」在两种角色下都排最后：同一个页面，位置一致才不会出现
 *   「换个账号登录，退出按钮跑到别处去了」。
 * ★ 管理者的「消息」是可用的：站内消息接口只要求登录
 *   （见 backend/app/routers/mobile.py 的「例外二」），
 *   「司机已确认接单」这类通知正是发给调度角色的。
 *
 * @param {object} [user] 登录接口返回的 user（缺省时读本地缓存）
 * @returns {{key: string, text: string, path: string}[]}
 */
export function roleTabs(user) {
  const profile = accountProfile(user)
  if (profile.isDriver) {
    return [
      { key: 'trips', text: '趟次', path: '/pages/trips/index' },
      { key: 'messages', text: '消息', path: '/pages/messages/index' },
      { key: 'profile', text: '我的', path: '/pages/profile/index' },
    ]
  }
  if (profile.canViewBoard) {
    return [
      { key: 'board', text: '看板', path: '/pages/board/index' },
      { key: 'tasks', text: '任务', path: '/pages/board/tasks' },
      { key: 'messages', text: '消息', path: '/pages/messages/index' },
      { key: 'profile', text: '我的', path: '/pages/profile/index' },
    ]
  }
  return []
}

/* ------------------------------------------------------------------ *
 * 未读数（模块级响应式，供 BottomNav 显示红点）
 * ------------------------------------------------------------------ *
 * ★ 为什么放在模块级而不是组件里：趟次首页、消息页、App.vue 的实时推送
 *   都要更新它，底部导航是**另一个组件**。放模块级就只有一个真相来源，
 *   不用 prop 层层传递，也不会出现「两个页面各算一份、数字不一样」。
 * ★ 这里只存数字，不在这里发请求 —— 谁有数据谁调用 setUnread()。
 */

/** 当前未读消息数（响应式） */
export const unreadCount = ref(0)

/** 更新未读数（负数按 0 处理，展示用 99+ 由组件决定） */
export function setUnread(count) {
  const safe = Number(count) || 0
  unreadCount.value = safe > 0 ? safe : 0
}

/**
 * 从实时推送报文里取出「发给当前账号的未读数」。
 *
 * 后端一般直接带 `unread`；但**撤回下发**这类「一次影响多个司机」的报文
 * 带的是 `unread_by_user`（user_id → 未读数），因为每个司机的消息条数不同，
 * 一个数字说不清。这里统一取一次，页面不用各自判断。
 *
 * @returns {number|null} null 表示报文里没有未读数，调用方应自己去查一次
 */
export function unreadFromPayload(payload) {
  if (!payload || typeof payload !== 'object') return null
  if (typeof payload.unread === 'number') return payload.unread

  const byUser = payload.unread_by_user
  if (byUser && typeof byUser === 'object') {
    const me = getStoredUser()
    const userId = me && (me.id ?? me.user_id)
    if (userId !== undefined && userId !== null) {
      const mine = byUser[userId] ?? byUser[String(userId)]
      if (typeof mine === 'number') return mine
    }
  }
  return null
}

/* ------------------------------------------------------------------ *
 * 登录校验
 * ------------------------------------------------------------------ */

/**
 * 页面级登录校验：没有 token 就跳登录页。
 *
 * @returns {boolean} true 表示已登录，可以继续加载数据
 */
export function requireLogin() {
  if (getToken()) return true
  clearAuthStorage()
  uni.reLaunch({ url: '/pages/login/login' })
  return false
}
