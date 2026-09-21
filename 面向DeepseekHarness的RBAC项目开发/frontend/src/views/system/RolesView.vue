<script setup>
/**
 * 角色管理（需要 users:manage，仅管理员）。
 *
 * ★ 本页是 R3「删除角色保护」的验证入口：
 *   尝试删除仍绑定用户的角色，会收到 409 与
 *   「该角色仍绑定 N 个用户，请先改绑」，并且角色不会被删除。
 *   页面上对「绑定用户数 > 0」的角色直接把删除按钮置为禁用并说明原因，
 *   但这只是体验优化 —— 真正拦住删除的是后端与数据库外键。
 */
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Refresh } from '@element-plus/icons-vue'
import * as api from '@/api'

const loading = ref(false)
const roles = ref([])
const permissions = ref([])

const dialogVisible = ref(false)
const submitting = ref(false)
const editingId = ref(null)
const formRef = ref()

const form = ref({
  code: '',
  name: '',
  description: '',
  permission_codes: [],
})

const rules = {
  code: [{ required: true, message: '请输入角色码', trigger: 'blur' }],
  name: [{ required: true, message: '请输入角色名称', trigger: 'blur' }],
}

const isEditing = computed(() => editingId.value !== null)

/** 按模块分组展示权限点，方便勾选 */
const permissionGroups = computed(() => {
  const groups = {}
  for (const p of permissions.value) {
    if (!groups[p.module]) groups[p.module] = []
    groups[p.module].push(p)
  }
  return groups
})

async function load() {
  loading.value = true
  try {
    const [roleList, permList] = await Promise.all([api.fetchRoles(), api.fetchPermissions()])
    roles.value = roleList
    permissions.value = permList
  } finally {
    loading.value = false
  }
}

function openCreate() {
  editingId.value = null
  form.value = { code: '', name: '', description: '', permission_codes: [] }
  dialogVisible.value = true
}

function openEdit(row) {
  editingId.value = row.id
  form.value = {
    code: row.code,
    name: row.name,
    description: row.description || '',
    permission_codes: [...row.permission_codes],
  }
  dialogVisible.value = true
}

async function submit() {
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return

  submitting.value = true
  try {
    if (isEditing.value) {
      // 角色码不允许修改（它是审计与代码里的稳定标识），只更新名称/描述/权限
      await api.updateRole(editingId.value, {
        name: form.value.name,
        description: form.value.description,
        permission_codes: form.value.permission_codes,
      })
      ElMessage.success('角色已更新，权限变更即时生效')
    } else {
      await api.createRole({ ...form.value })
      ElMessage.success('角色已创建')
    }
    dialogVisible.value = false
    await load()
  } finally {
    submitting.value = false
  }
}

