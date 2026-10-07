<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h2 class="page-title"><SafetyCertificateOutlined /> 角色权限</h2>
        <div class="page-subtitle">
          唯一识别码 + 角色名称 + 数据权限　·　树形权限菜单默认折叠，展开后可勾选（PDF 3.3）
        </div>
      </div>
      <a-space>
        <a-button :loading="loading" @click="load">
          <template #icon><ReloadOutlined /></template>
          刷新
        </a-button>
        <a-button type="primary" @click="openCreate">
          <template #icon><PlusOutlined /></template>
          新增角色
        </a-button>
      </a-space>
    </div>

    <!-- ---------------- 筛选条件 ---------------- -->
    <div class="filter-bar">
      <a-form layout="inline" :model="query">
        <a-form-item label="模糊查询">
          <a-input
            v-model:value="query.keyword"
            placeholder="识别码 / 角色名称 / 备注"
            style="width: 240px"
            allow-clear
            @press-enter="search"
          >
            <template #prefix><SearchOutlined /></template>
          </a-input>
        </a-form-item>
        <a-form-item label="数据权限">
          <a-select
            v-model:value="query.data_scope"
            style="width: 150px"
            allow-clear
            placeholder="全部"
            :options="SCOPE_OPTIONS"
          />
        </a-form-item>
        <a-form-item>
          <a-space>
            <a-button type="primary" :loading="loading" @click="search">查询</a-button>
            <a-button @click="reset">重置</a-button>
          </a-space>
        </a-form-item>
      </a-form>
    </div>

    <!-- ---------------- 角色列表（按 sort_order 倒序） ---------------- -->
    <a-card :bordered="false">
      <a-table
        :columns="columns"
        :data-source="rows"
        :loading="loading"
        row-key="id"
        size="middle"
        :scroll="{ x: 1180 }"
        :pagination="pagination"
        @change="onTableChange"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'code'">
            <span class="mono" style="font-weight: 600">{{ record.code }}</span>
            <a-tag v-if="record.is_builtin" color="default" style="margin-left: 6px">内置</a-tag>
          </template>

          <template v-else-if="column.key === 'data_scope'">
            <a-tag :color="scopeColor(record.data_scope)">{{ record.data_scope }}</a-tag>
          </template>

          <template v-else-if="column.key === 'sort_order'">
            <span class="mono">{{ record.sort_order }}</span>
          </template>

          <template v-else-if="column.key === 'status'">
            <a-badge
              :status="record.status ? 'success' : 'default'"
              :text="record.status ? '启用' : '停用'"
            />
          </template>

          <template v-else-if="column.key === 'remark'">
            <span class="text-muted" style="font-size: 12px">{{ record.remark || '-' }}</span>
          </template>

          <template v-else-if="column.key === 'created_at'">
            <span class="mono" style="font-size: 12px">{{ fmtTime(record.created_at) }}</span>
          </template>

          <template v-else-if="column.key === 'action'">
            <a-space size="small">
              <a @click="openEdit(record)">编辑 / 分配权限</a>
              <a
                class="text-danger"
                :class="{ disabled: record.is_builtin }"
                @click="removeRole(record)"
              >
                删除
              </a>
            </a-space>
          </template>
        </template>
      </a-table>
    </a-card>

    <!-- ---------------- 新增 / 编辑角色 + 权限分配 ---------------- -->
    <a-modal
      v-model:open="formOpen"
      :title="form.id ? `编辑角色：${form.name}` : '新增角色'"
      width="760px"
      :confirm-loading="submitting"
      @ok="submitForm"
    >
      <a-form ref="formRef" :model="form" :rules="rules" layout="vertical">
        <a-row :gutter="16">
          <a-col :span="12">
            <a-form-item label="唯一识别码" name="code">
              <a-input
                v-model:value="form.code"
                :disabled="Boolean(form.id)"
                placeholder="例如：ops_manager（创建后不可修改）"
              />
            </a-form-item>
          </a-col>
          <a-col :span="12">
            <a-form-item label="角色名称" name="name">
              <a-input v-model:value="form.name" placeholder="例如：运维主管" />
            </a-form-item>
          </a-col>

          <a-col :span="12">
            <a-form-item label="数据权限（可见数据范围）" name="data_scope">
              <a-select v-model:value="form.data_scope" :options="SCOPE_OPTIONS" />
            </a-form-item>
          </a-col>
          <a-col :span="6">
            <a-form-item label="排序（越大越靠前）">
              <a-input-number v-model:value="form.sort_order" :min="0" :max="9999" style="width: 100%" />
            </a-form-item>
          </a-col>
          <a-col :span="6">
            <a-form-item label="状态">
              <a-switch v-model:checked="form.status" checked-children="启用" un-checked-children="停用" />
            </a-form-item>
          </a-col>

          <a-col :span="24">
            <a-form-item label="备注">
              <a-textarea v-model:value="form.remark" :rows="2" placeholder="角色职责说明（选填）" />
            </a-form-item>
          </a-col>
        </a-row>
      </a-form>

      <a-divider style="margin: 4px 0 12px">
        权限菜单分配
        <span class="text-muted" style="font-size: 12px; font-weight: 400">
          （默认折叠，点击展开逐级勾选；父级勾选表示同时拥有其下全部权限）
        </span>
      </a-divider>

      <div class="perm-toolbar">
        <a-space size="small" wrap>
          <a-input
            v-model:value="permKeyword"
            size="small"
            placeholder="按名称 / 识别码过滤"
            style="width: 210px"
            allow-clear
          >
            <template #prefix><SearchOutlined /></template>
          </a-input>
          <a-button size="small" @click="checkAllPermissions">全选</a-button>
          <a-button size="small" @click="clearPermissions">清空</a-button>
          <a-tag color="blue">已选 {{ permissionCodes.length }} 项</a-tag>
        </a-space>
      </div>

      <a-spin :spinning="treeLoading">
        <div class="perm-tree">
          <a-empty v-if="!displayTree.length" description="暂无权限数据" />
          <a-tree
            v-else
            v-model:checked-keys="checkedKeys"
            v-model:expanded-keys="expandedKeys"
            :tree-data="displayTree"
            checkable
            :selectable="false"
            @check="onTreeCheck"
          >
            <template #title="node">
              <span>{{ node.name }}</span>
              <span class="mono text-muted" style="font-size: 12px; margin-left: 6px">
                {{ node.code }}
              </span>
              <a-tag v-if="node.perm_type === 'button'" color="cyan" style="margin-left: 6px">
                按钮
              </a-tag>
              <span v-if="node.route_path" class="text-muted" style="font-size: 12px; margin-left: 6px">
                {{ node.route_path }}
              </span>
            </template>
          </a-tree>
        </div>
      </a-spin>
    </a-modal>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { Modal, message } from 'ant-design-vue'
