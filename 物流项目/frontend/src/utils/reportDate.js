/**
 * 报表页共用的「调度日期」选择逻辑。
 *
 * ★ 为什么抽出来：4 个报表页都需要「拉可选日期 + 选择 + 触发重载」，
 *   而且都要处理「没有任何调度数据」的空状态。
 */

import { ref } from 'vue'
import * as api from '@/api'
import { withError } from './error'

export function useReportDate() {
  const dates = ref([])
  /** 空字符串表示「全部日期」 */
  const scheduleDate = ref('')

  async function loadDates() {
    const list = (await withError(() => api.fetchReportDates())) || []
    dates.value = list
    // 默认选中最近一次有数据的日期，没有数据时保持「全部」
    if (!scheduleDate.value && list.length) {
      scheduleDate.value = list[0]
    }
  }

  return { dates, scheduleDate, loadDates }
}
