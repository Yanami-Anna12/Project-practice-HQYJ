/**
 * 权限判断的辅助函数（供组合式 API 里使用）。
 */

import { computed } from 'vue'
import { useAuthStore } from '@/stores/auth'

/** 返回一个 has(code) 函数与只读的权限列表 */
export function usePermission() {
  const auth = useAuthStore()
  return {
    permissions: computed(() => auth.permissions),
    has: (code) => auth.has(code),
    /** 任一满足 */
    hasAny: (codes = []) => codes.some((c) => auth.has(c)),
  }
}
