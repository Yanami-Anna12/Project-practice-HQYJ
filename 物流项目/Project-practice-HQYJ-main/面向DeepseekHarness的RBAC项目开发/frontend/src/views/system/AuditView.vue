<script setup>
/**
 * 审计日志（需要 users:manage，仅管理员）。
 *
 * 本页是只读的 —— 后端也只提供 GET，没有任何写接口。
 * 「只追加、不修改、不删除」这条规则（R5）由四层共同保证：
 *   1. 代码层：全项目只有 services/audit.py 的 append_audit() 会写日志，且只做 INSERT
 *   2. 接口层：本页对应的接口只有 GET，POST/PUT/PATCH/DELETE 一律 405
 *   3. 模型层：actor_id 用 ON DELETE SET NULL —— 操作者被删，日志必须留下
 *   4. 数据层：actor_name 冗余存快照，即使 actor_id 变 NULL 仍可读
 */
import { onMounted, ref } from 'vue'
import { Refresh, Warning } from '@element-plus/icons-vue'
import * as api from '@/api'

const loading = ref(false)
const logs = ref([])
const filterAction = ref('')
const filterTarget = ref('')

/** 动作名的中文说明与标签颜色 */
const actionMeta = {
  'role.create': { text: '新建角色', type: 'success' },
  'role.update': { text: '更新角色', type: 'primary' },
  'role.delete': { text: '删除角色', type: 'danger' },
  'role.assign_permissions': { text: '调整角色权限', type: 'warning' },
  'user.assign_roles': { text: '调整用户角色', type: 'warning' },
  'permission.create': { text: '新建权限点', type: 'success' },
  'permission.toggle': { text: '启停权限点', type: 'danger' },
  'auth.login': { text: '登录成功', type: 'info' },
  'auth.login_failed': { text: '登录失败', type: 'danger' },
  'system.seed': { text: '系统初始化', type: 'info' },
}

const actionOptions = Object.keys(actionMeta)

async function load() {
  loading.value = true
  try {
    const params = { limit: 200 }
    if (filterAction.value) params.action = filterAction.value
    if (filterTarget.value) params.target_type = filterTarget.value
    logs.value = await api.fetchAuditLogs(params)
  } finally {
    loading.value = false
  }
}

function meta(action) {
  return actionMeta[action] || { text: action, type: 'info' }
}

onMounted(load)
</script>

<template>
  <div class="page-container">
    <div class="page-header">
      <div>
        <h2 class="page-title">审计日志</h2>
        <p class="page-desc">
          权限变更、角色分配、登录等操作都会记录在此。
          <strong>日志只追加，不提供修改与删除接口</strong>（R5）。
        </p>
      </div>
      <div class="actions">
        <el-select v-model="filterAction" placeholder="全部动作" clearable style="width: 180px" @change="load">
          <el-option v-for="a in actionOptions" :key="a" :label="meta(a).text" :value="a" />
        </el-select>
        <el-select v-model="filterTarget" placeholder="全部目标" clearable style="width: 140px" @change="load">
          <el-option label="角色" value="role" />
          <el-option label="用户" value="user" />
          <el-option label="权限点" value="permission" />
          <el-option label="系统" value="system" />
        </el-select>
        <el-button :icon="Refresh" @click="load">刷新</el-button>
      </div>
    </div>

    <el-card shadow="never">
      <el-table v-loading="loading" :data="logs" stripe>
        <el-table-column prop="id" label="ID" width="80" />
        <el-table-column label="时间" width="170">
          <template #default="{ row }">
            {{ String(row.created_at).replace('T', ' ').slice(0, 19) }}
          </template>
        </el-table-column>
        <el-table-column label="操作者" width="120">
          <template #default="{ row }">
            <el-tag size="small" effect="plain">{{ row.actor_name }}</el-tag>
            <!-- actor_id 为 NULL 说明操作者已被删除，日志依然保留（快照机制） -->
            <el-tooltip v-if="row.actor_id === null" content="该操作者已被删除，日志按快照保留">
              <el-icon class="deleted-icon"><Warning /></el-icon>
            </el-tooltip>
          </template>
        </el-table-column>
        <el-table-column label="动作" width="150">
          <template #default="{ row }">
            <el-tag :type="meta(row.action).type" size="small">{{ meta(row.action).text }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="对象" width="160">
          <template #default="{ row }">
            <span v-if="row.target_name" class="perm-code">{{ row.target_name }}</span>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="详情" min-width="320">
          <template #default="{ row }">
            <div v-if="row.detail" class="detail">
              <div v-for="(value, key) in row.detail" :key="key" class="detail-line">
                <span class="detail-key">{{ key }}：</span>
                <span class="detail-value">
                  {{ Array.isArray(value) ? (value.length ? value.join('、') : '（无）') : value }}
                </span>
              </div>
            </div>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
      </el-table>

      <el-empty v-if="!loading && !logs.length" description="暂无审计日志" />
    </el-card>

    <el-alert type="info" :closable="false" class="mt">
      <template #title>
        可以到「角色管理」新建/删除一个角色，或到「权限点管理」停用某个权限点，
        然后回到本页刷新，就能看到对应的审计记录被追加进来。
      </template>
    </el-alert>
  </div>
</template>

<style scoped>
.actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.mt {
  margin-top: 16px;
}

.muted {
  color: #909399;
}

.detail {
  font-size: 12px;
  line-height: 1.7;
}

.detail-line {
  display: flex;
  gap: 4px;
}

.detail-key {
  color: #909399;
  flex-shrink: 0;
}

.detail-value {
  color: #303133;
  word-break: break-all;
}

.deleted-icon {
  margin-left: 4px;
  color: #e6a23c;
  vertical-align: middle;
}
</style>