import {
  PlusOutlined,
  ReloadOutlined,
  SafetyCertificateOutlined,
  SearchOutlined,
} from '@ant-design/icons-vue'
import { adminApi } from '@/api'

const loading = ref(false)
const rows = ref([])
const total = ref(0)

const query = reactive({
  keyword: '',
  data_scope: undefined,
  page: 1,
  page_size: 20,
})

/** 数据权限取值与后端枚举一致（中文） */
const SCOPE_OPTIONS = [
  { label: '个人数据', value: '个人数据' },
  { label: '站点数据', value: '站点数据' },
  { label: '项目数据', value: '项目数据' },
  { label: '平台数据', value: '平台数据' },
]

const pagination = computed(() => ({
  current: query.page,
  pageSize: query.page_size,
  total: total.value,
  showSizeChanger: true,
  showTotal: (t) => `共 ${t} 条`,
}))

const columns = [
  { title: '唯一识别码', key: 'code', width: 210, fixed: 'left' },
  { title: '角色名称', dataIndex: 'name', width: 150 },
  { title: '数据权限', key: 'data_scope', width: 120 },
  { title: '排序', key: 'sort_order', width: 80 },
  { title: '状态', key: 'status', width: 100 },
  { title: '备注', key: 'remark', width: 250 },
  { title: '创建时间', key: 'created_at', width: 170 },
  { title: '操作', key: 'action', width: 190, fixed: 'right' },
]

