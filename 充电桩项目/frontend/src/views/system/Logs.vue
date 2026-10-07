<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h2 class="page-title"><AuditOutlined /> 日志审计</h2>
        <div class="page-subtitle">
          全量操作留痕与变更前后对比　·　登录轨迹溯源（PDF 8.4）
        </div>
      </div>
      <a-space>
        <a-button :loading="loading" @click="refresh">
          <template #icon><ReloadOutlined /></template>
          刷新
        </a-button>
      </a-space>
    </div>

    <a-tabs v-model:activeKey="activeTab" @change="onTabChange">
      <!-- ================================================ 操作日志 -->
      <a-tab-pane key="operations">
        <template #tab>
          <span><FileTextOutlined /> 操作日志</span>
        </template>

        <div class="filter-bar">
          <a-form layout="inline" :model="opQuery">
            <a-form-item label="模块">
              <a-select
                v-model:value="opQuery.module"
                style="width: 160px"
                allow-clear
                placeholder="全部模块"
                :options="MODULE_OPTIONS"
              />
            </a-form-item>
            <a-form-item label="操作人">
              <a-input
                v-model:value="opQuery.user_name"
                placeholder="姓名 / 用户名"
                style="width: 170px"
                allow-clear
                @press-enter="searchOps"
              >
                <template #prefix><SearchOutlined /></template>
              </a-input>
            </a-form-item>
            <a-form-item label="动作">
              <a-select
                v-model:value="opQuery.action"
                style="width: 180px"
                allow-clear
                show-search
                option-filter-prop="label"
                placeholder="全部动作"
                :options="ACTION_OPTIONS"
              />
            </a-form-item>
            <a-form-item>
              <a-space>
                <a-button type="primary" :loading="loading" @click="searchOps">查询</a-button>
                <a-button @click="resetOps">重置</a-button>
              </a-space>
            </a-form-item>
          </a-form>
        </div>

        <a-card :bordered="false">
          <a-table
            :columns="opColumns"
            :data-source="opRows"
            :loading="loading"
            row-key="id"
            size="middle"
            :scroll="{ x: 1360 }"
            :pagination="opPagination"
            :expanded-row-keys="opExpandedKeys"
            :expand-column-width="110"
            @change="onOpTableChange"
            @expand="onOpExpand"
          >
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'created_at'">
                <span class="mono" style="font-size: 12px">{{ fmtTime(record.created_at) }}</span>
              </template>

              <template v-else-if="column.key === 'user_name'">
                <a-tag color="blue">{{ record.user_name || '系统' }}</a-tag>
              </template>

              <template v-else-if="column.key === 'module'">
                {{ record.module || '-' }}
              </template>

              <template v-else-if="column.key === 'action'">
                <a-tag :color="actionColor(record.action)">{{ record.action || '-' }}</a-tag>
              </template>

              <template v-else-if="column.key === 'target'">
                <template v-if="record.target_type">
                  <div>{{ record.target_type }}</div>
                  <div class="mono text-muted" style="font-size: 12px">
                    {{ shortId(record.target_id) }}
                  </div>
                </template>
                <span v-else class="text-muted">-</span>
              </template>

              <template v-else-if="column.key === 'description'">
                <span style="font-size: 12px">{{ record.description || '-' }}</span>
              </template>

              <template v-else-if="column.key === 'ip'">
                <span class="mono" style="font-size: 12px">{{ record.ip || '-' }}</span>
                <div v-if="record.method || record.path" class="mono text-muted" style="font-size: 12px">
                  {{ record.method }} {{ record.path }}
                </div>
              </template>

              <template v-else-if="column.key === 'duration_ms'">
                <a-tag :color="durationColor(record.duration_ms)">
                  {{ record.duration_ms ?? '-' }} ms
                </a-tag>
              </template>

              <template v-else-if="column.key === 'status_code'">
                <a-tag :color="record.status_code >= 400 ? 'red' : 'green'">
                  {{ record.status_code ?? '-' }}
                </a-tag>
              </template>

              <template v-else-if="column.key === 'action_col'">
                <a v-if="hasChange(record)" @click="toggleOpExpand(record)">
                  {{ isOpExpanded(record.id) ? '收起对比' : '变更前后' }}
                </a>
                <span v-else class="text-muted" style="font-size: 12px">无变更数据</span>
              </template>
            </template>

            <!-- 变更前后 JSON 对比 -->
            <template #expandedRowRender="{ record }">
              <div class="diff-wrap">
                <div class="diff-col">
                  <div class="diff-title danger">变更前</div>
                  <div class="ai-trace">{{ prettyJson(record.before) }}</div>
                </div>
                <div class="diff-col">
                  <div class="diff-title success">变更后</div>
                  <div class="ai-trace">{{ prettyJson(record.after) }}</div>
                </div>
              </div>
            </template>
          </a-table>
        </a-card>
      </a-tab-pane>

      <!-- ================================================ 登录日志 -->
      <a-tab-pane key="logins">
        <template #tab>
          <span><LoginOutlined /> 登录日志</span>
        </template>

        <a-card :bordered="false">
          <a-table
            :columns="loginColumns"
            :data-source="loginRows"
            :loading="loading"
            row-key="id"
            size="middle"
            :scroll="{ x: 1120 }"
            :pagination="loginPagination"
            @change="onLoginTableChange"
          >
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'created_at'">
                <span class="mono" style="font-size: 12px">{{ fmtTime(record.created_at) }}</span>
              </template>

              <template v-else-if="column.key === 'user_name'">
                <a-tag color="blue">{{ record.user_name || '未知账号' }}</a-tag>
              </template>

              <template v-else-if="column.key === 'login_type'">
                <a-tag :color="record.login_type === '微信' ? 'green' : 'geekblue'">
                  {{ record.login_type || '账号密码' }}
                </a-tag>
              </template>

              <template v-else-if="column.key === 'success'">
                <a-badge
                  :status="record.success ? 'success' : 'error'"
                  :text="record.success ? '登录成功' : '登录失败'"
                />
              </template>

              <template v-else-if="column.key === 'message'">
                <span style="font-size: 12px" :class="record.success ? '' : 'text-danger'">
                  {{ record.message || '-' }}
                </span>
              </template>

              <template v-else-if="column.key === 'ip'">
                <span class="mono" style="font-size: 12px">{{ record.ip || '-' }}</span>
              </template>

              <template v-else-if="column.key === 'user_agent'">
                <a-tooltip :title="record.user_agent || ''">
                  <span class="text-muted" style="font-size: 12px">
                    {{ shortUa(record.user_agent) }}
                  </span>
                </a-tooltip>
              </template>
            </template>
          </a-table>
        </a-card>
      </a-tab-pane>
    </a-tabs>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import {
  AuditOutlined,
  FileTextOutlined,
  LoginOutlined,
  ReloadOutlined,
  SearchOutlined,
} from '@ant-design/icons-vue'
import { adminApi } from '@/api'

