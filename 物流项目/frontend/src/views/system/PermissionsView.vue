<script setup>
/**
 * 权限管理（权限点）。
 *
 * ★ 权限点是权限系统的最小单位，格式为 `资源:动作`，例如 vehicles:manage。
 *   「停用」一个权限点会立即影响所有引用它的角色 —— 这是观察权限生效链路的入口：
 *     停用 vehicles:manage → 角色「基础数据管理员」不再拥有它 → 该角色用户无法维护车辆。
 *
 * ★ 权限点仍被角色引用时不允许删除，避免角色指向不存在的权限（悬空引用）。
 */
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Refresh } from '@element-plus/icons-vue'
import * as api from '@/api'
import { useTable } from '@/utils/table'
import { tryAction } from '@/utils/error'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const canManage = computed(() => auth.has('permissions:manage'))

const { loading, rows: permissions, load } = useTable(api.fetchPermissions)

const filterModule = ref('')
const filterAction = ref('')

const modules = computed(() => [...new Set(permissions.value.map((p) => p.module))])
const actions = computed(() => [...new Set(permissions.value.map((p) => p.action))])

const filtered = computed(() =>
  permissions.value
    .filter((p) => (filterModule.value ? p.module === filterModule.value : true))
    .filter((p) => (filterAction.value ? p.action === filterAction.value : true)),
)

const actionMeta = {
  read: { text: '查看', type: 'info' },
  manage: { text: '维护', type: 'warning' },
  create: { text: '新建', type: 'success' },
  confirm: { text: '确认', type: 'primary' },
  replan: { text: '重排', type: 'danger' },
  view: { text: '查看', type: 'info' },
  custom: { text: '自定义', type: '' },
}

function meta(action) {
  return actionMeta[action] || { text: action, type: '' }
}

async function toggle(row) {
  const { ok } = await tryAction(
    () => api.togglePermission(row.id),
    `权限点 ${row.code} 已${row.is_active ? '停用' : '启用'}`,
  )
  if (ok) await load()
}

async function remove(row) {
  try {
    await ElMessageBox.confirm(
      row.role_count > 0
        ? `权限点 ${row.code} 仍被 ${row.role_count} 个角色引用，删除会被拒绝。仍要尝试吗？`
        : `确定删除权限点 ${row.code}？`,
      '删除确认',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  const { ok, result } = await tryAction(() => api.deletePermission(row.id))
  if (ok) {
    ElMessage.success(`权限点 ${result.deleted} 已删除`)
    await load()
  }
}

/* ---------------- 新建 ---------------- */
const dialogVisible = ref(false)
const submitting = ref(false)
const formRef = ref()
const form = ref({ code: '', name: '', module: '', action: 'read' })

const rules = {
  code: [
    { required: true, message: '请输入权限码', trigger: 'blur' },
    {
      pattern: /^[a-z][a-z0-9_]*:[a-z][a-z0-9_]*$/,
      message: '格式为 资源:动作，例如 stores:manage',
      trigger: 'blur',
    },
  ],
  name: [{ required: true, message: '请输入权限名称', trigger: 'blur' }],
}

function openCreate() {
  form.value = { code: '', name: '', module: modules.value[0] || '系统管理', action: 'read' }
  dialogVisible.value = true
}

async function submit() {
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return
  submitting.value = true
  const { ok } = await tryAction(() => api.createPermission({ ...form.value }), '权限点已创建')
  submitting.value = false
  if (!ok) return
  dialogVisible.value = false
  await load()
}

onMounted(load)
</script>

<template>
  <div class="page-container">
    <div class="page-header">
      <div>
        <h2 class="page-title">权限管理</h2>
        <p class="page-desc">
          权限点是权限系统的最小单位，格式 <code class="perm-code">资源:动作</code>。
          停用后会立即从所有角色中失效；仍被角色引用的权限点不允许删除。
          写操作需要 <code class="perm-code">permissions:manage</code>。
        </p>
      </div>
      <div class="actions">
        <el-select v-model="filterModule" placeholder="全部模块" clearable style="width: 140px">
          <el-option v-for="m in modules" :key="m" :label="m" :value="m" />
        </el-select>
        <el-select v-model="filterAction" placeholder="全部动作" clearable style="width: 130px">
          <el-option v-for="a in actions" :key="a" :label="meta(a).text" :value="a" />
        </el-select>
        <el-button :icon="Refresh" @click="load">刷新</el-button>
        <el-button v-if="canManage" type="primary" :icon="Plus" @click="openCreate">
          新建权限点
        </el-button>
      </div>
    </div>

    <el-card shadow="never">
      <el-table v-loading="loading" :data="filtered" stripe>
        <el-table-column prop="id" label="ID" width="60" />
        <el-table-column label="权限码" width="200">
          <template #default="{ row }">
            <span class="perm-code" :class="{ disabled: !row.is_active }">{{ row.code }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="name" label="名称" width="150" />
        <el-table-column prop="module" label="模块" width="130">
          <template #default="{ row }">
            <el-tag size="small" effect="plain">{{ row.module }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="动作" width="100">
          <template #default="{ row }">
            <el-tag :type="meta(row.action).type" size="small">{{ meta(row.action).text }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="引用角色数" width="110" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.role_count" type="warning" size="small">{{ row.role_count }}</el-tag>
            <span v-else class="muted">0</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="row.is_active ? 'success' : 'danger'" size="small" effect="plain">
              {{ row.is_active ? '启用' : '停用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column v-if="canManage" label="操作" width="150" fixed="right">
          <template #default="{ row }">
            <el-button size="small" type="warning" link @click="toggle(row)">
              {{ row.is_active ? '停用' : '启用' }}
            </el-button>
            <el-button size="small" type="danger" link @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!loading && !filtered.length" description="没有匹配的权限点" />
    </el-card>

    <el-alert type="info" :closable="false" class="mt">
      <template #title>
        验证权限链路：停用 <code class="perm-code">vehicles:manage</code> 后，
        用 <strong>dataadmin</strong> 账号登录，「车辆档案」的编辑按钮会消失；
        恢复启用后又会出现。这说明权限变更对所有角色即时生效。
      </template>
    </el-alert>

    <el-dialog v-model="dialogVisible" title="新建权限点" width="520px">
      <el-form ref="formRef" :model="form" :rules="rules" label-width="90px">
        <el-form-item label="权限码" prop="code">
          <el-input v-model="form.code" placeholder="例如 stores:manage" />
        </el-form-item>
        <el-form-item label="名称" prop="name">
          <el-input v-model="form.name" placeholder="例如 维护门店" />
        </el-form-item>
        <el-form-item label="模块">
          <el-select v-model="form.module" allow-create filterable style="width: 100%">
            <el-option v-for="m in modules" :key="m" :label="m" :value="m" />
          </el-select>
        </el-form-item>
        <el-form-item label="动作">
          <el-select v-model="form.action" style="width: 100%">
            <el-option v-for="a in actions" :key="a" :label="meta(a).text" :value="a" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submit">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.disabled {
  text-decoration: line-through;
  color: #c0c4cc;
}
</style>