async function handleDelete(row) {
  try {
    await ElMessageBox.confirm(
      row.user_count > 0
        ? `角色「${row.name}」仍绑定 ${row.user_count} 个用户，删除会被拒绝（409）。仍要尝试吗？`
        : `确定删除角色「${row.name}」？此操作不可撤销。`,
      '删除确认',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }

  try {
    const result = await api.deleteRole(row.id)
    ElMessage.success(`角色 ${result.deleted} 已删除`)
    await load()
  } catch {
    // 409 的提示由 axios 拦截器给出（含绑定用户数）
  }
}

/** 切换角色启用状态（R4：停用后其权限整体退出持有者的权限并集） */
async function toggleActive(row) {
  const next = !row.is_active
  await api.updateRole(row.id, { is_active: next })
  ElMessage.success(
    next
      ? `角色「${row.name}」已启用，其权限重新进入持有者的权限并集`
      : `角色「${row.name}」已停用，持有该角色的用户将立即失去其全部权限`,
  )
  await load()
}

onMounted(load)
</script>

<template>
  <div class="page-container">
    <div class="page-header">
      <div>
        <h2 class="page-title">角色管理</h2>
        <p class="page-desc">
          角色是「权限点的集合」。删除仍被用户引用的角色会被拒绝（409），
          提示绑定用户数，<strong>不做级联清除</strong>。
        </p>
      </div>
      <div class="actions">
        <el-button :icon="Refresh" @click="load">刷新</el-button>
        <el-button type="primary" :icon="Plus" @click="openCreate">新建角色</el-button>
      </div>
    </div>

    <el-card shadow="never">
      <el-table v-loading="loading" :data="roles" stripe>
        <el-table-column prop="id" label="ID" width="70" />
        <el-table-column prop="code" label="角色码" width="120">
          <template #default="{ row }">
            <span class="perm-code">{{ row.code }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="name" label="名称" width="110" />
        <el-table-column prop="description" label="描述" min-width="200" show-overflow-tooltip />
        <el-table-column label="绑定用户" width="110" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.user_count > 0" type="warning" size="small">
              {{ row.user_count }} 个
            </el-tag>
            <el-tag v-else type="info" size="small" effect="plain">0 个</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100" align="center">
          <template #default="{ row }">
            <el-switch
              :model-value="row.is_active"
              size="small"
              @change="toggleActive(row)"
            />
          </template>
        </el-table-column>
        <el-table-column label="权限点" min-width="300">
          <template #default="{ row }">
            <template v-if="row.permission_codes.length">
              <el-tag
                v-for="code in row.permission_codes"
                :key="code"
                size="small"
                effect="plain"
                class="mr perm-code"
              >
                {{ code }}
              </el-tag>
            </template>
            <span v-else class="muted">未绑定任何权限</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="150" fixed="right">
          <template #default="{ row }">
            <el-button size="small" type="primary" link @click="openEdit(row)">编辑</el-button>
            <!--
              绑定用户数 > 0 时禁用删除按钮并说明原因（体验优化）。
              即便绕过这个禁用，后端仍会返回 409。
            -->
            <el-tooltip
              :disabled="row.user_count === 0"
              :content="`该角色仍绑定 ${row.user_count} 个用户，请先改绑`"
            >
              <span>
                <el-button
                  size="small"
                  type="danger"
                  link
                  :disabled="row.user_count > 0"
                  @click="handleDelete(row)"
                >
                  删除
                </el-button>
              </span>
            </el-tooltip>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-alert type="warning" :closable="false" class="mt">
      <template #title>
        验证 R3：<code>admin</code> / <code>operator</code> / <code>supplier</code> /
        <code>readonly</code> 四个内置角色都有绑定用户，删除按钮被禁用。
        先到「用户管理」把这些用户改绑到别的角色，再来删除即可成功。
        后端与数据库外键会双重兜底，不可能出现「角色删了但绑定关系还在」。
      </template>
    </el-alert>

    <!-- 新建 / 编辑角色 -->
    <el-dialog
      v-model="dialogVisible"
      :title="isEditing ? `编辑角色 ${form.code}` : '新建角色'"
      width="560px"
    >
      <el-form ref="formRef" :model="form" :rules="rules" label-width="80px">
        <el-form-item label="角色码" prop="code">
          <el-input
            v-model="form.code"
            :disabled="isEditing"
            placeholder="英文标识，如 auditor"
          />
          <div v-if="isEditing" class="hint">角色码是审计与代码里的稳定标识，创建后不可修改</div>
        </el-form-item>
        <el-form-item label="名称" prop="name">
          <el-input v-model="form.name" placeholder="中文名，如 审计员" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="form.description" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item label="权限点">
          <el-checkbox-group v-model="form.permission_codes" class="perm-group">
            <div v-for="(items, module) in permissionGroups" :key="module" class="perm-module">
              <div class="module-name">{{ module }}</div>
              <el-checkbox
                v-for="p in items"
                :key="p.code"
                :value="p.code"
                :label="p.code"
                :disabled="!p.is_active"
              >
                <span class="perm-code">{{ p.code }}</span>
                <span class="perm-name">{{ p.name }}</span>
                <el-tag v-if="!p.is_active" size="small" type="danger" effect="plain">已停用</el-tag>
              </el-checkbox>
            </div>
          </el-checkbox-group>
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
}

.mt {
  margin-top: 16px;
}

.mr {
  margin-right: 4px;
  margin-bottom: 2px;
}

.muted {
  color: #909399;
  font-size: 12px;
}

.hint {
  font-size: 12px;
  color: #909399;
  line-height: 1.5;
}

.perm-group {
  display: flex;
  flex-direction: column;
  gap: 10px;
  width: 100%;
}

.perm-module {
  padding: 8px 10px;
  border: 1px solid #e4e7ed;
  border-radius: 6px;
}

.module-name {
  font-size: 12px;
  font-weight: 600;
  color: #606266;
  margin-bottom: 4px;
}

.perm-name {
  margin-left: 6px;
  color: #909399;
  font-size: 12px;
}

code {
  background: #f4f4f5;
  padding: 1px 5px;
  border-radius: 3px;
}
</style>
