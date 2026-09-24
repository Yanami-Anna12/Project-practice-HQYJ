<script setup>
/**
 * 规则版本治理（需求 二.2.7）。
 *
 * ★ 这里管的是规则的**版本**，不是规则内容本身：
 *   · 发布版本 = 把当前所有规则冻结成一份快照，并与上一版对比出变更
 *   · 回滚 = 把历史快照写回各规则表，**同时生成一个新版本**保留回滚痕迹
 *
 * ★ 为什么回滚也要生成新版本：版本链只增不减，才能保证「什么时候改了什么」
 *   完整可追溯。删掉历史会让审计断链。
 */
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh, Plus, RefreshLeft, View } from '@element-plus/icons-vue'
import * as api from '@/api'
import { withError, tryAction } from '@/utils/error'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const canManage = computed(() => auth.has('scheduling:create'))

const loading = ref(false)
const versions = ref([])
const overview = ref(null)

async function load() {
  loading.value = true
  try {
    const [vs, ov] = await Promise.all([
      withError(() => api.fetchRuleVersions()),
      withError(() => api.fetchRulesOverview()),
    ])
    versions.value = vs || []
    overview.value = ov
  } finally {
    loading.value = false
  }
}

const currentVersion = computed(() => overview.value?.current_version || '—')

/* ---------------- 发布版本 ---------------- */
const publishVisible = ref(false)
const publishing = ref(false)
const form = ref({ version: '', description: '' })

function openPublish() {
  form.value = { version: '', description: '' }
  publishVisible.value = true
}

async function publish() {
  publishing.value = true
  const { ok, result } = await tryAction(
    () =>
      api.publishRuleVersion({
        version: form.value.version || null,
        description: form.value.description,
      }),
    null,
  )
  publishing.value = false
  if (!ok) return

  publishVisible.value = false
  if (result.change_count === 0) {
    ElMessage.info(`已发布 ${result.version}，与上一版无差异`)
  } else {
    ElMessage.success(`已发布 ${result.version}，检出 ${result.change_count} 项变更`)
  }
  await load()
}

/* ---------------- 查看版本详情 ---------------- */
const detailVisible = ref(false)
const detailLoading = ref(false)
const detail = ref(null)

async function openDetail(row) {
  detailVisible.value = true
  detailLoading.value = true
  detail.value = null
  try {
    detail.value = await withError(() => api.fetchRuleVersion(row.id))
  } finally {
    detailLoading.value = false
  }
}

/** 版本详情里的快照摘要 */
const snapshotSummary = computed(() => {
  const s = detail.value?.snapshot
  if (!s) return null
  return {
    captured_at: s.captured_at,
    vehicle_types: (s.vehicle_types || []).length,
    terrain_matrix: (s.terrain_matrix || []).length,
    params: (s.params || []).length,
    route_strategy: (s.route_strategy || []).length,
    vehicleTypeRows: s.vehicle_types || [],
    paramRows: s.params || [],
  }
})

/* ---------------- 回滚 ---------------- */
const rollingBack = ref(false)

async function rollback(row) {
  try {
    await ElMessageBox.confirm(
      `确定回滚到版本 ${row.version}？\n\n` +
        `这会把「车辆类型规则、地形通行矩阵、参数」恢复到该版本的状态，` +
        `并生成一个新版本记录本次回滚。已生成的调度方案不受影响。`,
      '回滚确认',
      { type: 'warning', confirmButtonText: '回滚', cancelButtonText: '取消' },
    )
  } catch {
    return
  }

  rollingBack.value = true
  const { ok, result } = await tryAction(() => api.rollbackRuleVersion(row.id), null)
  rollingBack.value = false
  if (!ok) return

  ElMessage.success(result.message)
  await load()
}

onMounted(load)
</script>

