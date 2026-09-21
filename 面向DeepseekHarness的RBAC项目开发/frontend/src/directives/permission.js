/**
 * v-permission 指令 —— 按钮级权限控制。
 *
 * 用法：
 *     <el-button v-permission="'products:edit'">编辑商品</el-button>
 *     <el-button v-permission.disable="'products:edit'">编辑商品</el-button>
 *
 * 两种模式：
 *     默认          无权限时把元素从 DOM 中移除（隐藏）
 *     .disable 修饰符 无权限时保留元素但禁用并加提示（让用户知道"有这个功能但你没权限"）
 *
 * ★ 这是**纯体验优化**。移除 DOM 只防住了"手滑点错"，防不住任何人：
 *   打开控制台改一下 Pinia 里的 permissions，按钮立刻就回来了。
 *   但点下去后端 authorize() 依然返回 403 —— 那才是真正的控制点。
 *   换句话说：本指令的作用是"别让用户看到点不动的按钮"，不是"阻止越权"。
 */

import { useAuthStore } from '@/stores/auth'

function checkAndApply(el, binding) {
  const auth = useAuthStore()
  const required = binding.value

  // 未声明权限要求 → 不做任何处理
  if (!required) return

  const codes = Array.isArray(required) ? required : [required]
  // any 修饰符：满足任一权限即可；默认需要全部满足
  const mode = binding.modifiers.any ? 'some' : 'every'
  const allowed = codes[mode]((code) => auth.has(code))

  if (allowed) return

  if (binding.modifiers.disable) {
    // 禁用模式：保留元素，置灰并说明原因
    el.setAttribute('disabled', 'disabled')
    el.classList.add('is-disabled')
    el.style.pointerEvents = 'none'
    el.style.opacity = '0.5'
    if (!el.title) {
      el.title = `需要权限：${codes.join(mode === 'some' ? ' 或 ' : ' 且 ')}`
    }
  } else {
    // 默认模式：从 DOM 中移除
    el.parentNode?.removeChild(el)
  }
}

export default {
  mounted(el, binding) {
    checkAndApply(el, binding)
  },
  // 权限变化时（如管理员改绑角色后刷新）重新判定
  updated(el, binding) {
    // 已移除的元素不会再触发 updated，这里只需处理禁用模式的恢复
    if (binding.modifiers.disable && binding.value) {
      const auth = useAuthStore()
      const codes = Array.isArray(binding.value) ? binding.value : [binding.value]
      const mode = binding.modifiers.any ? 'some' : 'every'
      if (codes[mode]((code) => auth.has(code))) {
        el.removeAttribute('disabled')
        el.classList.remove('is-disabled')
        el.style.pointerEvents = ''
        el.style.opacity = ''
        el.removeAttribute('title')
      }
    }
  },
}
