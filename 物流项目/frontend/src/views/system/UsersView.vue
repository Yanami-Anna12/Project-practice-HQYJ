<script setup>
/**
 * 用户管理。
 *
 * ★ 权限并集的可视化入口：
 *   给 multi 账号同时勾选「调度员」和「只读观察者」，保存后「有效权限」列
 *   显示的是两者权限的**并集**，而不是取交集或取最严。
 *
 * ★ 「删除保护」的对应设计在角色页：角色仍被用户引用时不允许删除。
 */
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh, InfoFilled } from '@element-plus/icons-vue'
import * as api from '@/api'
import { useTable, formatTime } from '@/utils/table'
import { tryAction } from '@/utils/error'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()

const { loading, rows: users, load } = useTable(api.fetchUsers)
const roles = ref([])

const dialogVisible = ref(false)
const submitting = ref(false)
const currentUser = ref(null)
const selectedRoles = ref([])

const canManage = computed(() => auth.has('users:manage'))

async function loadRoles() {
  const list = await api.fetchRoles().catch(() => [])
  roles.value = list || []
}

function openAssign(row) {
  currentUser.value = row
  selectedRoles.value = [...row.roles]
  dialogVisible.value = true
}

/** 只有启用的角色才能分配 */
const assignableRoles = computed(() => roles.value.filter((r) => r.is_active))

/** 保存后的权限并集预览（前端预览，以保存返回为准） */
const previewPermissions = computed(() => {
  const set = new Set()
  for (const code of selectedRoles.value) {
    const role = roles.value.find((r) => r.code === code)
    if (role) role.permission_codes.forEach((p) => set.add(p))
  }
  return [...set].sort()
})

async function submit() {
  submitting.value = true
  const { ok, result } = await tryAction(
    () => api.setUserRoles(currentUser.value.id, selectedRoles.value),
    null,
  )
  submitting.value = false
  if (!ok) return
  dialogVisible.value = false
  ElMessage.success(
    `已保存：角色 ${result.roles.join(' + ') || '无'}，权限并集 ${result.permissions.length} 个`,
  )
  await load()
}

async function toggleActive(row) {
  const { ok } = await tryAction(
    () => api.toggleUserActive(row.id),
    `${row.username} 已${row.is_active ? '停用' : '启用'}`,
  )
  if (ok) await load()
}

async function resetPassword(row) {
  const { ok, result } = await tryAction(() => api.resetUserPassword(row.id))
  if (!ok) return
  ElMessageBox.alert(
    `账号 ${row.username} 的密码已重置为：${result.password}`,
    '重置成功',
    { confirmButtonText: '知道了' },
  )
}

onMounted(async () => {
  await Promise.all([load(), loadRoles()])
})
</script>

<template>
  <div class="page-container">
    <div class="page-header">
      <div>
        <h2 class="page-title">用户管理</h2>
        <p class="page-desc">
          给用户分配角色。勾选多个角色时，权限为<strong>并集</strong>，不是取最严。
          写操作需要 <code class="perm-code">users:manage</code>。
        </p>
      </div>
      <el-button :icon="Refresh" @click="load">刷新</el-button>
    </div>

    <el-card shadow="never">
      <el-table v-loading="loading" :data="users" stripe>
        <el-table-column prop="id" label="ID" width="60" />
        <el-table-column prop="username" label="用户名" width="120">
          <template #default="{ row }">
            <span class="perm-code">{{ row.username }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="nickname" label="昵称" width="110" />
        <el-table-column prop="dept" label="部门" width="100" />
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="row.is_active ? 'success' : 'danger'" size="small" effect="plain">
              {{ row.is_active ? '正常' : '停用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="绑定角色" min-width="170">
          <template #default="{ row }">
            <template v-if="row.roles.length">
              <el-tag
                v-for="code in row.roles"
                :key="code"
                size="small"
                class="mr"
                :type="row.roles.length > 1 ? 'warning' : ''"
              >
                {{ code }}
              </el-tag>
              <el-tooltip v-if="row.roles.length > 1" content="多角色：权限为各角色权限的并集">
                <el-icon color="#e6a23c"><InfoFilled /></el-icon>
              </el-tooltip>
            </template>
            <el-tag v-else type="danger" size="small" effect="plain">无角色 · 无任何权限</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="有效权限（并集）" min-width="300">
          <template #default="{ row }">
            <span v-if="!row.permissions.length" class="muted">—</span>
            <el-tag
              v-for="code in row.permissions"
              :key="code"
              size="small"
              type="success"
              effect="plain"
              class="mr perm-code"
            >
              {{ code }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="创建时间" width="160">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="200" fixed="right">
          <template #default="{ row }">
            <el-button size="small" type="primary" link @click="openAssign(row)">
              分配角色
            </el-button>
            <el-button
              v-if="canManage"
              size="small"
              type="warning"
              link
              :disabled="row.is_self"
              @click="toggleActive(row)"
            >
              {{ row.is_active ? '停用' : '启用' }}
            </el-button>
            <el-button v-if="canManage" size="small" link @click="resetPassword(row)">
              重置密码
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-alert type="success" :closable="false" class="mt">
      <template #title>
        验证「权限并集」：把 <strong>multi</strong> 账号改成「调度员 + 只读观察者」，
        观察「有效权限」列会同时包含两个角色的权限点。
        用 <strong>multi</strong> 登录后，侧边栏能看到「智能调度 Agent」，但看不到「系统管理」。
      </template>
    </el-alert>

    <!-- 角色分配对话框 -->
    <el-dialog v-model="dialogVisible" width="620px" :title="`为 ${currentUser?.username} 分配角色`">
      <el-alert v-if="currentUser" type="info" :closable="false" class="dialog-tip">
        <template #title>
          当前角色：{{ currentUser.roles.join(' + ') || '无' }} ·
          当前有效权限 {{ currentUser.permissions.length }} 个
        </template>
      </el-alert>

      <el-checkbox-group v-model="selectedRoles" class="role-group">
        <div v-for="role in assignableRoles" :key="role.code" class="role-item">
          <el-checkbox :value="role.code">
            <span class="role-name">{{ role.name }}</span>
            <span class="role-code perm-code">{{ role.code }}</span>
          </el-checkbox>
          <div class="role-perms">
            <el-tag
              v-for="code in role.permission_codes"
              :key="code"
              size="small"
              effect="plain"
              class="mr perm-code"
            >
              {{ code }}
            </el-tag>
            <span v-if="!role.permission_codes.length" class="muted">未绑定权限点</span>
          </div>
        </div>
      </el-checkbox-group>

      <el-divider content-position="left">保存后的权限并集预览</el-divider>
      <div class="preview">
        <el-tag
          v-for="code in previewPermissions"
          :key="code"
          size="small"
          type="success"
          class="mr perm-code"
        >
          {{ code }}
        </el-tag>
        <span v-if="!previewPermissions.length" class="muted">
          未选择角色 → 该用户将没有任何权限，所有受保护页面都无法访问
        </span>
      </div>

      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submit">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.dialog-tip {
  margin-bottom: 12px;
}

.role-group {
  display: flex;
  flex-direction: column;
  gap: 10px;
  width: 100%;
}

.role-item {
  padding: 10px 12px;
  border: 1px solid #e4e7ed;
  border-radius: 6px;
}

.role-name {
  font-weight: 600;
  margin-right: 8px;
}

.role-code {
  color: #909399;
}

.role-perms {
  margin-top: 6px;
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.preview {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  min-height: 24px;
}
</style>