const activeTab = ref('operations')
const loading = ref(false)

/** 操作日志模块筛选（与后端审计写入的 module 取值一致） */
const MODULE_OPTIONS = [
  '用户管理',
  '角色管理',
  '系统参数',
  '工单管理',
  '作业管理',
  '巡检管理',
  '故障管理',
  '台账管理',
  'AI Agent 中心',
  '导出管理',
  '个人中心',
  '认证',
].map((m) => ({ label: m, value: m }))

const ACTION_OPTIONS = [
  '新增用户',
  '编辑用户',
  '删除用户',
  '新增角色',
  '编辑角色',
  '删除角色',
  '修改参数',
  '同步台账',
  '修改站点扩展字段',
  '工单申请',
  '编辑工单',
  '接受工单',
  '退回工单',
  '取消工单',
  '重新下发工单',
  '工单导出',
  '巡检录入',
  '更新子任务',
  '故障上报',
  '故障核查',
  '人工确认',
  '异常重排',
  '新增知识库文档',
  '智能故障诊断',
  '智能巡检报告',
  '智能风控检查',
  '智能报告生成',
  '报告推送',
  '修改资料',
  '修改密码',
  '退出登录',
].map((a) => ({ label: a, value: a }))

// ---------------------------------------------------------------- 操作日志
const opRows = ref([])
const opTotal = ref(0)
const opExpandedKeys = ref([])

const opQuery = reactive({
  module: undefined,
  user_name: '',
  action: undefined,
  page: 1,
  page_size: 20,
})

const opColumns = [
  { title: '时间', key: 'created_at', width: 165, fixed: 'left' },
  { title: '操作人', key: 'user_name', width: 120 },
  { title: '模块', key: 'module', width: 130 },
  { title: '动作', key: 'action', width: 150 },
  { title: '目标对象', key: 'target', width: 160 },
  { title: '操作说明', key: 'description', width: 240 },
  { title: 'IP / 接口', key: 'ip', width: 220 },
  { title: '耗时', key: 'duration_ms', width: 100 },
  { title: '状态码', key: 'status_code', width: 90 },
  { title: '操作', key: 'action_col', width: 110, fixed: 'right' },
]

const opPagination = computed(() => ({
  current: opQuery.page,
  pageSize: opQuery.page_size,
  total: opTotal.value,
  showSizeChanger: true,
  showTotal: (t) => `共 ${t} 条`,
}))

// ---------------------------------------------------------------- 登录日志
const loginRows = ref([])
const loginTotal = ref(0)
const loginQuery = reactive({ page: 1, page_size: 20 })

