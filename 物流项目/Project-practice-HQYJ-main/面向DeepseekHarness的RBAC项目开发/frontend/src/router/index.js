/**
 * 路由定义与全局守卫。
 *
 * 前端有两道基于权限的界面控制，都只是**体验优化**：
 *   1. 路由级 —— meta.permission 声明该页面需要的权限点，守卫里拦截
 *   2. 菜单级 —— 侧边栏直接渲染 /api/me/menus 返回的树（后端已裁剪）
 *
 * ★ 两者都可以被绕过（改 localStorage、直接调接口），
 *   后端 authorize() 才是否决权所在。这一点在 README 与代码注释里都写明了。
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
        meta: { title: '工作台', icon: 'HomeFilled' },
        // 无 permission 声明 = 登录即可访问
      },
      {
        path: 'products',
        name: 'products',
        component: () => import('@/views/ProductsView.vue'),
        meta: { title: '商品管理', icon: 'Goods', permission: 'products:read' },
      },
      {
        path: 'orders',
        name: 'orders',
        component: () => import('@/views/OrdersView.vue'),
        meta: { title: '订单管理', icon: 'List', permission: 'orders:read' },
      },
      {
        path: 'reports',
        name: 'reports',
        component: () => import('@/views/ReportsView.vue'),
        meta: { title: '数据报表', icon: 'TrendCharts', permission: 'reports:view' },
      },
      {
        path: 'system/users',
        name: 'system-users',
        component: () => import('@/views/system/UsersView.vue'),
        meta: { title: '用户管理', icon: 'User', permission: 'users:manage' },
      },
      {
        path: 'system/roles',
        name: 'system-roles',
        component: () => import('@/views/system/RolesView.vue'),
        meta: { title: '角色管理', icon: 'Avatar', permission: 'users:manage' },
      },
      {
        path: 'system/permissions',
        name: 'system-permissions',
        component: () => import('@/views/system/PermissionsView.vue'),
        meta: { title: '权限点管理', icon: 'Key', permission: 'users:manage' },
      },
      {
        path: 'system/audit',
        name: 'system-audit',
        component: () => import('@/views/system/AuditView.vue'),
        meta: { title: '审计日志', icon: 'Document', permission: 'users:manage' },
      },
      {
        path: 'forbidden',
        name: 'forbidden',
        component: () => import('@/views/ForbiddenView.vue'),
        meta: { title: '无权访问' },
      },
      {
        // 命中未定义路径时给出明确提示，而不是白屏
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
    // 已登录用户访问登录页 → 直接回工作台
    if (to.name === 'login' && auth.isLoggedIn) return { path: '/dashboard' }
    return true
  }

  // 2) 未登录 → 去登录页，并记住原目标便于登录后跳回
  if (!auth.isLoggedIn) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }

  // 3) 菜单尚未加载（例如直接刷新子页面）→ 先补一次
  if (!auth.menusLoaded) {
    try {
      await auth.loadMenus()
    } catch {
      // 拉菜单失败通常是 Token 失效，交给 axios 拦截器处理，这里不阻塞跳转
    }
  }

  // 4) 路由级权限校验（仅界面层；后端才是最终防线）
  const required = to.meta.permission
  if (required && !auth.has(required)) {
    ElMessage.warning(`没有访问「${to.meta.title || to.path}」的权限`)
    return { path: '/forbidden', query: { from: to.fullPath, need: required } }
  }

  return true
})

router.afterEach((to) => {
  document.title = to.meta.title
    ? `${to.meta.title} · RBAC 权限管理系统`
    : 'RBAC 权限管理系统'
})

export default router
