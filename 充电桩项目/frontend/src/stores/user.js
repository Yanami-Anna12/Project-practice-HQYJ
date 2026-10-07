import { defineStore } from 'pinia'
import { authApi } from '@/api'

/** 认证与当前用户：数据权限决定可见范围（PDF 3.3） */
export const useUserStore = defineStore('user', {
  state: () => ({
    token: localStorage.getItem('token') || '',
    user: null,
    permissions: [],
    menus: [],
    role: null,
    loaded: false,
  }),

  getters: {
    isLoggedIn: (s) => Boolean(s.token),
    dataScope: (s) => s.user?.data_scope || s.role?.data_scope || '个人数据',
    displayName: (s) => s.user?.real_name || s.user?.username || '',
    /** 权限判断：平台数据权限默认放行 */
    hasPermission: (s) => (code) => {
      if (!code) return true
      if (s.dataScope === '平台数据') return true
      return s.permissions.includes(code)
    },
  },

  actions: {
    async login(payload) {
      const res = await authApi.login(payload)
      this.token = res.data.access_token
      localStorage.setItem('token', this.token)
      this.user = res.data.user
      await this.fetchProfile()
      return res.data.user
    },

    async fetchProfile() {
      if (!this.token) return null
      const res = await authApi.profile()
      this.user = res.data.user
      this.permissions = res.data.permissions || []
      this.menus = res.data.menus || []
      this.role = res.data.role
      this.loaded = true
      return this.user
    },

    async updateProfile(payload) {
      const res = await authApi.updateProfile(payload)
      this.user = res.data
      return res.data
    },

    async logout() {
      try {
        await authApi.logout()
      } catch {
        /* 忽略退出失败 */
      }
      this.token = ''
      this.user = null
      this.permissions = []
      this.menus = []
      this.role = null
      this.loaded = false
      localStorage.removeItem('token')
    },
  },
})