const loginColumns = [
  { title: '登录时间', key: 'created_at', width: 170, fixed: 'left' },
  { title: '账号', key: 'user_name', width: 140 },
  { title: '登录方式', key: 'login_type', width: 110 },
  { title: '结果', key: 'success', width: 120 },
  { title: '说明', key: 'message', width: 240 },
  { title: 'IP 地址', key: 'ip', width: 150 },
  { title: '客户端', key: 'user_agent' },
]

const loginPagination = computed(() => ({
  current: loginQuery.page,
  pageSize: loginQuery.page_size,
  total: loginTotal.value,
  showSizeChanger: true,
  showTotal: (t) => `共 ${t} 条`,
}))

// ---------------------------------------------------------------- 展示辅助
function fmtTime(v) {
  if (!v) return '-'
  return String(v).replace('T', ' ').slice(0, 19)
}
function shortId(id) {
  if (!id) return '-'
  return id.length > 14 ? `${id.slice(0, 8)}…${id.slice(-4)}` : id
}
function shortUa(ua) {
  if (!ua) return '-'
  return ua.length > 46 ? `${ua.slice(0, 46)}…` : ua
}
function actionColor(action) {
  if (!action) return 'default'
  if (action.startsWith('删除') || action.includes('取消')) return 'red'
  if (action.startsWith('新增') || action.includes('创建')) return 'green'
  if (action.startsWith('编辑') || action.startsWith('修改')) return 'orange'
  return 'blue'
}
function durationColor(ms) {
  if (ms === null || ms === undefined) return 'default'
  if (ms >= 1000) return 'red'
  if (ms >= 300) return 'orange'
  return 'green'
}
/** 无变更快照时不展示展开入口 */
function hasChange(record) {
  return Boolean(record.before || record.after)
}
function isOpExpanded(id) {
  return opExpandedKeys.value.includes(id)
}
function toggleOpExpand(record) {
  opExpandedKeys.value = isOpExpanded(record.id)
    ? opExpandedKeys.value.filter((k) => k !== record.id)
    : [...opExpandedKeys.value, record.id]
}
function onOpExpand(expanded, record) {
  opExpandedKeys.value = expanded
    ? [...opExpandedKeys.value, record.id]
    : opExpandedKeys.value.filter((k) => k !== record.id)
}
function prettyJson(v) {
  if (v === null || v === undefined || v === '') return '（无）'
  if (typeof v === 'string') {
    try {
      return JSON.stringify(JSON.parse(v), null, 2)
    } catch {
      return v
    }
  }
  try {
    return JSON.stringify(v, null, 2)
  } catch {
    return String(v)
  }
}

// ---------------------------------------------------------------- 数据加载
async function loadOperations() {
  loading.value = true
  try {
    const params = { page: opQuery.page, page_size: opQuery.page_size }
    if (opQuery.module) params.module = opQuery.module
    if (opQuery.action) params.action = opQuery.action
    if (opQuery.user_name) params.user_name = opQuery.user_name
    const res = await adminApi.operationLogs(params)
    opRows.value = res.data?.items || []
    opTotal.value = res.data?.meta?.total || 0
  } finally {
    loading.value = false
  }
}

async function loadLogins() {
  loading.value = true
  try {
    const res = await adminApi.loginLogs({
      page: loginQuery.page,
      page_size: loginQuery.page_size,
    })
    loginRows.value = res.data?.items || []
    loginTotal.value = res.data?.meta?.total || 0
  } finally {
    loading.value = false
  }
}

function searchOps() {
  opQuery.page = 1
  opExpandedKeys.value = []
  loadOperations()
}

function resetOps() {
  Object.assign(opQuery, {
    module: undefined,
    user_name: '',
    action: undefined,
    page: 1,
  })
  opExpandedKeys.value = []
  loadOperations()
}

function onOpTableChange(pag) {
  opQuery.page = pag.current
  opQuery.page_size = pag.pageSize
  loadOperations()
}

function onLoginTableChange(pag) {
  loginQuery.page = pag.current
  loginQuery.page_size = pag.pageSize
  loadLogins()
}

function onTabChange(key) {
  if (key === 'logins' && !loginRows.value.length) loadLogins()
  if (key === 'operations' && !opRows.value.length) loadOperations()
}

function refresh() {
  if (activeTab.value === 'logins') loadLogins()
  else loadOperations()
}

onMounted(loadOperations)
</script>

<style scoped>
.diff-wrap {
  display: flex;
  gap: 14px;
  flex-wrap: wrap;
}

.diff-col {
  flex: 1 1 320px;
  min-width: 280px;
}

.diff-title {
  font-size: 12px;
  font-weight: 600;
  margin-bottom: 6px;
}

.diff-title.danger {
  color: #f5222d;
}

.diff-title.success {
  color: #52c41a;
}
</style>
