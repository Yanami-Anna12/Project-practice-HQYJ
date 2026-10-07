/**
 * 业务枚举的中文标签与标签颜色。
 *
 * ★ 取值必须与 backend/seed.py 写入 sys_dict_item 的值保持一致，
 *   否则页面会显示原始英文码。这里是纯粹的展示映射，不做业务判断。
 */

/** 地形限制 */
export const TERRAIN_TYPE = {
  normal: { text: '普通', type: 'success' },
  medium: { text: '中控', type: 'warning' },
  strict: { text: '严控', type: 'danger' },
}

/** 车辆地形能力 */
export const TERRAIN_CAPABILITY = {
  all: { text: '全能去', type: 'success' },
  big_small: { text: '大小包能去', type: 'warning' },
  small_only: { text: '小包能去', type: 'info' },
}

/** 配送时段 */
export const TIME_WINDOW = {
  AM: { text: '上午', type: 'primary' },
  PM: { text: '下午', type: 'warning' },
}

/** 车辆状态 */
export const VEHICLE_STATUS = {
  idle: { text: '空闲', type: 'success' },
  running: { text: '出车中', type: 'primary' },
  maintenance: { text: '维保中', type: 'warning' },
  offline: { text: '停用', type: 'info' },
}

/** 司机班次 */
export const DRIVER_SHIFT = {
  AM: { text: '上午班', type: 'primary' },
  PM: { text: '下午班', type: 'warning' },
  FULL: { text: '全天', type: 'success' },
}

/** 司机状态 */
export const DRIVER_STATUS = {
  available: { text: '可出勤', type: 'success' },
  leave: { text: '请假', type: 'warning' },
  offline: { text: '停用', type: 'info' },
}

/** 车型码 */
export const VEHICLE_TYPE_CODE = {
  '4.2m': { text: '四米二', type: 'primary' },
  big: { text: '大包', type: 'warning' },
  small: { text: '小包', type: 'success' },
}

/** 调度任务状态（后续模块使用） */
export const TASK_STATUS = {
  created: { text: '待调度', type: 'info' },
  running: { text: '求解中', type: 'primary' },
  pending_confirm: { text: '待确认', type: 'warning' },
  dispatched: { text: '已下发', type: 'success' },
  completed: { text: '已完成', type: '' },
  failed: { text: '失败', type: 'danger' },
}

/** 通用取值：找不到时回退为原始码 */
function pick(map, value) {
  return map[value] || { text: value || '—', type: '' }
}

export const terrainType = (v) => pick(TERRAIN_TYPE, v)
export const terrainCapability = (v) => pick(TERRAIN_CAPABILITY, v)
export const timeWindow = (v) => pick(TIME_WINDOW, v)
export const vehicleStatus = (v) => pick(VEHICLE_STATUS, v)
export const driverShift = (v) => pick(DRIVER_SHIFT, v)
export const driverStatus = (v) => pick(DRIVER_STATUS, v)
export const vehicleTypeCode = (v) => pick(VEHICLE_TYPE_CODE, v)
export const taskStatus = (v) => pick(TASK_STATUS, v)

/** 供下拉框使用的选项列表 */
export const TERRAIN_TYPE_OPTIONS = Object.entries(TERRAIN_TYPE).map(([value, m]) => ({
  value,
  label: m.text,
}))
export const TERRAIN_CAPABILITY_OPTIONS = Object.entries(TERRAIN_CAPABILITY).map(
  ([value, m]) => ({ value, label: m.text }),
)
export const TIME_WINDOW_OPTIONS = Object.entries(TIME_WINDOW).map(([value, m]) => ({
  value,
  label: m.text,
}))
export const VEHICLE_STATUS_OPTIONS = Object.entries(VEHICLE_STATUS).map(([value, m]) => ({
  value,
  label: m.text,
}))
export const DRIVER_SHIFT_OPTIONS = Object.entries(DRIVER_SHIFT).map(([value, m]) => ({
  value,
  label: m.text,
}))
export const DRIVER_STATUS_OPTIONS = Object.entries(DRIVER_STATUS).map(([value, m]) => ({
  value,
  label: m.text,
}))
