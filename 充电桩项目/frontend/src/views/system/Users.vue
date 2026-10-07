<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h2 class="page-title"><TeamOutlined /> 用户管理</h2>
        <div class="page-subtitle">
          账号 ↔ 角色 ↔ 项目 / 站点 绑定　·　数据权限由角色决定（PDF 3.3）
        </div>
      </div>
      <a-space>
        <a-button :loading="loading" @click="load">
          <template #icon><ReloadOutlined /></template>
          刷新
        </a-button>
        <a-button type="primary" @click="openCreate">
          <template #icon><PlusOutlined /></template>
          新增用户
        </a-button>
      </a-space>
    </div>

    <!-- ---------------- 筛选条件 ---------------- -->
    <div class="filter-bar">
      <a-form layout="inline" :model="query">
        <a-form-item label="模糊查询">
          <a-input
            v-model:value="query.keyword"
            placeholder="用户名 / 姓名 / 手机号"
            style="width: 210px"
            allow-clear
            @press-enter="search"
          >
            <template #prefix><SearchOutlined /></template>
          </a-input>
        </a-form-item>
        <a-form-item label="所属项目">
          <a-select
            v-model:value="query.project_id"
            style="width: 180px"
            allow-clear
            placeholder="全部项目"
            :options="projectOptions"
            :field-names="{ label: 'name', value: 'id' }"
            @change="onQueryProjectChange"
          />
        </a-form-item>
        <a-form-item label="所属站点">
          <a-select
            v-model:value="query.station_id"
            style="width: 180px"
            allow-clear
            placeholder="全部站点"
            :options="queryStations"
            :field-names="{ label: 'name', value: 'id' }"
          />
        </a-form-item>
        <a-form-item label="角色">
          <a-select
            v-model:value="query.role_id"
            style="width: 150px"
            allow-clear
            placeholder="全部角色"
            :options="roles"
            :field-names="{ label: 'name', value: 'id' }"
          />
        </a-form-item>
        <a-form-item label="状态">
          <a-select v-model:value="query.status" style="width: 110px" allow-clear placeholder="全部">
            <a-select-option value="true">启用</a-select-option>
            <a-select-option value="false">停用</a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item>
          <a-space>
            <a-button type="primary" :loading="loading" @click="search">查询</a-button>
            <a-button @click="reset">重置</a-button>
          </a-space>
        </a-form-item>
      </a-form>
    </div>

    <!-- ---------------- 用户列表 ---------------- -->
    <a-card :bordered="false">
      <a-table
        :columns="columns"
        :data-source="rows"
        :loading="loading"
        row-key="id"
        size="middle"
        :scroll="{ x: 1360 }"
        :pagination="pagination"
        @change="onTableChange"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'account'">
            <div style="font-weight: 600">{{ record.username }}</div>
            <div class="text-muted" style="font-size: 12px">{{ record.real_name }}</div>
          </template>

          <template v-else-if="column.key === 'phone'">
            {{ record.phone || '-' }}
            <div v-if="record.email" class="text-muted" style="font-size: 12px">
              {{ record.email }}
            </div>
          </template>

          <template v-else-if="column.key === 'org'">
            <div>{{ record.project_name || '-' }}</div>
            <div class="text-muted" style="font-size: 12px">
              {{ record.station_name || '未绑定站点' }}
            </div>
          </template>

          <template v-else-if="column.key === 'role'">
            <a-tag color="blue">{{ record.role?.name || '未分配' }}</a-tag>
            <div class="text-muted" style="font-size: 12px">{{ scopeLabel(record.data_scope) }}</div>
          </template>

          <template v-else-if="column.key === 'user_type'">
            <a-tag :color="userTypeColor(record.user_type)">{{ userTypeText(record.user_type) }}</a-tag>
          </template>

          <template v-else-if="column.key === 'status'">
            <a-badge
              :status="record.status ? 'success' : 'default'"
              :text="record.status ? '启用' : '停用'"
            />
          </template>

          <template v-else-if="column.key === 'last_login_at'">
            <span class="mono" style="font-size: 12px">{{ fmtTime(record.last_login_at) }}</span>
          </template>

          <template v-else-if="column.key === 'action'">
            <a-space size="small">
              <a @click="openEdit(record)">编辑</a>
              <a @click="toggleStatus(record)">{{ record.status ? '停用' : '启用' }}</a>
              <a @click="openResetPwd(record)">重置密码</a>
              <a
                class="text-danger"
                :class="{ disabled: record.username === 'admin' }"
                @click="removeUser(record)"
              >
                删除
              </a>
            </a-space>
          </template>
        </template>
      </a-table>
    </a-card>

    <!-- ---------------- 新增 / 编辑用户 ---------------- -->
    <a-modal
      v-model:open="formOpen"
      :title="form.id ? '编辑用户' : '新增用户'"
      width="680px"
      :confirm-loading="submitting"
      @ok="submitForm"
    >
      <a-form ref="formRef" :model="form" :rules="rules" layout="vertical">
        <a-row :gutter="16">
          <a-col :span="12">
            <a-form-item label="用户名" name="username">
              <a-input
                v-model:value="form.username"
                :disabled="Boolean(form.id)"
                placeholder="登录账号，2-64 位"
              />
            </a-form-item>
          </a-col>
          <a-col :span="12">
            <a-form-item label="姓名" name="real_name">
              <a-input v-model:value="form.real_name" placeholder="真实姓名" />
            </a-form-item>
          </a-col>

          <a-col :span="12">
            <a-form-item label="手机号" name="phone">
              <a-input v-model:value="form.phone" placeholder="11 位手机号" allow-clear />
            </a-form-item>
          </a-col>
          <a-col :span="12">
            <a-form-item label="邮箱" name="email">
              <a-input v-model:value="form.email" placeholder="选填" allow-clear />
            </a-form-item>
          </a-col>

          <a-col :span="12">
            <a-form-item label="所属项目" name="project_id">
              <a-select
                v-model:value="form.project_id"
                allow-clear
                placeholder="选择项目"
                :options="projectOptions"
                :field-names="{ label: 'name', value: 'id' }"
                @change="onFormProjectChange($event)"
              />
            </a-form-item>
          </a-col>
          <a-col :span="12">
            <a-form-item label="所属站点" name="station_id">
              <a-select
                v-model:value="form.station_id"
                allow-clear
                :disabled="!form.project_id"
                :placeholder="form.project_id ? '按项目联动显示站点' : '请先选择项目'"
                :options="formStations"
                :field-names="{ label: 'name', value: 'id' }"
                :loading="stationLoading"
              />
            </a-form-item>
          </a-col>

          <a-col :span="12">
            <a-form-item label="角色" name="role_id">
              <a-select
                v-model:value="form.role_id"
                allow-clear
                placeholder="选择角色（决定数据权限）"
                :options="roles"
                :field-names="{ label: 'name', value: 'id' }"
              />
            </a-form-item>
          </a-col>
          <a-col :span="12">
            <a-form-item label="用户类型" name="user_type">
              <a-select v-model:value="form.user_type">
                <a-select-option value="admin">后台账号</a-select-option>
                <a-select-option value="staff">运维人员</a-select-option>
                <a-select-option value="miniapp">小程序用户</a-select-option>
              </a-select>
            </a-form-item>
          </a-col>

          <a-col v-if="!form.id" :span="12">
            <a-form-item label="初始密码" name="password">
              <a-input-password v-model:value="form.password" placeholder="至少 6 位" />
            </a-form-item>
          </a-col>
          <a-col :span="12">
            <a-form-item label="技能标签">
              <a-input v-model:value="form.skills" placeholder="例如：电气,通信（逗号分隔）" allow-clear />
            </a-form-item>
          </a-col>

          <a-col :span="12">
            <a-form-item label="账号状态">
              <a-switch
                v-model:checked="form.status"
                checked-children="启用"
                un-checked-children="停用"
              />
            </a-form-item>
          </a-col>
          <a-col v-if="form.id" :span="12">
            <a-form-item label="是否在岗（派单约束）">
              <a-switch v-model:checked="form.on_duty" checked-children="在岗" un-checked-children="离岗" />
            </a-form-item>
          </a-col>
        </a-row>
      </a-form>
    </a-modal>

    <!-- ---------------- 重置密码 ---------------- -->
    <a-modal
      v-model:open="pwdOpen"
      title="重置密码"
      :confirm-loading="pwdLoading"
      @ok="submitResetPwd"
    >
      <a-alert
        type="warning"
        show-icon
        style="margin-bottom: 14px"
        :message="`即将重置「${pwdTarget?.real_name || ''}（${pwdTarget?.username || ''}）」的登录密码`"
      />
      <a-form layout="vertical">
        <a-form-item label="新密码（至少 6 位）" required>
          <a-input-password v-model:value="pwdValue" placeholder="请输入新密码" />
        </a-form-item>
      </a-form>
    </a-modal>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { Modal, message } from 'ant-design-vue'
