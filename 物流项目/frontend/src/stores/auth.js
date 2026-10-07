/**
 * 登录态与权限的集中管理。
 */

import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import * as api from '@/api'
import { clearAuthStorage, getStoredUser, setStoredUser, setToken } from '@/utils/storage'

export const useAuthStore = defineStore('auth', () => {
  const user = ref(getStoredUser())
  /** 菜单树只放内存，不持久化 —— 见 loadMenus 的说明 */
  const menus = ref([])
  const menusLoaded = ref(false)

  const isLoggedIn = computed(() => !!user.value)

  /** 当前用户的有效权限（多角色并集） */
  const permissions = computed(() => user.value?.permissions || [])

  const roleNames = computed(() => user.value?.role_names || [])

  /** 是否拥有某个权限点，用于路由守卫与按钮显隐 */
  function has(code) {
    if (!code) return true
    return permissions.value.includes(code)
  }

  async function login(payload) {
    const res = await api.login(payload)
    setToken(res.token)
    setStoredUser(res.user)
    user.value = res.user
    await loadMenus()
    return res.user
  }

  /**
   * 拉取当前用户可见的菜单树。
   *
   * ★ 刻意**不**缓存到 localStorage：
   *   菜单树是服务端的授权状态（后端按权限裁剪后返回）。
   *   一旦缓存到本地，就会出现「管理员在后台加了新菜单/调整了权限，
   *   用户不重新登录就始终看不到」的问题 —— 这个坑实际踩过一次：
   *   新增的「门店配送达成」菜单因为页面加载了旧缓存而不显示。
   *
   *   代价是每次刷新页面多一个轻量请求。菜单接口只查一次权限表 + 裁剪树，
   *   让它始终反映服务端当前状态，比省这一次请求重要得多。
   */
  async function loadMenus() {
    menus.value = await api.fetchMenus()
    menusLoaded.value = true
    return menus.value
  }

  /** 重新拉取当前用户信息（权限变更后调用） */
  async function refreshProfile() {
    const me = await api.fetchMe()
    setStoredUser(me)
    user.value = me
    // 用户信息变了，可见菜单也可能变，一并刷新
    await loadMenus()
    return me
  }

  async function logout() {
    try {
      await api.logout()
    } catch {
      // 登出失败不影响本地清理
    }
    clearAuthStorage()
    user.value = null
    menus.value = []
    menusLoaded.value = false
  }

  return {
    user,
    menus,
    menusLoaded,
    isLoggedIn,
    permissions,
    roleNames,
    has,
    login,
    logout,
    loadMenus,
    refreshProfile,
  }
})
