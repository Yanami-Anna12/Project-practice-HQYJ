import { createRouter, createWebHashHistory } from 'vue-router'
import { useUserStore } from '@/stores/user'

const routes = [
  {
    path: '/login',
    name: 'login',
    component: () => import('@/views/Login.vue'),
    meta: { public: true, title: '登录' },
  },
  {
    path: '/',
    component: () => import('@/layouts/BasicLayout.vue'),
    redirect: '/dashboard',
    children: [
      {
        path: 'dashboard',
        name: 'dashboard',
        component: () => import('@/views/Dashboard.vue'),
        meta: { title: '首页看板', icon: 'DashboardOutlined' },
      },
      {
        path: 'work-orders',
        name: 'work-orders',
        component: () => import('@/views/WorkOrderList.vue'),
        meta: { title: '工单管理', icon: 'ProfileOutlined' },
      },
      {
        path: 'work-orders/:id',
        name: 'work-order-detail',
        component: () => import('@/views/WorkOrderDetail.vue'),
        meta: { title: '工单详情', hidden: true, activeMenu: '/work-orders' },
      },
      {
        path: 'tasks',
        name: 'tasks',
        component: () => import('@/views/TaskList.vue'),
        meta: { title: '作业管理', icon: 'ScheduleOutlined' },
      },
      {
        path: 'faults',
        name: 'faults',
        component: () => import('@/views/FaultList.vue'),
        meta: { title: '故障管理', icon: 'WarningOutlined' },
      },
      {
        path: 'faults/:id',
        name: 'fault-detail',
        component: () => import('@/views/FaultDetail.vue'),
        meta: { title: '故障详情', hidden: true, activeMenu: '/faults' },
      },
      {
        path: 'ledger',
        name: 'ledger',
        component: () => import('@/views/Ledger.vue'),
        meta: { title: '台账管理', icon: 'DatabaseOutlined' },
      },
      {
        path: 'statistics',
        name: 'statistics',
        component: () => import('@/views/Statistics.vue'),
        meta: { title: '统计分析', icon: 'BarChartOutlined' },
      },
      {
        path: 'messages',
        name: 'messages',
        component: () => import('@/views/Messages.vue'),
        meta: { title: '消息中心', icon: 'BellOutlined' },
      },
      {
        path: 'ai',
        name: 'ai',
        component: () => import('@/views/ai/AgentCenter.vue'),
        meta: { title: 'AI Agent 中心', icon: 'RobotOutlined' },
      },
      {
        path: 'ai/work-order',
        name: 'ai-work-order',
        component: () => import('@/views/ai/WorkOrderAgent.vue'),
        meta: { title: '智能工单调度', icon: 'ThunderboltOutlined' },
      },
      {
        path: 'ai/fault',
        name: 'ai-fault',
        component: () => import('@/views/ai/FaultDiagnosis.vue'),
        meta: { title: '智能故障诊断', icon: 'ExperimentOutlined' },
      },
      {
        path: 'ai/risk',
        name: 'ai-risk',
        component: () => import('@/views/ai/RiskControl.vue'),
        meta: { title: '智能风控', icon: 'SafetyOutlined' },
      },
      {
        path: 'ai/knowledge',
        name: 'ai-knowledge',
        component: () => import('@/views/ai/Knowledge.vue'),
        meta: { title: '知识库', icon: 'BookOutlined' },
      },
      {
        path: 'ai/tasks',
        name: 'ai-tasks',
        component: () => import('@/views/ai/AgentTasks.vue'),
        meta: { title: 'Agent 任务', icon: 'ClusterOutlined' },
      },
      {
        path: 'reports',
        name: 'reports',
        component: () => import('@/views/Reports.vue'),
        meta: { title: '运维报告', icon: 'FileTextOutlined' },
      },
      {
        path: 'reports/:id',
        name: 'report-detail',
        component: () => import('@/views/ReportDetail.vue'),
        meta: { title: '报告详情', hidden: true, activeMenu: '/reports' },
      },
      {
        path: 'system/users',
        name: 'system-users',
        component: () => import('@/views/system/Users.vue'),
        meta: { title: '用户管理', icon: 'TeamOutlined', permission: 'system:user' },
      },
      {
        path: 'system/roles',
        name: 'system-roles',
        component: () => import('@/views/system/Roles.vue'),
        meta: { title: '角色权限', icon: 'SafetyCertificateOutlined', permission: 'system:role' },
      },
      {
        path: 'system/configs',
        name: 'system-configs',
        component: () => import('@/views/system/Configs.vue'),
        meta: { title: '参数与规则', icon: 'SettingOutlined', permission: 'system:config' },
      },
      {
        path: 'system/logs',
        name: 'system-logs',
        component: () => import('@/views/system/Logs.vue'),
        meta: { title: '日志审计', icon: 'AuditOutlined', permission: 'system:log' },
      },
    ],
  },
  {
    path: '/:pathMatch(.*)*',
    name: 'not-found',
    component: () => import('@/views/NotFound.vue'),
    meta: { public: true, title: '页面不存在' },
  },
]

const router = createRouter({
  history: createWebHashHistory(),
  routes,
})

router.beforeEach(async (to) => {
  const store = useUserStore()
  if (to.meta.public) return true

  if (!store.token) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }
  if (!store.loaded) {
    try {
      await store.fetchProfile()
    } catch {
      await store.logout()
      return { name: 'login' }
    }
  }
  if (to.meta.permission && !store.hasPermission(to.meta.permission)) {
    return { name: 'dashboard' }
  }
  return true
})

router.afterEach((to) => {
  document.title = to.meta.title
    ? `${to.meta.title} · 充电桩运维 AI Agent`
    : '充电桩运维管理 AI Agent 平台'
})

export default router