<template>
  <div class="page-container">
    <div class="page-header">
      <div>
        <h2 class="page-title">规则版本治理</h2>
        <p class="page-desc">
          发布版本会冻结当前全部规则并对比出变更；回滚会把历史快照写回规则表，
          同时生成新版本保留痕迹。需要 <code class="perm-code">scheduling:create</code>。
        </p>
      </div>
      <div class="actions">
        <el-button :icon="Refresh" @click="load">刷新</el-button>
        <el-button v-if="canManage" type="primary" :icon="Plus" @click="openPublish">
          发布新版本
        </el-button>
      </div>
    </div>

    <el-row :gutter="16" class="mb">
      <el-col :xs="12" :sm="6">
        <el-card shadow="never" class="stat">
          <div class="stat-label">当前规则版本</div>
          <div class="stat-value small">
            <el-tag type="success" size="large" class="perm-code">{{ currentVersion }}</el-tag>
          </div>
        </el-card>
      </el-col>
      <el-col :xs="12" :sm="6">
        <el-card shadow="never" class="stat">
          <div class="stat-label">版本总数</div>
          <div class="stat-value">{{ versions.length }}</div>
        </el-card>
      </el-col>
      <el-col :xs="12" :sm="6">
        <el-card shadow="never" class="stat">
          <div class="stat-label">受管规则项</div>
          <div class="stat-value small">
            {{ (overview?.vehicle_types || []).length }} 车型 +
            {{ (overview?.terrain_matrix || []).length }} 矩阵格 +
            {{ (overview?.params || []).length }} 参数
          </div>
        </el-card>
      </el-col>
      <el-col :xs="12" :sm="6">
        <el-card shadow="never" class="stat">
          <div class="stat-label">最新发布时间</div>
          <div class="stat-value small">
            {{ versions.length ? String(versions[0].published_at).replace('T', ' ').slice(0, 16) : '尚未发布' }}
          </div>
        </el-card>
      </el-col>
    </el-row>

    <el-card shadow="never">
      <template #header>
        <span class="card-title">版本历史</span>
      </template>

      <el-table v-loading="loading" :data="versions" stripe>
        <el-table-column label="版本" width="110">
          <template #default="{ row }">
            <el-tag
              :type="row.version === currentVersion ? 'success' : 'info'"
              size="small"
              class="perm-code"
            >
              {{ row.version }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="description" label="说明" width="200" show-overflow-tooltip />
        <el-table-column label="变更摘要" min-width="320">
          <template #default="{ row }">
            <span class="summary">{{ row.change_summary }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="published_by" label="发布人" width="100" />
        <el-table-column label="发布时间" width="170">
          <template #default="{ row }">
            <span class="perm-code">
              {{ String(row.published_at).replace('T', ' ').slice(0, 19) }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="170" fixed="right">
          <template #default="{ row }">
            <el-button size="small" link :icon="View" @click="openDetail(row)">详情</el-button>
            <el-button
              v-if="canManage"
              size="small"
              type="warning"
              link
              :icon="RefreshLeft"
              :loading="rollingBack"
              :disabled="row.version === currentVersion"
              @click="rollback(row)"
            >
              回滚
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-empty v-if="!loading && !versions.length" description="还没有发布过规则版本">
        <el-button v-if="canManage" type="primary" :icon="Plus" @click="openPublish">
          发布第一个版本
        </el-button>
      </el-empty>
    </el-card>

    <el-alert type="info" :closable="false" class="mt">
      <template #title>
        验证流程：改一个参数（例如「参数管理」里的求解超时）→ 回到本页点「发布新版本」→
        变更摘要里会显示 <code class="perm-code">参数 xxx: 30 → 45</code> →
        点「回滚」后参数值会还原，同时多出一个新版本记录这次回滚。
      </template>
    </el-alert>

    <!-- 发布对话框 -->
    <el-dialog v-model="publishVisible" title="发布规则版本" width="520px">
      <el-form label-width="90px">
        <el-form-item label="版本号">
          <el-input v-model="form.version" placeholder="留空自动递增，例如 v1.0.1" />
        </el-form-item>
        <el-form-item label="版本说明">
          <el-input
            v-model="form.description"
            type="textarea"
            :rows="3"
            placeholder="例如：调整四米二装载量上限、放开严控地形通行"
          />
        </el-form-item>
      </el-form>
      <el-alert type="info" :closable="false">
        <template #title>
          发布会把当前「车辆类型规则 + 地形通行矩阵 + 参数」冻结成快照，
          并与上一版对比生成变更摘要。后续调度任务会记录这个版本号。
        </template>
      </el-alert>
      <template #footer>
        <el-button @click="publishVisible = false">取消</el-button>
        <el-button type="primary" :loading="publishing" @click="publish">发布</el-button>
      </template>
    </el-dialog>

    <!-- 版本详情 -->
    <el-dialog v-model="detailVisible" title="版本详情" width="760px" top="7vh">
      <div v-loading="detailLoading">
        <template v-if="snapshotSummary">
          <el-descriptions :column="2" border size="small">
            <el-descriptions-item label="版本">
              <span class="perm-code">{{ detail.version }}</span>
            </el-descriptions-item>
            <el-descriptions-item label="快照时间">
              {{ snapshotSummary.captured_at }}
            </el-descriptions-item>
            <el-descriptions-item label="说明">{{ detail.description || '—' }}</el-descriptions-item>
            <el-descriptions-item label="发布人">{{ detail.published_by }}</el-descriptions-item>
            <el-descriptions-item label="车型规则">
              {{ snapshotSummary.vehicle_types }} 条
            </el-descriptions-item>
            <el-descriptions-item label="通行矩阵">
              {{ snapshotSummary.terrain_matrix }} 格
            </el-descriptions-item>
            <el-descriptions-item label="参数">
              {{ snapshotSummary.params }} 项
            </el-descriptions-item>
            <el-descriptions-item label="线路策略">
              {{ snapshotSummary.route_strategy }} 条
            </el-descriptions-item>
          </el-descriptions>

          <el-divider content-position="left">该版本的车型规则快照</el-divider>
          <el-table :data="snapshotSummary.vehicleTypeRows" size="small" border>
            <el-table-column prop="name" label="车型" width="100" />
            <el-table-column label="装载量" width="130">
              <template #default="{ row }">
                <span class="perm-code">{{ row.min_load }}–{{ row.max_load }}</span>
              </template>
            </el-table-column>
            <el-table-column label="趟次" width="110">
              <template #default="{ row }">
                {{ row.trips_per_day }}（{{ row.am_trips }}+{{ row.pm_trips }}）
              </template>
            </el-table-column>
            <el-table-column prop="planned_count" label="计划保有量" width="110" align="center" />
          </el-table>

          <el-divider content-position="left">该版本的参数快照</el-divider>
          <el-table :data="snapshotSummary.paramRows" size="small" border max-height="240">
            <el-table-column label="参数键" min-width="260">
              <template #default="{ row }">
                <span class="perm-code">{{ row.key }}</span>
              </template>
            </el-table-column>
            <el-table-column label="值" width="200">
              <template #default="{ row }">
                <span class="perm-code">{{ row.value }}</span>
              </template>
            </el-table-column>
          </el-table>
        </template>
        <el-empty v-else description="加载中…" />
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

.card-title {
  font-weight: 600;
}

.mb {
  margin-bottom: 16px;
}

.stat {
  text-align: center;
}

.stat-label {
  font-size: 13px;
  color: #909399;
}

.stat-value {
  font-size: 24px;
  font-weight: 600;
}

.stat-value.small {
  font-size: 15px;
  padding: 4px 0;
  line-height: 1.6;
}

.summary {
  font-size: 12px;
  color: #606266;
  line-height: 1.6;
}
</style>