import {
  PlusOutlined,
  ReloadOutlined,
  SearchOutlined,
  TeamOutlined,
} from '@ant-design/icons-vue'
import { adminApi } from '@/api'

const loading = ref(false)
const rows = ref([])
const total = ref(0)
const projects = ref([])
const roles = ref([])

/** 列表筛选：所属站点随项目联动 */
const query = reactive({
  keyword: '',
  project_id: undefined,
  station_id: undefined,
  role_id: undefined,
  status: undefined,
  page: 1,
  page_size: 20,
})
const queryStations = ref([])

const projectOptions = computed(() => projects.value)

const pagination = computed(() => ({
  current: query.page,
  pageSize: query.page_size,
  total: total.value,
  showSizeChanger: true,
  showTotal: (t) => `共 ${t} 条`,
}))

const columns = [
  { title: '用户名 / 姓名', key: 'account', width: 160, fixed: 'left' },
  { title: '手机号 / 邮箱', key: 'phone', width: 180 },
  { title: '所属项目 / 站点', key: 'org', width: 220 },
  { title: '角色 / 数据权限', key: 'role', width: 170 },
  { title: '用户类型', key: 'user_type', width: 110 },
  { title: '状态', key: 'status', width: 100 },
  { title: '最近登录', key: 'last_login_at', width: 160 },
  { title: '操作', key: 'action', width: 220, fixed: 'right' },
]

