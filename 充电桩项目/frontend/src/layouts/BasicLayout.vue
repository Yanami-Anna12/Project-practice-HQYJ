<template>
  <a-layout style="min-height: 100vh">
    <!-- ---------------- 侧边导航 ---------------- -->
    <a-layout-sider
      v-model:collapsed="collapsed"
      :trigger="null"
      collapsible
      :width="216"
      theme="dark"
      class="sider"
    >
      <div class="logo">
        <span class="logo-icon">⚡</span>
        <span v-show="!collapsed" class="logo-text">充电桩运维 AI Agent</span>
      </div>

      <a-menu
        v-model:selectedKeys="selectedKeys"
        v-model:openKeys="openKeys"
        theme="dark"
        mode="inline"
      >
        <template v-for="group in menuGroups" :key="group.key">
          <a-menu-item
            v-if="group.children.length === 1"
            :key="group.children[0].path"
            @click="goTo(group.children[0].path)"
          >
            <component :is="group.children[0].icon" />
            <span>{{ group.children[0].title }}</span>
          </a-menu-item>

          <a-sub-menu v-else :key="group.key">
            <template #title>
              <component :is="group.icon" />
              <span>{{ group.title }}</span>
            </template>
            <a-menu-item
              v-for="item in group.children"
              :key="item.path"
              @click="goTo(item.path)"
            >
              <component :is="item.icon" />
              <span>{{ item.title }}</span>
            </a-menu-item>
          </a-sub-menu>
        </template>
      </a-menu>
    </a-layout-sider>

    <a-layout>
      <!-- ---------------- 顶部栏 ---------------- -->
      <a-layout-header class="header">
        <div class="header-left">
          <MenuUnfoldOutlined v-if="collapsed" class="trigger" @click="collapsed = false" />
          <MenuFoldOutlined v-else class="trigger" @click="collapsed = true" />
          <a-breadcrumb style="margin-left: 14px">
            <a-breadcrumb-item>运维平台</a-breadcrumb-item>
            <a-breadcrumb-item>{{ currentTitle }}</a-breadcrumb-item>
          </a-breadcrumb>
        </div>

        <div class="header-right">
          <a-tooltip :title="`AI 状态：${aiStatus.text}`">
            <a-tag :color="aiStatus.color" style="margin-right: 6px">
              <RobotOutlined />
              {{ aiStatus.tag }}
            </a-tag>
          </a-tooltip>

          <a-tooltip :title="`数据权限：${store.dataScope}`">
            <a-tag color="blue" style="margin-right: 10px">{{ store.dataScope }}</a-tag>
          </a-tooltip>

          <a-badge :count="unread" :overflow-count="99" size="small">
            <BellOutlined class="header-icon" @click="router.push('/messages')" />
          </a-badge>

          <a-dropdown>
            <div class="user-box">
              <a-avatar :size="30" style="background: #2f6fb5">
                {{ store.displayName.slice(0, 1) }}
              </a-avatar>
              <span class="user-name">{{ store.displayName }}</span>
              <DownOutlined style="font-size: 11px" />
            </div>
            <template #overlay>
              <a-menu>
                <a-menu-item key="profile" @click="profileOpen = true">
                  <UserOutlined /> 个人中心
                </a-menu-item>
                <a-menu-item key="docs" @click="openDocs">
                  <ApiOutlined /> 接口文档
                </a-menu-item>
                <a-menu-divider />
                <a-menu-item key="logout" @click="onLogout">
                  <LogoutOutlined /> 退出登录
                </a-menu-item>
              </a-menu>
            </template>
          </a-dropdown>
        </div>
      </a-layout-header>

      <a-layout-content class="content">
        <router-view v-slot="{ Component }">
          <keep-alive :max="6">
            <component :is="Component" :key="route.fullPath" />
          </keep-alive>
        </router-view>
      </a-layout-content>
    </a-layout>

    <!-- ---------------- 个人中心 ---------------- -->
    <a-modal
      v-model:open="profileOpen"
      title="个人中心"
      :footer="null"
      width="480px"
    >
      <a-descriptions :column="1" bordered size="small">
        <a-descriptions-item label="用户名">{{ store.user?.username }}</a-descriptions-item>
        <a-descriptions-item label="姓名">{{ store.user?.real_name }}</a-descriptions-item>
        <a-descriptions-item label="手机号">{{ store.user?.phone || '-' }}</a-descriptions-item>
        <a-descriptions-item label="邮箱">{{ store.user?.email || '-' }}</a-descriptions-item>
        <a-descriptions-item label="角色">
          {{ store.role?.name || '-' }}
        </a-descriptions-item>
        <a-descriptions-item label="数据权限">
          <a-tag color="blue">{{ store.dataScope }}</a-tag>
        </a-descriptions-item>
        <a-descriptions-item label="所属项目">
          {{ store.user?.project_name || '-' }}
        </a-descriptions-item>
        <a-descriptions-item label="所属站点">
          {{ store.user?.station_name || '-' }}
        </a-descriptions-item>
        <a-descriptions-item label="权限数量">
          {{ store.permissions.length }} 项
        </a-descriptions-item>
      </a-descriptions>

      <a-divider style="margin: 18px 0 12px">修改密码</a-divider>
      <a-form layout="vertical" :model="pwdForm">
        <a-form-item label="原密码">
          <a-input-password v-model:value="pwdForm.old_password" />
        </a-form-item>
        <a-form-item label="新密码（至少 6 位）">
          <a-input-password v-model:value="pwdForm.new_password" />
        </a-form-item>
        <a-button type="primary" block :loading="pwdLoading" @click="changePwd">
          确认修改
        </a-button>
      </a-form>
    </a-modal>
  </a-layout>
