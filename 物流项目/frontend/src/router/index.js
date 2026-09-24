/**
 * 路由定义与全局守卫。
 *
 * 两道基于权限的界面控制，都只是**体验优化**：
 *   1. 路由级 —— meta.permission 声明该页需要的权限点，守卫里拦截
 *   2. 菜单级 —— 侧边栏渲染的是按权限裁剪后的菜单树（见 api/menus.js）
 *
 * ★ 首版是纯前端演示，没有后端，所以「改 localStorage 就能越权」在本版本成立。
 *   接真实后端后，最终把关必须在服务端。
 */

import { createRouter, createWebHistory } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '@/stores/auth'

const routes = [
  {
    path: '/login',
    name: 'login',
    component: () => import('@/views/LoginView.vue'),
    meta: { public: true, title: '登录' },
  },
  {
    path: '/',
    component: () => import('@/layout/AppLayout.vue'),
    redirect: '/dashboard',
    children: [
      {
        path: 'dashboard',
        name: 'dashboard',
        component: () => import('@/views/DashboardView.vue'),
        meta: { title: '调度看板', icon: 'Odometer' },
      },

      /* ---------------- 系统管理（首版已实现） ---------------- */
      {
        path: 'system/users',
        name: 'system-users',
        component: () => import('@/views/system/UsersView.vue'),
        meta: { title: '用户管理', permission: 'users:read' },
      },
      {
        path: 'system/roles',
        name: 'system-roles',
        component: () => import('@/views/system/RolesView.vue'),
        meta: { title: '角色管理', permission: 'roles:read' },
      },
      {
        path: 'system/permissions',
        name: 'system-permissions',
        component: () => import('@/views/system/PermissionsView.vue'),
        meta: { title: '权限管理', permission: 'permissions:read' },
      },
      {
        path: 'system/dicts',
        name: 'system-dicts',
        component: () => import('@/views/system/DictsView.vue'),
        meta: { title: '字典管理', permission: 'dicts:read' },
      },
      {
        path: 'system/params',
        name: 'system-params',
        component: () => import('@/views/system/ParamsView.vue'),
        meta: { title: '参数管理', permission: 'params:read' },
      },
      {
        path: 'system/attachments',
        name: 'system-attachments',
        component: () => import('@/views/system/AttachmentsView.vue'),
        meta: { title: '附件管理', permission: 'attachments:read' },
      },
      {
        path: 'system/logs',
        name: 'system-logs',
        component: () => import('@/views/system/LogsView.vue'),
        meta: { title: '日志管理', permission: 'logs:read' },
      },

      /* ---------------- 其余模块：占位页（菜单可见，提示待开发） ---------------- */
      // 业务基础数据
      { path: 'base/stores', name: 'base-stores', component: () => import('@/views/base/StoresView.vue'), meta: { title: '门店管理', permission: 'stores:read' } },
      { path: 'base/routes', name: 'base-routes', component: () => import('@/views/base/RoutesView.vue'), meta: { title: '线路管理', permission: 'routes:read' } },
      { path: 'base/mappings', name: 'base-mappings', component: () => import('@/views/base/MappingsView.vue'), meta: { title: '门店线路映射', permission: 'routes:read' } },
      { path: 'base/vehicles', name: 'base-vehicles', component: () => import('@/views/base/VehiclesView.vue'), meta: { title: '车辆档案', permission: 'vehicles:read' } },
      { path: 'base/vehicle-types', name: 'base-vehicle-types', component: () => import('@/views/base/VehicleTypesView.vue'), meta: { title: '车辆类型', permission: 'vehicles:read' } },
      { path: 'base/drivers', name: 'base-drivers', component: () => import('@/views/base/DriversView.vue'), meta: { title: '司机管理', permission: 'drivers:read' } },
      { path: 'base/terrain', name: 'base-terrain', component: () => import('@/views/base/TerrainView.vue'), meta: { title: '地形与通行规则', permission: 'terrain:manage' } },

      // 调度规则配置
      // ★ 装载量规则与趟次规则是同一张表（md_vehicle_type）的两组字段，
      //   所以复用同一个组件。因为两者路由 path 不同，
      //   el-menu 按 path 匹配主导航不会冲突。
      { path: 'rules/load', name: 'rules-load', component: () => import('@/views/base/VehicleTypesView.vue'), meta: { title: '装载量规则', permission: 'vehicles:read' } },
      { path: 'rules/trip', name: 'rules-trip', component: () => import('@/views/base/VehicleTypesView.vue'), meta: { title: '趟次规则', permission: 'vehicles:read' } },
      { path: 'rules/strategy', name: 'rules-strategy', component: () => import('@/views/rules/StrategyView.vue'), meta: { title: '调度策略与评分', permission: 'scheduling:read' } },
      { path: 'rules/governance', name: 'rules-governance', component: () => import('@/views/rules/GovernanceView.vue'), meta: { title: '规则版本治理', permission: 'scheduling:read' } },

      // 车辆分配管理
      { path: 'assign/available', name: 'assign-available', component: () => import('@/views/assign/AvailableView.vue'), meta: { title: '可出勤车辆', permission: 'vehicles:read' } },
      { path: 'assign/demand', name: 'assign-demand', component: () => import('@/views/assign/DemandsView.vue'), meta: { title: '门店配送需求', permission: 'stores:read' } },
      { path: 'assign/result', name: 'assign-result', component: () => import('@/views/assign/ResultView.vue'), meta: { title: '分配结果', permission: 'scheduling:read' } },

      // 智能调度 Agent
      { path: 'scheduling/tasks', name: 'sched-tasks', component: () => import('@/views/scheduling/SchedTasksView.vue'), meta: { title: '调度任务', permission: 'scheduling:read' } },
      { path: 'scheduling/plans', name: 'sched-plans', component: () => import('@/views/scheduling/SchedPlansView.vue'), meta: { title: '多方案比选', permission: 'scheduling:read' } },
      { path: 'scheduling/confirm', name: 'sched-confirm', component: () => import('@/views/scheduling/SchedConfirmView.vue'), meta: { title: '人工确认', permission: 'scheduling:confirm' } },
      { path: 'scheduling/exception', name: 'sched-exception', component: () => import('@/views/scheduling/SchedExceptionView.vue'), meta: { title: '异常重排', permission: 'scheduling:replan' } },

      // 报表与看板
      { path: 'reports/attendance', name: 'reports-attendance', component: () => import('@/views/reports/AttendanceView.vue'), meta: { title: '车辆出勤', permission: 'reports:view' } },
      { path: 'reports/trip', name: 'reports-trip', component: () => import('@/views/reports/TripView.vue'), meta: { title: '趟次达成', permission: 'reports:view' } },
      { path: 'reports/loadrate', name: 'reports-loadrate', component: () => import('@/views/reports/LoadRateView.vue'), meta: { title: '装载率分析', permission: 'reports:view' } },
      { path: 'reports/store', name: 'reports-store', component: () => import('@/views/reports/StoreView.vue'), meta: { title: '门店配送达成', permission: 'reports:view' } },
      { path: 'reports/cost', name: 'reports-cost', component: () => import('@/views/reports/CostView.vue'), meta: { title: '成本与方案对比', permission: 'reports:view' } },

      // 集成与监控
      { path: 'integration/systems', name: 'int-systems', component: () => import('@/views/integration/SystemsView.vue'), meta: { title: '接口集成配置', permission: 'integrations:manage' } },
      { path: 'integration/monitor', name: 'int-monitor', component: () => import('@/views/integration/MonitorView.vue'), meta: { title: '监控预警', permission: 'monitor:read' } },

      {
        path: 'forbidden',
        name: 'forbidden',
        component: () => import('@/views/ForbiddenView.vue'),
        meta: { title: '无权访问' },
      },
      {
        path: ':pathMatch(.*)*',
        name: 'not-found',
        component: () => import('@/views/NotFoundView.vue'),
        meta: { title: '页面不存在' },
      },
    ],
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()

  // 1) 公开页面直接放行
  if (to.meta.public) {
    if (to.name === 'login' && auth.isLoggedIn) return { path: '/dashboard' }
    return true
  }

  // 2) 未登录 → 去登录页，记住原目标便于登录后跳回
  if (!auth.isLoggedIn) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }

  // 3) 菜单尚未加载（例如直接刷新子页面）→ 补一次
  if (!auth.menusLoaded) {
    try {
      await auth.loadMenus()
    } catch {
      // 拉菜单失败通常是登录态失效，不阻塞跳转
    }
  }

  // 4) 路由级权限校验（仅界面层）
  const required = to.meta.permission
  if (required && !auth.has(required)) {
    ElMessage.warning(`没有访问「${to.meta.title || to.path}」的权限`)
    return { path: '/forbidden', query: { from: to.fullPath, need: required } }
  }

  return true
})

router.afterEach((to) => {
  document.title = to.meta.title
    ? `${to.meta.title} · 车辆智能调度 Agent`
    : '车辆智能调度 Agent'
})

export default router