// ---------------------------------------------------------------- 展示辅助
const USER_TYPE = { admin: '后台账号', staff: '运维人员', miniapp: '小程序用户' }

function userTypeText(t) {
  return USER_TYPE[t] || t || '-'
}
function userTypeColor(t) {
  return { admin: 'blue', staff: 'green', miniapp: 'purple' }[t] || 'default'
}
/** 数据权限兼容中文与英文枚举值（后端统一返回中文） */
function scopeLabel(s) {
  if (!s) return '未设置数据权限'
  const map = {
    personal: '个人数据',
    station: '站点数据',
    project: '项目数据',
    platform: '平台数据',
  }
  return map[s] || s
}
function fmtTime(v) {
  if (!v) return '-'
  return String(v).replace('T', ' ').slice(0, 19)
}

// ---------------------------------------------------------------- 数据加载
async function load() {
  loading.value = true
  try {
    const params = { ...query }
    // 状态以字符串承载（'全部' 不下发），转换为布尔
    if (params.status === 'true') params.status = true
    else if (params.status === 'false') params.status = false
    else delete params.status

    const res = await adminApi.users(params)
    rows.value = res.data?.items || []
    total.value = res.data?.meta?.total || 0
  } finally {
    loading.value = false
  }
}

/** 项目 / 角色下拉：一次加载后复用 */
async function loadOptions() {
  try {
    const res = await adminApi.projects()
    projects.value = res.data || []
  } catch {
    projects.value = []
  }
  try {
    const res = await adminApi.roles({ page: 1, page_size: 200 })
    roles.value = res.data?.items || []
  } catch {
    roles.value = []
  }
}

function search() {
  query.page = 1
  load()
}

function reset() {
  Object.assign(query, {
    keyword: '',
    project_id: undefined,
    station_id: undefined,
    role_id: undefined,
    status: undefined,
    page: 1,
  })
  queryStations.value = []
  load()
}

function onTableChange(pag) {
  query.page = pag.current
  query.page_size = pag.pageSize
  load()
}

/** 筛选区项目变化 → 联动站点下拉，并清空已选站点 */
async function onQueryProjectChange(pid) {
  query.station_id = undefined
  if (!pid) {
    queryStations.value = []
    return
  }
  try {
    const res = await adminApi.stationOptions({ project_id: pid })
    queryStations.value = res.data || []
  } catch {
    queryStations.value = []
  }
}

// ---------------------------------------------------------------- 新增 / 编辑
const formOpen = ref(false)
const submitting = ref(false)
const stationLoading = ref(false)
const formRef = ref(null)
const formStations = ref([])

const form = reactive({
  id: undefined,
  username: '',
  real_name: '',
  phone: '',
  email: '',
  password: '',
  role_id: undefined,
  project_id: undefined,
  station_id: undefined,
  user_type: 'admin',
  skills: '',
  status: true,
  on_duty: true,
})

const rules = {
  username: [
    { required: true, message: '请输入用户名' },
    { min: 2, max: 64, message: '用户名长度 2-64 位' },
  ],
  real_name: [{ required: true, message: '请输入姓名' }],
  phone: [{ pattern: /^1[3-9]\d{9}$/, message: '手机号格式不正确' }],
  email: [{ type: 'email', message: '邮箱格式不正确' }],
  password: [
    { required: true, message: '请输入初始密码' },
    { min: 6, message: '密码至少 6 位' },
  ],
}

