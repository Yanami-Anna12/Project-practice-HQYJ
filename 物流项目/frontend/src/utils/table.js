/**
 * 列表页的通用加载逻辑：loading 状态 + 错误兜底。
 */

import { ref } from 'vue'
import { withError } from './error'

/**
 * @param {Function} loader 一个返回 Promise<Array> 的函数
 * @param {*} initial 初始值
 */
export function useTable(loader, initial = []) {
  const loading = ref(false)
  const rows = ref(initial)

  async function load() {
    loading.value = true
    try {
      const data = await withError(() => loader())
      rows.value = data || []
    } finally {
      loading.value = false
    }
  }

  return { loading, rows, load }
}

/** 把 ISO 时间格式化成 'YYYY-MM-DD HH:mm:ss' */
export function formatTime(value) {
  if (!value) return '—'
  return String(value).replace('T', ' ').slice(0, 19)
}

/** 把字节数格式化成可读大小 */
export function formatSize(bytes) {
  const n = Number(bytes) || 0
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(2)} MB`
}