</template>

<script setup>
import { computed, h, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Modal, message } from 'ant-design-vue'
import {
  ApiOutlined,
  AuditOutlined,
  BarChartOutlined,
  BellOutlined,
  BookOutlined,
  ClusterOutlined,
  DashboardOutlined,
  DatabaseOutlined,
  DownOutlined,
  ExperimentOutlined,
  FileTextOutlined,
  LogoutOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  ProfileOutlined,
  RobotOutlined,
  SafetyCertificateOutlined,
  SafetyOutlined,
  ScheduleOutlined,
  SettingOutlined,
  TeamOutlined,
  ThunderboltOutlined,
  UserOutlined,
  WarningOutlined,
} from '@ant-design/icons-vue'
import { aiApi, authApi, messageApi } from '@/api'
import { useUserStore } from '@/stores/user'

const route = useRoute()
const router = useRouter()
const store = useUserStore()

const collapsed = ref(false)
const selectedKeys = ref([route.path])
const unread = ref(0)
const profileOpen = ref(false)
const pwdLoading = ref(false)
const pwdForm = reactive({ old_password: '', new_password: '' })
const aiStatus = reactive({ tag: 'AI 检测中', color: 'default', text: '' })

const ICONS = {
  DashboardOutlined,
  ProfileOutlined,
  ScheduleOutlined,
  WarningOutlined,
  DatabaseOutlined,
  BarChartOutlined,
  BellOutlined,
  RobotOutlined,
  FileTextOutlined,
  TeamOutlined,
  SafetyCertificateOutlined,
  SettingOutlined,
  AuditOutlined,
  ThunderboltOutlined,
  ExperimentOutlined,
  SafetyOutlined,
  BookOutlined,
  ClusterOutlined,
}

/** 按 PDF 3.1 模块总览组织菜单 */
const MENU_DEF = [
  { key: 'board', title: '首页看板', icon: 'DashboardOutlined', children: [{ path: '/dashboard', title: '首页看板', icon: 'DashboardOutlined' }] },
  {
    key: 'order',
    title: '工单与作业',
    icon: 'ProfileOutlined',
    children: [
      { path: '/work-orders', title: '工单管理', icon: 'ProfileOutlined' },
      { path: '/tasks', title: '作业管理', icon: 'ScheduleOutlined' },
    ],
  },
  {
    key: 'fault',
    title: '故障与台账',
    icon: 'WarningOutlined',
    children: [
      { path: '/faults', title: '故障管理', icon: 'WarningOutlined' },
      { path: '/ledger', title: '台账管理', icon: 'DatabaseOutlined' },
    ],
  },
  {
    key: 'data',
    title: '统计与消息',
    icon: 'BarChartOutlined',
    children: [
      { path: '/statistics', title: '统计分析', icon: 'BarChartOutlined' },
      { path: '/messages', title: '消息中心', icon: 'BellOutlined' },
    ],
  },
  {
    key: '/ai',
    title: 'AI Agent 中心',
    icon: 'RobotOutlined',
    children: [
      { path: '/ai', title: 'Agent 概览', icon: 'RobotOutlined' },
      { path: '/ai/work-order', title: '智能工单调度', icon: 'ThunderboltOutlined' },
      { path: '/ai/fault', title: '智能故障诊断', icon: 'ExperimentOutlined' },
      { path: '/ai/risk', title: '智能风控', icon: 'SafetyOutlined' },
      { path: '/ai/knowledge', title: '知识库 RAG', icon: 'BookOutlined' },
      { path: '/ai/tasks', title: 'Agent 任务', icon: 'ClusterOutlined' },
    ],
  },
  { key: 'report', title: '运维报告', icon: 'FileTextOutlined', children: [{ path: '/reports', title: '运维分析报告', icon: 'FileTextOutlined' }] },
  {
    key: '/system',
    title: '系统管理',
    icon: 'SettingOutlined',
    children: [
      { path: '/system/users', title: '用户管理', icon: 'TeamOutlined', permission: 'system:user' },
      { path: '/system/roles', title: '角色权限', icon: 'SafetyCertificateOutlined', permission: 'system:role' },
      { path: '/system/configs', title: '参数与规则', icon: 'SettingOutlined', permission: 'system:config' },
      { path: '/system/logs', title: '日志审计', icon: 'AuditOutlined', permission: 'system:log' },
    ],
  },
]