// ---------------------------------------------------------------- 展示辅助
function scopeColor(s) {
  return (
    {
      个人数据: 'default',
      站点数据: 'blue',
      项目数据: 'geekblue',
      平台数据: 'red',
    }[s] || 'default'
  )
}
function fmtTime(v) {
  if (!v) return '-'
  return String(v).replace('T', ' ').slice(0, 19)
}

// ---------------------------------------------------------------- 角色列表
async function load() {
  loading.value = true
  try {
    const params = { ...query }
    if (!params.keyword) delete params.keyword
    if (!params.data_scope) delete params.data_scope
    const res = await adminApi.roles(params)
    rows.value = res.data?.items || []
    total.value = res.data?.meta?.total || 0
  } finally {
    loading.value = false
  }
}

function search() {
  query.page = 1
  load()
}

function reset() {
  Object.assign(query, { keyword: '', data_scope: undefined, page: 1 })
  load()
}

function onTableChange(pag) {
  query.page = pag.current
  query.page_size = pag.pageSize
  load()
}

// ---------------------------------------------------------------- 权限树
const treeLoading = ref(false)
const permTree = ref([])
const checkedKeys = ref([])
const expandedKeys = ref([])
const permKeyword = ref('')
/** 提交给后端的权限识别码集合（勾选 + 半选的父级菜单） */
const permissionCodes = ref([])

/** 树节点：后端 PermissionTreeNode（code/name/perm_type/route_path/children） */
function buildTree(nodes) {
  return (nodes || []).map((n) => {
    const node = {
      key: n.code,
      code: n.code,
      name: n.name,
      perm_type: n.perm_type,
      route_path: n.route_path,
      data_scope: n.data_scope,
    }
    if (n.children?.length) node.children = buildTree(n.children)
    return node
  })
}

/** 关键码过滤：命中节点及其祖先链保留，展开以便查看 */
const displayTree = computed(() => {
  const kw = permKeyword.value.trim().toLowerCase()
  if (!kw) return buildTree(permTree.value)

  const filter = (nodes) =>
    (nodes || [])
      .map((n) => {
        const children = filter(n.children)
        const hit =
          (n.name || '').toLowerCase().includes(kw) || (n.code || '').toLowerCase().includes(kw)
        if (hit || children.length) {
          return { ...n, children: children.length ? children : n.children }
        }
        return null
      })
      .filter(Boolean)

  return filter(buildTree(permTree.value))
})

async function loadPermissionTree() {
  if (permTree.value.length) return
  treeLoading.value = true
  try {
    const res = await adminApi.permissionTree()
    permTree.value = res.data || []
  } catch {
    permTree.value = []
  } finally {
    treeLoading.value = false
  }
}

/** 收集全部权限识别码（含父级菜单） */
function collectCodes(nodes, acc = []) {
  ;(nodes || []).forEach((n) => {
    acc.push(n.code)
    if (n.children?.length) collectCodes(n.children, acc)
  })
  return acc
}

function onTreeCheck(keys, e) {
  const checked = Array.isArray(keys) ? keys : keys?.checked || []
  const half = e?.halfCheckedKeys || []
  checkedKeys.value = checked
  permissionCodes.value = Array.from(new Set([...checked, ...half]))
}

function checkAllPermissions() {
  const all = collectCodes(permTree.value)
  checkedKeys.value = all
  permissionCodes.value = [...all]
  expandedKeys.value = permTree.value.map((n) => n.code)
}

function clearPermissions() {
  checkedKeys.value = []
  permissionCodes.value = []
}

// ---------------------------------------------------------------- 新增 / 编辑
const formOpen = ref(false)
const submitting = ref(false)
const formRef = ref(null)

