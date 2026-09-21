<script setup>
/**
 * 用户管理（需要 users:manage，仅管理员）。
 *
 * ★ 这是 R1「多角色并集」最直观的验证入口：
 *   给一个用户同时勾选「运营」和「只读」，保存后右侧权限列会显示
 *   两者权限的**并集**（含 products:edit），而不是取交集或最严。
 *
 * ★ 也是 R3 的验证前置：只有当某角色不再被任何用户引用时，
 *   才能在角色管理页把它删掉。
 */
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { InfoFilled, Refresh } from '@element-plus/icons-vue'
import * as api from '@/api'

const loading = ref(false)
const users = ref([])
const roles = ref([])

const dialogVisible = ref(false)
const submitting = ref(false)
const currentUser = ref(null)
const selectedRoles = ref([])

async function load() {
  loading.value = true
  try {
    const [userList, roleList] = await Promise.all([api.fetchUsers(), api.fetchRoles()])
    users.value = userList
    roles.value = roleList
  } finally {
    loading.value = false
  }
}

function openAssign(row) {
  currentUser.value = row
  selectedRoles.value = [...row.roles]
  dialogVisible.value = true
}

/** 实时预览：勾选的角色对应的权限并集（前端预览，保存后以后端返回为准） */
const previewPermissions = computed(() => {
  const set = new Set()
  for (const code of selectedRoles.value) {
    const role = roles.value.find((r) => r.code === code)
    if (role) role.permission_codes.forEach((p) => set.add(p))
  }
  return [...set].sort()
})

/** 只有被启用的角色才能分配 */
const assignableRoles = computed(() => roles.value.filter((r) => r.is_active))

async function submit() {
  submitting.value = true
  try {
    const result = await api.setUserRoles(currentUser.value.id, selectedRoles.value)
    ElMessage.success(
      `已保存：角色 ${result.roles.join(' + ') || '无'}，权限并集 ${result.permissions.length} 个`,
    )
    dialogVisible.value = false
    await load()
  } finally {
    submitting.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="page-container">
    <div class="page-header">
      <div>
        <h2 class="page-title">用户管理</h2>
        <p class="page-desc">
          给用户分配角色（需要 <code class="perm-code">users:manage</code>）。
          勾选多个角色时，权限为<strong>并集</strong>，不是取最严。
        </p>
      </div>
      <el-button :icon="Refresh" @click="load">刷新</el-button>
    </div>

    <el-card shadow="never">
      <el-table v-loading="loading" :data="users" stripe>
        <el-table-column prop="id" label="ID" width="70" />
        <el-table-column prop="username" label="用户名" width="130">
          <template #default="{ row }">
            <span class="perm-code">{{ row.username }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="nickname" label="昵称" width="130" />
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="row.is_active ? 'success' : 'danger'" size="small" effect="plain">
              {{ row.is_active ? '正常' : '停用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="绑定角色" min-width="180">
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
        <el-table-column label="有效权限（并集）" min-width="280">
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
        <el-table-column label="操作" width="110" fixed="right">
          <template #default="{ row }">
            <el-button size="small" type="primary" link @click="openAssign(row)">
              分配角色
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-alert type="success" :closable="false" class="mt">
      <template #title>
        验证 R1：把 <strong>multi</strong> 账号只留「只读」，或改成「运营 + 只读」，
        观察「有效权限」列的变化 —— 后者会多出 <code>products:edit</code>，这就是并集。
      </template>
    </el-alert>

    <!-- 角色分配对话框 -->
    <el-dialog v-model="dialogVisible" width="560px" :title="`为 ${currentUser?.username} 分配角色`">
      <el-alert v-if="currentUser" type="info" :closable="false" class="dialog-tip">
        <template #title>
          当前角色：{{ currentUser.roles.join(' + ') || '无' }} ·
          当前权限 {{ currentUser.permissions.length }} 个
        </template>
      </el-alert>

      <el-checkbox-group v-model="selectedRoles" class="role-group">
        <div v-for="role in assignableRoles" :key="role.code" class="role-item">
          <el-checkbox :value="role.code" :label="role.code">
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
          未选择角色 → 该用户将没有任何权限，所有受保护接口都会返回 403
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

code {
  background: #f4f4f5;
  padding: 1px 5px;
  border-radius: 3px;
}
</style>