// 侧边菜单默认全部展开。
// 原来写死 ['/ai', '/system']，而 MENU_DEF 里其余分组的 key 是
// 'board' / 'order' / 'fault' / 'data'，对不上就会保持折叠 ——
// 折叠状态下子菜单项高度为 0，鼠标点不到，表现为「菜单点不了」。
// 改为从 MENU_DEF 推导，以后增删分组不会再漏配。
const openKeys = ref(MENU_DEF.map((g) => g.key))

const menuGroups = computed(() =>
  MENU_DEF.map((group) => ({
    ...group,
    icon: ICONS[group.icon] || DashboardOutlined,
    children: group.children
      .filter((c) => !c.permission || store.hasPermission(c.permission))
      .map((c) => ({ ...c, icon: ICONS[c.icon] || DashboardOutlined })),
  })).filter((g) => g.children.length > 0),
)

const currentTitle = computed(() => route.meta?.title || '')

/** 侧边菜单跳转。原来只绑了 selectedKeys 而没有点击处理，
 *  点菜单只会高亮、不会切路由，看起来就像「点不动」。 */
function goTo(path) {
  if (!path || path === route.path) return
  // 同一路径重复点击会抛 NavigationDuplicated，这里提前挡掉
  router.push(path).catch(() => {})
}

watch(
  () => route.path,
  (p) => {
    selectedKeys.value = [route.meta?.activeMenu || p]
  },
  { immediate: true },
)

async function loadUnread() {
  try {
    const res = await messageApi.list({ page: 1, page_size: 1 })
    unread.value = res.data?.unread_count || 0
  } catch {
    /* 忽略 */
  }
}

async function loadAiStatus() {
  try {
    const res = await aiApi.health()
    const d = res.data || {}
    if (d.status === 'ok') {
      aiStatus.tag = `LLM 在线 · ${d.model}`
      aiStatus.color = 'green'
      aiStatus.text = '大模型可用，报告与根因分析走 LLM 增强'
    } else {
      aiStatus.tag = '规则引擎模式'
      aiStatus.color = 'orange'
      aiStatus.text = d.detail || '未配置 LLM_API_KEY，使用确定性规则引擎降级输出'
    }
  } catch {
    aiStatus.tag = 'AI 不可用'
    aiStatus.color = 'default'
    aiStatus.text = '无法获取 AI 状态'
  }
}

async function changePwd() {
  if (!pwdForm.old_password || !pwdForm.new_password) {
    message.warning('请填写完整')
    return
  }
  pwdLoading.value = true
  try {
    await authApi.changePassword({ ...pwdForm })
    message.success('密码已修改，请重新登录')
    pwdForm.old_password = ''
    pwdForm.new_password = ''
    profileOpen.value = false
    await store.logout()
    router.replace('/login')
  } catch {
    /* 已提示 */
  } finally {
    pwdLoading.value = false
  }
}

function openDocs() {
  // 后端地址可由 VITE_API_TARGET 覆盖（默认 8010，避免与同机其他项目端口冲突）
  const target = import.meta.env.VITE_API_TARGET || 'http://127.0.0.1:8010'
  window.open(`${target}/docs`, '_blank')
}

function onLogout() {
  Modal.confirm({
    title: '确认退出登录？',
    onOk: async () => {
      await store.logout()
      router.replace('/login')
    },
  })
}

let timer = null
onMounted(() => {
  loadUnread()
  loadAiStatus()
  timer = setInterval(loadUnread, 30000)
})
onUnmounted(() => {
  if (timer) clearInterval(timer)
})
</script>

<style scoped>
.sider {
  background: #1f2a37 !important;
}

.logo {
  height: 56px;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 16px;
  color: #fff;
  font-weight: 600;
  font-size: 14px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  white-space: nowrap;
  overflow: hidden;
}

.logo-icon {
  font-size: 18px;
}

.header {
  background: #fff;
  padding: 0 18px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.06);
  height: 56px;
  line-height: 56px;
}

.header-left,
.header-right {
  display: flex;
  align-items: center;
}

.trigger {
  font-size: 17px;
  cursor: pointer;
  color: #1f2329;
}

.header-icon {
  font-size: 17px;
  cursor: pointer;
  color: #1f2329;
  margin-right: 20px;
}

.user-box {
  display: flex;
  align-items: center;
  gap: 7px;
  cursor: pointer;
  padding: 0 6px;
}

.user-name {
  font-size: 13px;
  max-width: 110px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.content {
  padding: 0;
  overflow-y: auto;
  background: #f0f2f5;
}
</style>