function fillForm(record) {
  Object.assign(form, {
    id: record?.id,
    username: record?.username || '',
    real_name: record?.real_name || '',
    phone: record?.phone || '',
    email: record?.email || '',
    password: '',
    role_id: record?.role_id || undefined,
    project_id: record?.project_id || undefined,
    station_id: record?.station_id || undefined,
    user_type: record?.user_type || 'admin',
    skills: record?.skills || '',
    status: record?.status !== false,
    on_duty: record?.on_duty !== false,
  })
}

async function openCreate() {
  fillForm(null)
  formStations.value = []
  formOpen.value = true
  formRef.value?.clearValidate?.()
}

async function openEdit(record) {
  fillForm(record)
  // 按当前用户所属项目联动站点下拉
  if (record.project_id) {
    await onFormProjectChange(record.project_id, record.station_id)
  } else {
    formStations.value = []
  }
  formOpen.value = true
  formRef.value?.clearValidate?.()
}

/** 表单内项目变化 → 站点联动下拉（PDF 3.3 站点数据联动显示） */
async function onFormProjectChange(pid, keepStationId) {
  form.station_id = keepStationId || undefined
  if (!pid) {
    formStations.value = []
    return
  }
  stationLoading.value = true
  try {
    const res = await adminApi.stationOptions({ project_id: pid })
    formStations.value = res.data || []
  } catch {
    formStations.value = []
  } finally {
    stationLoading.value = false
  }
}

async function submitForm() {
  try {
    await formRef.value?.validate()
  } catch {
    return
  }
  submitting.value = true
  try {
    const payload = {
      real_name: form.real_name,
      phone: form.phone || null,
      email: form.email || null,
      role_id: form.role_id || null,
      project_id: form.project_id || null,
      station_id: form.station_id || null,
      skills: form.skills || null,
    }
    if (form.id) {
      payload.status = form.status
      payload.on_duty = form.on_duty
      await adminApi.updateUser(form.id, payload)
      message.success('用户已更新')
    } else {
      await adminApi.createUser({
        ...payload,
        username: form.username,
        password: form.password,
        user_type: form.user_type,
      })
      message.success('用户已创建')
    }
    formOpen.value = false
    load()
  } catch {
    /* 拦截器已提示 */
  } finally {
    submitting.value = false
  }
}

// ---------------------------------------------------------------- 启用 / 停用
async function toggleStatus(record) {
  const next = !record.status
  Modal.confirm({
    title: next ? '确认启用该用户？' : '确认停用该用户？',
    content: next
      ? `${record.real_name}（${record.username}）将可以重新登录`
      : `${record.real_name}（${record.username}）停用后无法登录，已接任务需另行改派`,
    okText: '确认',
    cancelText: '取消',
    onOk: async () => {
      try {
        await adminApi.updateUser(record.id, { status: next })
        message.success(next ? '已启用' : '已停用')
        load()
      } catch {
        /* 拦截器已提示 */
      }
    },
  })
}

// ---------------------------------------------------------------- 重置密码
const pwdOpen = ref(false)
const pwdLoading = ref(false)
const pwdValue = ref('')
const pwdTarget = ref(null)

function openResetPwd(record) {
  pwdTarget.value = record
  pwdValue.value = ''
  pwdOpen.value = true
}

async function submitResetPwd() {
  if (!pwdValue.value || pwdValue.value.length < 6) {
    message.warning('新密码至少 6 位')
    return
  }
  pwdLoading.value = true
  try {
    await adminApi.updateUser(pwdTarget.value.id, { password: pwdValue.value })
    message.success('密码已重置')
    pwdOpen.value = false
  } catch {
    /* 拦截器已提示 */
  } finally {
    pwdLoading.value = false
  }
}

// ---------------------------------------------------------------- 删除
function removeUser(record) {
  if (record.username === 'admin') {
    message.warning('内置管理员账号不允许删除')
    return
  }
  Modal.confirm({
    title: '确认删除该用户？',
    content: `删除后不可恢复：${record.real_name}（${record.username}）`,
    okText: '删除',
    okType: 'danger',
    cancelText: '取消',
    onOk: async () => {
      try {
        await adminApi.deleteUser(record.id)
        message.success('用户已删除')
        load()
      } catch {
        /* 拦截器已提示 */
      }
    },
  })
}

onMounted(() => {
  loadOptions()
  load()
})
</script>

<style scoped>
.disabled {
  color: #bfbfbf !important;
  cursor: not-allowed;
}
</style>
