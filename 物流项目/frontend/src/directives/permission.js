/**
 * 按钮级权限：v-permission="'users:manage'"
 *
 * ★ 只是体验优化 —— 隐藏按钮不等于禁止操作。
 *   首版无后端，所以这一点在本版本里只是「占位」；
 *   接真实后端后，真正的把关在服务端口。
 */

import { useAuthStore } from '@/stores/auth'

export default {
  mounted(el, binding) {
    const auth = useAuthStore()
    const required = binding.value
    if (required && !auth.has(required)) {
      el.parentNode?.removeChild(el)
    }
  },
}