const form = reactive({
  id: undefined,
  code: '',
  name: '',
  data_scope: '个人数据',
  sort_order: 0,
  status: true,
  remark: '',
})

const rules = {
  code: [
    { required: true, message: '请输入唯一识别码' },
    { min: 2, max: 64, message: '识别码长度 2-64 位' },
    {
      pattern: /^[A-Za-z][A-Za-z0-9_:.-]*$/,
      message: '识别码以字母开头，可含字母、数字、下划线、冒号、点、横线',
    },
  ],
  name: [{ required: true, message: '请输入角色名称' }],
  data_scope: [{ required: true, message: '请选择数据权限' }],
}

async function openCreate() {
  Object.assign(form, {
    id: undefined,
    code: '',
    name: '',
    data_scope: '个人数据',
    sort_order: 0,
    status: true,
    remark: '',
  })
  checkedKeys.value = []
  permissionCodes.value = []
  expandedKeys.value = []
  permKeyword.value = ''
  formOpen.value = true
  formRef.value?.clearValidate?.()
  await loadPermissionTree()
}

async function openEdit(record) {
  Object.assign(form, {
    id: record.id,
    code: record.code,
    name: record.name,
    data_scope: record.data_scope || '个人数据',
    sort_order: record.sort_order ?? 0,
    status: record.status !== false,
    remark: record.remark || '',
  })
  permKeyword.value = ''
  expandedKeys.value = []
  formOpen.value = true
  formRef.value?.clearValidate?.()

  treeLoading.value = true
  try {
    const [treeRes, permRes] = await Promise.all([
      permTree.value.length ? Promise.resolve({ data: permTree.value }) : adminApi.permissionTree(),
      adminApi.rolePermissions(record.id),
    ])
    permTree.value = treeRes.data || []
    permissionCodes.value = permRes.data?.permission_codes || []
    // 已授权的父级菜单展开，便于查看勾选情况
    const granted = new Set(permissionCodes.value)
    expandedKeys.value = (permTree.value || [])
      .filter((n) => granted.has(n.code))
      .map((n) => n.code)
    checkedKeys.value = [...permissionCodes.value]
  } catch {
    permissionCodes.value = []
    checkedKeys.value = []
  } finally {
    treeLoading.value = false
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
      name: form.name,
      data_scope: form.data_scope,
      sort_order: form.sort_order ?? 0,
      remark: form.remark || null,
      permission_codes: permissionCodes.value,
    }
    if (form.id) {
      payload.status = form.status
      await adminApi.updateRole(form.id, payload)
      message.success('角色已更新')
    } else {
      await adminApi.createRole({ ...payload, code: form.code })
      message.success('角色已创建')
    }
    formOpen.value = false
    load()
  } catch {
    /* 拦截器已提示 */
  } finally {
    submitting.value = false
  }
}

// ---------------------------------------------------------------- 删除
function removeRole(record) {
  if (record.is_builtin) {
    message.warning('内置角色不允许删除')
    return
  }
  Modal.confirm({
    title: '确认删除该角色？',
    content: `删除后不可恢复：${record.name}（${record.code}）。若角色下仍有用户，后端会拒绝删除。`,
    okText: '删除',
    okType: 'danger',
    cancelText: '取消',
    onOk: async () => {
      try {
        await adminApi.deleteRole(record.id)
        message.success('角色已删除')
        load()
      } catch {
        /* 拦截器已提示 */
      }
    },
  })
}

onMounted(load)
</script>

<style scoped>
.perm-toolbar {
  margin-bottom: 10px;
}

.perm-tree {
  min-height: 180px;
  max-height: 320px;
  overflow: auto;
  border: 1px solid #e8e8e8;
  border-radius: 8px;
  padding: 8px 10px;
  background: #fafbfc;
}

.perm-tree :deep(.ant-tree) {
  background: transparent;
}

.disabled {
  color: #bfbfbf !important;
  cursor: not-allowed;
}
</style>
