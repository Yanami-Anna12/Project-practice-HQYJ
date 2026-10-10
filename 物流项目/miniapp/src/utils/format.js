/**
 * 显示用的小工具：日期、状态文案、异常类型。
 *
 * ★ 状态取值直接对齐后端（见 backend/app/services/mobile.py）：
 *   计划明细 status：planned 已计划 / dispatched 已下发 / arrived 已到店 / done 已完成
 *   趟次 trip_status：planned 未开始 / running 执行中 / done 已完成
 *   打卡 action：arrive 到店 / depart 离店 / complete 完成
 *   后端用的中文串必须与实际返回保持一致，否则司机会看到英文字符串。
 */

/** Date | string → YYYY-MM-DD */
export function formatDate(value) {
  if (!value) return ''
  if (typeof value === 'string') return value.slice(0, 10)
  const d = new Date(value)
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

/** 今天（本地时区） */
export function today() {
  return formatDate(new Date())
}

/** 在给定日期上加减天数，返回 YYYY-MM-DD */
export function shiftDate(dateStr, days) {
  const base = dateStr ? new Date(`${dateStr}T00:00:00`) : new Date()
  base.setDate(base.getDate() + days)
  return formatDate(base)
}

/** ISO 时间串 → HH:mm */
export function formatTime(value) {
  if (!value) return ''
  const text = String(value)
  const matched = text.match(/T(\d{2}:\d{2})/)
  if (matched) return matched[1]
  const d = new Date(text)
  if (Number.isNaN(d.getTime())) return text.slice(11, 16)
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

/** ISO 时间串 → MM-DD HH:mm（消息列表用） */
export function formatDateTime(value) {
  if (!value) return ''
  const text = String(value)
  return `${text.slice(5, 10)} ${formatTime(text)}`
}

/** 时间段的展示名：AM 上午 / PM 下午 / FULL 全天 */
export function timeWindowLabel(code) {
  const map = { AM: '上午', PM: '下午', FULL: '全天' }
  return map[code] || code || '—'
}

/** 班次展示名 */
export function shiftLabel(code) {
  const map = { AM: '上午班', PM: '下午班', FULL: '全天班' }
  return map[code] || code || '—'
}

/** 计划明细状态 → 中文（站点级别的状态） */
export function stopStatusLabel(status) {
  const map = {
    planned: '未下发',
    dispatched: '待打卡',
    arrived: '已到店',
    done: '已完成',
    completed: '已完成',
  }
  return map[status] || status || '未知'
}

/** 计划明细状态 → 标签样式类 */
export function stopStatusClass(status) {
  if (status === 'arrived') return 'tag-running'
  if (status === 'done' || status === 'completed') return 'tag-done'
  if (status === 'planned') return 'tag-warn'
  return 'tag-planned'
}

/** 趟次整体状态 → 中文 */
export function tripStatusLabel(status) {
  const map = { planned: '未开始', running: '执行中', done: '已完成' }
  return map[status] || status || '未知'
}

/**
 * 趟次整体状态 → 展示文案（带上站点状态兜底）。
 *
 * ★ 后端 _trip_status() 只认「已完成 done」和「已到店 arrived」两种站点状态，
 *   全线 dispatched（已下发未打卡）时 trip_status 仍然是 planned。
 *   对司机来说这时的趟次其实是「可以打卡了」，显示「未开始」会让人以为不能开工，
 *   所以在门店一个都没动过、但已有 dispatched 门店时显示「待打卡」。
 */
export function tripStatusText(trip) {
  const status = trip?.trip_status || ''
  if (
    status === 'planned' &&
    !trip?.done_stores &&
    !trip?.arrived_stores &&
    trip?.store_count
  ) {
    return '待打卡'
  }
  return tripStatusLabel(status)
}

/** 趟次整体状态 → 标签样式类 */
export function tripStatusClass(status) {
  if (status === 'running') return 'tag-running'
  if (status === 'done') return 'tag-done'
  return 'tag-planned'
}

/** 打卡动作 → 中文 */
export function actionLabel(action) {
  const map = { arrive: '到店', depart: '离店', complete: '完成' }
  return map[action] || action || ''
}

/* ------------------------------------------------------------------ *
 * 管理端（只读看板）用的展示映射
 * ------------------------------------------------------------------ */

/**
 * 调度任务状态 → 中文 / 标签样式类。
 *
 * ★ 取值与 backend/seed.py 的 task_status 字典项、以及
 *   frontend/src/utils/enums.js 的 TASK_STATUS 三处保持一致，
 *   三端看到的状态名必须是同一个词。
 */
export const TASK_STATUS = {
  created: { text: '待调度', cls: 'tag-planned' },
  running: { text: '求解中', cls: 'tag-running' },
  pending_confirm: { text: '待确认', cls: 'tag-warn' },
  dispatched: { text: '已下发', cls: 'tag-done' },
  completed: { text: '已完成', cls: 'tag-done' },
  failed: { text: '失败', cls: 'tag-danger' },
}

export function taskStatusText(status) {
  return (TASK_STATUS[status] || {}).text || status || '未知'
}

export function taskStatusClass(status) {
  return (TASK_STATUS[status] || {}).cls || 'tag-planned'
}

/** 异常事件状态 → 中文（调度侧现在只有 pending / handled 两种在用） */
export function exceptionStatusText(status) {
  const map = { pending: '待处理', handled: '已处理', resolved: '已处理', ignored: '已忽略' }
  return map[status] || status || '未知'
}

export function exceptionStatusClass(status) {
  return status === 'pending' ? 'tag-warn' : 'tag-done'
}

/**
 * 异常来源 → 中文。
 * driver:D002 这种是司机端上报（source = driver:<工号>），其余是调度员账号名。
 */
export function exceptionSourceText(source) {
  if (!source) return '—'
  if (source.startsWith('driver:')) return `司机上报（${source.slice(7)}）`
  return source
}

/**
 * 确认接单状态 → 展示文案。
 *
 * ★ 已跑完的一律显示「已完成」，不显示「待确认」：
 *   早先的写法对 `done 且从没点过确认` 的趟次会显示「待确认」，
 *   于是绿卡上写着「待确认」，自相矛盾（已跑完的单子再点确认也没有意义）。
 *
 * @param {object} trip 至少含 accepted / accepted_at / trip_status
 */
export function acceptStatusText(trip) {
  if (tripState(trip) === 'done') {
    const when = trip?.accepted_at ? formatDateTime(trip.accepted_at) : ''
    return when ? `已完成 · ${when} 接单` : '已完成'
  }
  if (!trip || !trip.accepted) return '待确认'
  const when = trip.accepted_at ? formatDateTime(trip.accepted_at) : ''
  return when ? `已确认接单 ${when}` : '已确认接单'
}

/**
 * 确认接单状态 → 标签样式类。
 *
 * ★ 与卡片色条同一套三色语义（用户口径）：
 *   未确认 = 红，已确认但没跑完 = 黄，已跑完 = 绿。
 *   注意「已跑完」优先于「已确认」：跑完的单子哪怕没点过确认，也该是绿的。
 */
export function acceptStatusClass(trip) {
  const state = tripState(trip)
  if (state === 'done') return 'tag-done'
  if (state === 'accepted') return 'tag-accepted'
  return 'tag-pending'
}

/**
 * 趟次的「三色状态」—— 全站唯一口径，色条、标签、排序都用它。
 *
 *   pending  未确认接单           → 红色
 *   accepted 已确认但未完成       → 黄色
 *   done     已完成（跑完了）     → 绿色
 *
 * ★ 为什么抽成一个函数：卡片颜色、状态标签、列表排序三处必须完全一致，
 *   各写一份 if/else 迟早出现「卡片是黄的、标签是绿的」这种自相矛盾。
 *
 * @param {object} trip 趟次对象（列表项或详情对象）
 * @returns {'pending'|'accepted'|'done'}
 */
export function tripState(trip) {
  if (trip && trip.trip_status === 'done') return 'done'
  return trip && trip.accepted ? 'accepted' : 'pending'
}

/** 三色状态 → 卡片色条 class（红/黄/绿） */
export function tripCardClass(trip) {
  return `trip-card-${tripState(trip)}`
}

/** 三色状态 → 中文短标签（色条旁边那行字的兜底文案） */
export function tripStateLabel(trip) {
  const map = { pending: '待确认', accepted: '已接单', done: '已完成' }
  return map[tripState(trip)]
}

/**
 * 看板「趟次明细」用的四态（比司机端多一档「正在跑」）。
 *
 * 后端 `manager/overview` 的 trip_briefs.state 就是这四个值：
 *   running  有门店到店/完成但没全完   → 看板排最前（调度最该盯的）
 *   accepted 已接单、一个门店都没打卡
 *   pending  没接单也没打卡
 *   done     该趟所有门店都完成
 */
export function briefStateLabel(state) {
  const map = { running: '正在跑', accepted: '已接单', pending: '待确认', done: '已完成' }
  return map[state] || state || '—'
}

/** 看板四态 → 标签样式类（与司机端三色同色系，外加「正在跑」的蓝色） */
export function briefStateClass(state) {
  const map = {
    running: 'tag-running',
    accepted: 'tag-accepted',
    pending: 'tag-pending',
    done: 'tag-done',
  }
  return map[state] || 'tag-planned'
}

/**
 * 把 accept 接口的返回结果合并回列表/详情对象（就地更新）。
 *
 * ★ 为什么不用「确认成功后整页重拉」：
 *   弱网下重拉一次要等一个往返，司机点完按钮会以为没反应。
 *   后端已经把 accepted_at 原样返回，本地直接改这两行就够了；
 *   下一次 onShow / 下拉刷新时再与服务端对齐。
 *
 * @param {object} target 趟次对象（列表项或详情对象）
 * @param {object} result accept 接口返回
 * @returns {boolean} 是否确实变成「已确认」
 */
export function applyAcceptance(target, result) {
  if (!target || !result || !result.accepted) return false
  target.accepted = true
  if (result.accepted_at) target.accepted_at = result.accepted_at
  return true
}

/** 秒级时间戳（ISO）→ YYYY-MM-DD HH:mm（看板生成时间用） */
export function formatFullDateTime(value) {
  if (!value) return ''
  return `${formatDate(value)} ${formatTime(value)}`
}

/* ------------------------------------------------------------------ *
 * 方案明细 → 趟次（管理端任务详情用）
 * ------------------------------------------------------------------ */

/**
 * 把「方案明细」（一行 = 某车某趟服务某门店）按 车辆 + 趟次 归并成趟次。
 *
 * ★ 为什么在前端归并：后端 `GET /api/scheduling/plans/{id}/details` 是
 *   「明细」粒度（一个门店一行），因为它同时服务于方案比选与门店级展示。
 *   管理端任务详情要的是「趟次」粒度（一行 = 一趟活），
 *   归并规则很轻（按 vehicle_id + trip_no 分组），放在这里比让后端多开一个
 *   接口更符合本项目「接口按数据形态划分、展示归并把控在前端」的既有做法。
 *
 * ★ accepted 的取值：同一趟的所有门店行必然一致（后端按 trip_key 匹配
 *   dispatch_record，确认是趟次级事实），所以取首行即可，不会出现
 *   「一半已确认一半未确认」的自相矛盾展示。
 *
 * @param {Array} details 方案明细数组
 * @returns {Array} [{ trip_key, vehicle_id, plate_no, driver_name, trip_no,
 *                     time_window, store_count, total_load, done_stores,
 *                     accepted, accepted_at, stores }]
 */
export function groupPlanTrips(details) {
  const rows = Array.isArray(details) ? details : []
  const grouped = {}
  const order = []
  rows.forEach((row) => {
    const key = `${row.vehicle_id}:${row.trip_no}`
    if (!grouped[key]) {
      grouped[key] = []
      order.push(key)
    }
    grouped[key].push(row)
  })

  return order.map((key) => {
    const list = grouped[key].slice().sort((a, b) => a.sequence - b.sequence)
    const head = list[0]
    const done = list.filter((r) => r.status === 'done' || r.status === 'completed').length
    const arrived = list.filter((r) => r.status === 'arrived').length
    return {
      trip_key: `${head.vehicle_id}:${head.trip_no}`,
      vehicle_id: head.vehicle_id,
      plate_no: head.plate_no,
      driver_name: head.driver_name,
      trip_no: head.trip_no,
      time_window: head.time_window,
      store_count: list.length,
      total_load: Math.round(list.reduce((sum, r) => sum + (Number(r.load_amount) || 0), 0) * 100) / 100,
      done_stores: done,
      arrived_stores: arrived,
      /**
       * ★ 这里必须补上 trip_status：它是 acceptStatusText/acceptStatusClass/tripState
       *   的判据之一。少了它，管理端「任务详情」里**已经跑完的趟次会被判成
       *   「待确认」（红）/「已确认」**，与司机端看到的绿色「已完成」自相矛盾。
       *   口径与后端 services/mobile.py 的 _trip_status() 完全一致：
       *   全 done → done；有 arrived/done → running；否则 planned。
       */
      trip_status: done >= list.length && list.length ? 'done' : done || arrived ? 'running' : 'planned',
      accepted: !!head.accepted,
      accepted_at: head.accepted_at || null,
      stores: list,
    }
  })
}

/**
 * 异常类型选项。
 *
 * ★ 取值必须落在后端与调度员界面**已有**的 event_type 里：
 *   调度员侧的「异常重排」页面只认识 vehicle_breakdown / driver_absence /
 *   demand_change / traffic_control / terrain_control 这 5 个值
 *   （见 frontend/src/views/scheduling/SchedExceptionView.vue），
 *   传别的值那边会显示成裸英文串。所以司机端只是换个更口语的说法，
 *   把多个说法归到同一个值上，不自造新类型。
 */
export const EXCEPTION_TYPES = [
  { key: 'traffic', value: 'traffic_control', label: '交通管制 / 堵车' },
  { key: 'breakdown', value: 'vehicle_breakdown', label: '车辆故障' },
  { key: 'closed', value: 'demand_change', label: '门店未营业 / 无人收货' },
  { key: 'demand', value: 'demand_change', label: '门店临时加减货' },
  { key: 'terrain', value: 'terrain_control', label: '地形管控 / 路不通' },
  { key: 'weather', value: 'terrain_control', label: '恶劣天气' },
  { key: 'other', value: 'driver_absence', label: '其他异常' },
]

/** 异常类型 → 中文（调度员侧已有的 5 个值都能认出来） */
export function exceptionTypeLabel(value) {
  const map = {
    vehicle_breakdown: '车辆故障',
    driver_absence: '司机缺勤 / 其他',
    demand_change: '门店加减货',
    traffic_control: '交通管制',
    terrain_control: '地形 / 天气管控',
  }
  return map[value] || value || '异常'
}

/** 手机号拨号（小程序里 tel: 只能通过 makePhoneCall 调起） */
export function callPhone(phone) {
  if (!phone) {
    uni.showToast({ title: '该门店没有留电话', icon: 'none' })
    return
  }
  uni.makePhoneCall({
    phoneNumber: String(phone),
    fail: () => uni.showToast({ title: '拨号已取消', icon: 'none' }),
  })
}

/** 复制文本到剪贴板 */
export function copyText(text, tip = '已复制') {
  uni.setClipboardData({
    data: String(text || ''),
    success: () => uni.showToast({ title: tip, icon: 'none' }),
  })
}
