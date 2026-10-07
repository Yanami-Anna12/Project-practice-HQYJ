<script setup>
/**
 * 角色管理。
 *
 * ★ 「删除保护」的验证入口：
 *   尝试删除仍绑定用户的角色会被拒绝（409），并提示还剩几个用户绑着。
 *   页面上对「绑定用户数 > 0」的角色直接禁用删除按钮并说明原因，
 *   但这只是体验优化 —— 首版没有后端，真正的把关在 api/index.js 的 deleteRole 里。
 */
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Refresh, View } from '@element-plus/icons-vue'
import * as api from '@/api'
import { useTable } from '@/utils/table'
import { tryAction } from '@/utils/error'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const canManage = computed(() => auth.has('roles:manage'))

const { loading, rows: roles, load } = useTable(api.fetchRoles)
const permissions = ref([])

const dialogVisible = ref(false)
const submitting = ref(false)
const editingId = ref(null)
const formRef = ref()

const form = ref({ code: '', name: '', description: '', permission_codes: [] })

const rules = {
  code: [
    { required: true, message: '请输入角色码', trigger: 'blur' },
    { pattern: /^[a-z][a-z0-9_]*$/, message: '只能用小写字母、数字和下划线', trigger: 'blur' },
  ],
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

async function loadPermissions() {
  permissions.value = (await api.fetchPermissions().catch(() => [])) || []
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
  const payload = {
    name: form.value.name,
    description: form.value.description,
    permission_codes: form.value.permission_codes,
  }
  const { ok } = await tryAction(
    () =>
      isEditing.value
        ? api.updateRole(editingId.value, payload)
        : api.createRole({ ...form.value }),
    isEditing.value ? '角色已更新' : '角色已创建',
  )
  submitting.value = false
  if (!ok) return
  dialogVisible.value = false
  await load()
}

async function handleDelete(row) {
  const blocked = row.user_count > 0
  try {
    await ElMessageBox.confirm(
      blocked
        ? `角色「${row.name}」仍绑定 ${row.user_count} 个用户，删除会被拒绝。仍要尝试吗？`
        : `确定删除角色「${row.name}」？此操作不可撤销。`,
      '删除确认',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  const { ok, result } = await tryAction(() => api.deleteRole(row.id))
  if (ok) {
    ElMessage.success(`角色 ${result.deleted} 已删除`)
    await load()
  }
}

/** 预览某角色的权限点（只读弹窗） */
const detailVisible = ref(false)
const detailRole = ref(null)

function openDetail(row) {
  detailRole.value = row
  detailVisible.value = true
}

onMounted(async () => {
  await Promise.all([load(), loadPermissions()])
})
</script>

<template>
  <div class="page-container">
    <div class="page-header">
      <div>
        <h2 class="page-title">角色管理</h2>
        <p class="page-desc">
          角色是权限的集合。删除仍被用户引用的角色会被拒绝（409），避免出现「用户指向不存在的角色」。
          写操作需要 <code class="perm-code">roles:manage</code>。
        </p>
      </div>
      <div class="actions">
        <el-button :icon="Refresh" @click="load">刷新</el-button>
        <el-button v-if="canManage" type="primary" :icon="Plus" @click="openCreate">
          新建角色
        </el-button>
      </div>
    </div>

    <el-card shadow="never">
      <el-table v-loading="loading" :data="roles" stripe>
        <el-table-column prop="id" label="ID" width="60" />
        <el-table-column label="角色码" width="130">
          <template #default="{ row }">
            <span class="perm-code">{{ row.code }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="name" label="名称" width="150" />
        <el-table-column prop="description" label="说明" min-width="200" show-overflow-tooltip />
        <el-table-column label="权限数" width="90" align="center">
          <template #default="{ row }">
            <el-tag size="small" effect="plain">{{ row.permission_codes.length }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="绑定用户" width="100" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.user_count" type="warning" size="small">{{ row.user_count }}</el-tag>
            <span v-else class="muted">0</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="row.is_active ? 'success' : 'info'" size="small" effect="plain">
              {{ row.is_active ? '启用' : '停用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="180" fixed="right">
          <template #default="{ row }">
            <el-button size="small" link :icon="View" @click="openDetail(row)">权限</el-button>
            <el-button v-if="canManage" size="small" type="primary" link @click="openEdit(row)">
              编辑
            </el-button>
            <el-tooltip
              v-if="canManage && row.user_count > 0"
              :content="`仍绑定 ${row.user_count} 个用户，删除会被拒绝`"
            >
              <span>
                <el-button size="small" type="danger" link disabled>删除</el-button>
              </span>
            </el-tooltip>
            <el-button
              v-else-if="canManage"
              size="small"
              type="danger"
              link
              @click="handleDelete(row)"
            >
              删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-alert type="info" :closable="false" class="mt">
      <template #title>
        可以试试删除 <strong>admin</strong> 角色 —— 它绑定着用户，删除会被拒绝并说明还剩几个用户。
        这是「删除保护」在界面上的体现。
      </template>
    </el-alert>

    <!-- 新建 / 编辑 -->
    <el-dialog
      v-model="dialogVisible"
      :title="isEditing ? `编辑角色 ${form.code}` : '新建角色'"
      width="680px"
    >
      <el-form ref="formRef" :model="form" :rules="rules" label-width="90px">
        <el-form-item label="角色码" prop="code">
          <el-input v-model="form.code" :disabled="isEditing" placeholder="例如 dispatcher" />
          <div class="field-note">
            角色码是审计与代码里的稳定标识，创建后不允许修改。
          </div>
        </el-form-item>
        <el-form-item label="名称" prop="name">
          <el-input v-model="form.name" placeholder="例如 调度员" />
        </el-form-item>
        <el-form-item label="说明">
          <el-input v-model="form.description" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item label="权限点">
          <div class="perm-groups">
            <div v-for="(items, module) in permissionGroups" :key="module" class="perm-group">
              <div class="perm-group-title">{{ module }}</div>
              <el-checkbox-group v-model="form.permission_codes">
                <el-checkbox v-for="p in items" :key="p.code" :value="p.code">
                  <span class="perm-name">{{ p.name }}</span>
                  <span class="perm-code perm-dim">{{ p.code }}</span>
                </el-checkbox>
              </el-checkbox-group>
            </div>
          </div>
        </el-form-item>
      </el-form>

      <template #footer>
        <span class="footer-info">已选 {{ form.permission_codes.length }} 个权限点</span>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submit">保存</el-button>
      </template>
    </el-dialog>

    <!-- 权限只读查看 -->
    <el-dialog v-model="detailVisible" :title="`${detailRole?.name} 的权限点`" width="620px">
      <div class="preview">
        <el-tag
          v-for="code in detailRole?.permission_codes || []"
          :key="code"
          size="small"
          effect="plain"
          class="mr perm-code"
        >
          {{ code }}
        </el-tag>
        <span v-if="!detailRole?.permission_codes?.length" class="muted">未绑定权限点</span>
      </div>
    </el-dialog>
  </div>
</template>

<style scoped>
.actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.field-note {
  font-size: 12px;
  color: #909399;
  line-height: 1.6;
}

.perm-groups {
  display: flex;
  flex-direction: column;
  gap: 10px;
  width: 100%;
}

.perm-group {
  padding: 8px 12px;
  border: 1px solid #e4e7ed;
  border-radius: 6px;
}

.perm-group-title {
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 4px;
}

.perm-name {
  margin-right: 6px;
}

.perm-dim {
  color: #a8abb2;
}

.footer-info {
  float: left;
  font-size: 12px;
  color: #909399;
  line-height: 32px;
}

.preview {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
</style>
