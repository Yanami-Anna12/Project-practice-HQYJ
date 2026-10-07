/**
 * 菜单分组的元信息（占位页与日志页用来展示说明）。
 */

export const PERMISSION_MODULES = {
  system: {
    title: '系统管理',
    match: 'system',
    desc: '用户、角色、权限、字典、参数、附件、日志',
    permissionPrefixes: ['users:', 'roles:', 'permissions:', 'dicts:', 'params:', 'attachments:', 'logs:'],
  },
  base: {
    title: '业务基础数据',
    match: 'base',
    desc: '门店、线路、映射、车辆、司机、地形规则',
    permissionPrefixes: ['stores:', 'routes:', 'vehicles:', 'drivers:', 'terrain:'],
  },
  rules: {
    title: '调度规则配置',
    match: 'rules',
    desc: '装载量规则、趟次规则、调度策略与评分、规则版本治理',
    permissionPrefixes: ['vehicles:', 'scheduling:'],
  },
  assign: {
    title: '车辆分配管理',
    match: 'assign',
    desc: '可出勤车辆池、门店配送需求、分配结果',
    permissionPrefixes: ['vehicles:', 'stores:', 'scheduling:'],
  },
  scheduling: {
    title: '智能调度 Agent',
    match: 'scheduling',
    desc: '调度任务、多方案比选、人工确认、异常重排',
    permissionPrefixes: ['scheduling:'],
  },
  reports: {
    title: '报表与看板',
    match: 'reports',
    desc: '车辆出勤、趟次达成、装载率、成本与方案对比',
    permissionPrefixes: ['reports:'],
  },
  integration: {
    title: '集成与监控',
    match: 'integration',
    desc: 'TMS/WMS/OMS/ERP 接口集成、监控预警',
    permissionPrefixes: ['integrations:', 'monitor:'],
  },
}

/** 动作码的中文说明与标签颜色（日志页用） */
export const ACTION_META = {
  'auth.login': { text: '登录成功', type: 'info' },
  'auth.login_failed': { text: '登录失败', type: 'danger' },
  'system.seed': { text: '系统初始化', type: 'info' },

  'user.assign_roles': { text: '调整用户角色', type: 'warning' },
  'user.toggle': { text: '启停用户', type: 'danger' },
  'user.reset_password': { text: '重置密码', type: 'warning' },

  'role.create': { text: '新建角色', type: 'success' },
  'role.update': { text: '更新角色', type: 'primary' },
  'role.delete': { text: '删除角色', type: 'danger' },

  'permission.create': { text: '新建权限点', type: 'success' },
  'permission.toggle': { text: '启停权限点', type: 'danger' },
  'permission.delete': { text: '删除权限点', type: 'danger' },

  'dict.create': { text: '新建字典类型', type: 'success' },
  'dict.toggle': { text: '启停字典类型', type: 'warning' },
  'dict.delete': { text: '删除字典类型', type: 'danger' },
  'dict_item.create': { text: '新建字典项', type: 'success' },
  'dict_item.update': { text: '更新字典项', type: 'primary' },
  'dict_item.delete': { text: '删除字典项', type: 'danger' },

  'param.update': { text: '修改参数', type: 'primary' },
  'param.toggle': { text: '启停参数', type: 'warning' },

  'attachment.upload': { text: '上传附件', type: 'success' },
  'attachment.delete': { text: '删除附件', type: 'danger' },

  // 业务动作（首版尚未产生，预留给后续模块）
  'scheduling.create': { text: '创建调度任务', type: 'primary' },
  'scheduling.confirm': { text: '人工确认方案', type: 'warning' },
  'scheduling.replan': { text: '异常重排', type: 'danger' },
  'scheduling.dispatch': { text: '下发方案', type: 'success' },
}

export function actionMeta(action) {
  return ACTION_META[action] || { text: action, type: 'info' }
}

/** 审计目标的类型中文名 */
export const TARGET_TYPE_LABELS = {
  system: '系统',
  user: '用户',
  role: '角色',
  permission: '权限点',
  dict: '字典',
  param: '参数',
  attachment: '附件',
  task: '调度任务',
}
