/**
 * 登录态与权限状态（Pinia）。
 *
 * ★ 关于 store 里 permissions 的定位（本项目最需要理解的一点）：
 *   它来自后端登录响应，保存在浏览器里，用户可以随意篡改。
 *   它**只**用于决定「菜单画几个、按钮显不显示」。
 *   任何真正的访问控制都在后端 authorize() 里完成。
 *   在控制台里把 permissions 改成全权限，按钮确实会出现，
 *   但点下去后端照样返回 403 —— 这是设计如此，不是漏洞。
 */

import { defineStore } from 'pinia'
import * as api from '@/api'
import {
  clearAuthStorage,
  getStoredMenus,
  getStoredUser,
  getToken,
  setStoredMenus,
  setStoredUser,
  setToken,
} from '@/utils/storage'

export const useAuthStore = defineStore('auth', {
  state: () => {
    const stored = getStoredUser() || {}
    return {
      token: getToken(),
      user: stored.user || null,
      roles: stored.roles || [],
      permissions: stored.permissions || [],
      menus: getStoredMenus() || [],
      // 菜单是否已从后端加载过（避免重复请求）
      menusLoaded: Boolean(getStoredMenus()),
    }
  },

  getters: {
    isLoggedIn: (state) => Boolean(state.token),
    username: (state) => state.user?.username || '',
    nickname: (state) => state.user?.nickname || state.user?.username || '',
    /** 权限集合，供 v-permission 指令与路由守卫使用（Set 查询是 O(1)） */
    permissionSet: (state) => new Set(state.permissions),
    /** 用户名首字母，用于头像占位 */
    avatarText: (state) => (state.user?.username || '?').charAt(0).toUpperCase(),
  },

  actions: {
    /**
     * 登录。
     * 响应中的 permissions 仅用于渲染界面 —— 后端不信任它，前端也不该把它当安全依据。
     */
    async login(username, password) {
      const data = await api.login({ username, password })
      this.token = data.access_token
      this.user = data.user
      this.roles = data.roles
      this.permissions = data.permissions

      setToken(data.access_token)
      setStoredUser({
        user: data.user,
        roles: data.roles,
        permissions: data.permissions,
      })

      // 登录后立刻取一次菜单（服务端已按权限裁剪好）
      await this.loadMenus()
      return data
    },

    /** 退出登录：清空内存与本地存储 */
    logout() {
      this.token = ''
      this.user = null
      this.roles = []
      this.permissions = []
      this.menus = []
      this.menusLoaded = false
      clearAuthStorage()
    },

    /** 拉取菜单树（后端已裁剪，前端直接渲染，不再二次过滤） */
    async loadMenus() {
      const menus = await api.fetchMyMenus()
      this.menus = menus
      this.menusLoaded = true
      setStoredMenus(menus)
      return menus
    },

    /**
     * 重新拉取权限集合。
     * 用于「管理员改了当前用户的角色/权限点后立刻刷新界面」的场景。
     * 平时不需要主动调用 —— 后端每次请求都会重新算权限。
     */
    async refreshPermissions() {
      const data = await api.fetchMyPermissions()
      this.permissions = data.permissions
      this.roles = data.roles
      setStoredUser({ user: this.user, roles: data.roles, permissions: data.permissions })
      await this.loadMenus()
      return data
    },

    /** 判断是否拥有某权限（仅用于界面显隐） */
    has(permissionCode) {
      if (!permissionCode) return true
      return this.permissionSet.has(permissionCode)
    },
  },
})
