<script setup>
/**
 * 日志管理（审计日志）。
 *
 * ★ 本页是只读的 —— 后端也只提供 GET，没有任何写接口。
 *   「只追加、不修改、不删除」这条规则由四层保证：
 *     1. 代码层：全项目只有 backend/app/services/audit.py 的 append_audit() 会写日志
 *     2. 接口层：/api/audit-logs 只有 GET，POST/PUT/PATCH/DELETE 一律 405
 *     3. 模型层：actor_id 可为 NULL —— 操作者被删，日志必须留下
 *     4. 数据层：actor_name 冗余存快照，即使 actor_id 变 NULL 仍可读
 *
 * ★ 日志的价值在于可追溯：你刚才在别的页面做的每个写操作，
 *   都会在这里出现一条新记录。可以边操作边回来刷新观察。
 */
import { computed, onMounted, ref } from 'vue'
import { Refresh, Warning } from '@element-plus/icons-vue'
import * as api from '@/api'
import { withError } from '@/utils/error'
import { formatTime } from '@/utils/table'
import { actionMeta, TARGET_TYPE_LABELS } from '@/api/meta'

const loading = ref(false)
const logs = ref([])
const actions = ref([])
const filterAction = ref('')
const filterTarget = ref('')
const keyword = ref('')

async function load() {
  loading.value = true
  try {
    logs.value =
      (await withError(() =>
        api.fetchAuditLogs({ action: filterAction.value, target_type: filterTarget.value }),
      )) || []
  } finally {
    loading.value = false
  }
}

async function loadActions() {
  actions.value = (await withError(() => api.fetchAuditActions())) || []
}

/** 前端本地再按关键词过滤（操作者 / 对象 / 详情） */
const filtered = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  if (!kw) return logs.value
  return logs.value.filter((l) => {
    const hay = [
      l.actor_name,
      l.target_name,
      l.action,
      JSON.stringify(l.detail || {}),
    ]
      .join(' ')
      .toLowerCase()
    return hay.includes(kw)
  })
})

function meta(action) {
  return actionMeta(action)
}

function targetLabel(type) {
  return TARGET_TYPE_LABELS[type] || type
}

/** 统计：按动作计数，用于页头概览 */
const stats = computed(() => {
  const map = {}
  for (const l of logs.value) map[l.action] = (map[l.action] || 0) + 1
  return Object.entries(map)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 6)
})

onMounted(async () => {
  await Promise.all([load(), loadActions()])
})
</script>

<template>
  <div class="page-container">
    <div class="page-header">
      <div>
        <h2 class="page-title">日志管理</h2>
        <p class="page-desc">
          权限变更、角色分配、参数修改、登录等操作都会记录在此。
          <strong>日志只追加，不提供修改与删除</strong>。
        </p>
      </div>
      <div class="actions">
        <el-input
          v-model="keyword"
          placeholder="搜索操作者/对象/详情"
          clearable
          style="width: 200px"
        />
        <el-select v-model="filterAction" placeholder="全部动作" clearable style="width: 170px" @change="load">
          <el-option v-for="a in actions" :key="a" :label="meta(a).text" :value="a" />
        </el-select>
        <el-select v-model="filterTarget" placeholder="全部对象" clearable style="width: 130px" @change="load">
          <el-option
            v-for="(label, value) in TARGET_TYPE_LABELS"
            :key="value"
            :label="label"
            :value="value"
          />
        </el-select>
        <el-button :icon="Refresh" @click="load">刷新</el-button>
      </div>
    </div>

    <!-- 概览 -->
    <el-card v-if="stats.length" shadow="never" class="mb">
      <div class="stats">
        <span class="stats-label">共 {{ logs.length }} 条，主要动作：</span>
        <el-tag
          v-for="[action, count] in stats"
          :key="action"
          :type="meta(action).type"
          size="small"
          effect="plain"
          class="mr"
        >
          {{ meta(action).text }} × {{ count }}
        </el-tag>
      </div>
    </el-card>

    <el-card shadow="never">
      <el-table v-loading="loading" :data="filtered" stripe>
        <el-table-column prop="id" label="ID" width="70" />
        <el-table-column label="时间" width="170">
          <template #default="{ row }">
            <span class="perm-code time">{{ formatTime(row.created_at) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作者" width="130">
          <template #default="{ row }">
            <el-tag size="small" effect="plain">{{ row.actor_name }}</el-tag>
            <!-- actor_id 为 null 说明操作者已不存在，日志仍按快照保留 -->
            <el-tooltip v-if="row.actor_id === null" content="该操作者不存在，日志按快照保留">
              <el-icon class="warn-icon"><Warning /></el-icon>
            </el-tooltip>
          </template>
        </el-table-column>
        <el-table-column label="动作" width="150">
          <template #default="{ row }">
            <el-tag :type="meta(row.action).type" size="small">{{ meta(row.action).text }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="对象" width="180">
          <template #default="{ row }">
            <div class="target">
              <span class="target-type muted">{{ targetLabel(row.target_type) }}</span>
              <span v-if="row.target_name" class="perm-code">{{ row.target_name }}</span>
              <span v-else class="muted">—</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="详情" min-width="320">
          <template #default="{ row }">
            <div v-if="row.detail && Object.keys(row.detail).length" class="detail">
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

      <el-empty v-if="!loading && !filtered.length" description="没有匹配的日志" />
    </el-card>

    <el-alert type="info" :closable="false" class="mt">
      <template #title>
        验证「只追加」：到「参数管理」改一个参数值，或到「角色管理」新建一个角色，
        然后回到本页刷新，会看到对应的新记录被追加进来 —— 而既有记录无法被编辑或删除。
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

.mb {
  margin-bottom: 16px;
}

.stats {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px;
}

.stats-label {
  font-size: 13px;
  color: #606266;
  margin-right: 4px;
}

.time {
  color: #606266;
}

.target {
  display: flex;
  align-items: center;
  gap: 6px;
}

.target-type {
  flex-shrink: 0;
}

.warn-icon {
  margin-left: 4px;
  color: #e6a23c;
  vertical-align: middle;
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
</style>
