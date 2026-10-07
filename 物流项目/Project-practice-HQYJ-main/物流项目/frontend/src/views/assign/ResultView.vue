<script setup>
/**
 * 分配结果 —— 调度产出的方案在各任务上的汇总视图。
 *
 * ★ 与「智能调度 Agent → 调度任务」的区别：
 *   那边是操作入口（创建、看多方案），这边是**结果视角**：
 *   横向对比所有历史任务选用了哪套方案、指标如何、是否已下发。
 */
import { computed, onMounted, ref } from 'vue'
import { Refresh, View } from '@element-plus/icons-vue'
import { useRouter } from 'vue-router'
import * as api from '@/api'
import { withError } from '@/utils/error'
import { taskStatus } from '@/utils/enums'

const router = useRouter()

const loading = ref(false)
const tasks = ref([])
/** { taskId: { plans: [], confirmedPlanId } } */
const planMap = ref({})
const expanded = ref([])

async function load() {
  loading.value = true
  try {
    tasks.value = (await withError(() => api.fetchSchedulingTasks())) || []
    // 为每个任务拉一次详情（任务量不大，直接全取，保证视图完整）
    const entries = await Promise.all(
      tasks.value.slice(0, 20).map(async (t) => {
        const d = await withError(() => api.fetchSchedulingTask(t.id))
        return [t.id, d]
      }),
    )
    const map = {}
    for (const [id, d] of entries) {
      if (!d) continue
      map[id] = {
        plans: d.plans || [],
        recommended: (d.plans || []).find((p) => p.is_recommended),
      }
    }
    planMap.value = map
  } finally {
    loading.value = false
  }
}

const rows = computed(() =>
  tasks.value.map((t) => {
    const info = planMap.value[t.id] || { plans: [], recommended: null }
    return {
      ...t,
      plan_count: info.plans.length,
      recommended: info.recommended,
      total_trips: info.recommended?.trip_count || 0,
      total_vehicles: info.recommended?.vehicle_count || 0,
      avg_load_rate: info.recommended?.avg_load_rate || 0,
      statusMeta: taskStatus(t.status),
    }
  }),
)

const stats = computed(() => {
  const withPlan = rows.value.filter((r) => r.recommended)
  return {
    tasks: rows.value.length,
    withPlan: withPlan.length,
    dispatched: rows.value.filter((r) => ['dispatched', 'completed'].includes(r.status)).length,
    avgLoad:
      withPlan.length
        ? withPlan.reduce((s, r) => s + Number(r.avg_load_rate), 0) / withPlan.length
        : 0,
  }
})

onMounted(load)
</script>

<template>
  <div class="page-container">
    <div class="page-header">
      <div>
        <h2 class="page-title">分配结果</h2>
        <p class="page-desc">
          各次调度选用的方案与关键指标汇总。展开行可看该任务的全部候选方案对比。
        </p>
      </div>
      <div class="actions">
        <el-button :icon="Refresh" @click="load">刷新</el-button>
        <el-button type="primary" @click="router.push('/scheduling/tasks')">
          去创建调度
        </el-button>
      </div>
    </div>

    <el-row :gutter="16" class="mb">
      <el-col :xs="12" :sm="6">
        <el-card shadow="never" class="stat">
          <div class="stat-label">调度任务</div>
          <div class="stat-value">{{ stats.tasks }}</div>
        </el-card>
      </el-col>
      <el-col :xs="12" :sm="6">
        <el-card shadow="never" class="stat">
          <div class="stat-label">已生成方案</div>
          <div class="stat-value">{{ stats.withPlan }}</div>
        </el-card>
      </el-col>
      <el-col :xs="12" :sm="6">
        <el-card shadow="never" class="stat">
          <div class="stat-label">已下发</div>
          <div class="stat-value ok">{{ stats.dispatched }}</div>
        </el-card>
      </el-col>
      <el-col :xs="12" :sm="6">
        <el-card shadow="never" class="stat">
          <div class="stat-label">平均装载率</div>
          <div class="stat-value">{{ stats.avgLoad.toFixed(1) }}%</div>
        </el-card>
      </el-col>
    </el-row>

    <el-card shadow="never">
      <el-table v-loading="loading" :data="rows" stripe row-key="id">
        <el-table-column type="expand">
          <template #default="{ row }">
            <div class="expand-body">
              <div class="expand-title">该任务的候选方案（{{ row.plan_count }} 套）</div>
              <el-table :data="planMap[row.id]?.plans || []" size="small" border>
                <el-table-column label="方案" width="80">
                  <template #default="{ row: p }">
                    <el-tag v-if="p.is_recommended" type="success" size="small">
                      ★ {{ p.plan_code }}
                    </el-tag>
                    <el-tag v-else size="small" effect="plain">{{ p.plan_code }}</el-tag>
                  </template>
                </el-table-column>
                <el-table-column prop="strategy" label="策略" width="180" />
                <el-table-column label="趟次" width="80" align="center">
                  <template #default="{ row: p }">{{ p.trip_count }}</template>
                </el-table-column>
                <el-table-column label="用车" width="80" align="center">
                  <template #default="{ row: p }">{{ p.vehicle_count }}</template>
                </el-table-column>
                <el-table-column label="四米二" width="90" align="right">
                  <template #default="{ row: p }">
                    {{ Number(p.four_two_usage).toFixed(1) }}%
                  </template>
                </el-table-column>
                <el-table-column label="装载率" width="90" align="right">
                  <template #default="{ row: p }">
                    {{ Number(p.avg_load_rate).toFixed(1) }}%
                  </template>
                </el-table-column>
                <el-table-column label="评分" width="90" align="right">
                  <template #default="{ row: p }">
                    <span class="score">{{ Number(p.score).toFixed(1) }}</span>
                  </template>
                </el-table-column>
                <el-table-column label="未满足门店" min-width="140">
                  <template #default="{ row: p }">
                    <span v-if="p.uncovered_stores" class="muted">{{ p.uncovered_stores }}</span>
                    <el-tag v-else type="success" size="small" effect="plain">无</el-tag>
                  </template>
                </el-table-column>
              </el-table>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="code" label="任务编号" width="150">
          <template #default="{ row }">
            <span class="perm-code">{{ row.code }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="schedule_date" label="调度日期" width="110" />
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="row.statusMeta.type" size="small">{{ row.statusMeta.text }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="选用方案" width="130">
          <template #default="{ row }">
            <template v-if="row.recommended">
              <el-tag type="success" size="small">{{ row.recommended.plan_code }}</el-tag>
              <span class="ml-sm">{{ row.recommended.strategy }}</span>
            </template>
            <span v-else class="muted">未生成</span>
          </template>
        </el-table-column>
        <el-table-column label="趟次" width="80" align="center">
          <template #default="{ row }">{{ row.total_trips }}</template>
        </el-table-column>
        <el-table-column label="用车" width="80" align="center">
          <template #default="{ row }">{{ row.total_vehicles }}</template>
        </el-table-column>
        <el-table-column label="装载率" width="100" align="right">
          <template #default="{ row }">
            {{ Number(row.avg_load_rate).toFixed(1) }}%
          </template>
        </el-table-column>
        <el-table-column prop="created_by" label="创建人" width="100" />
        <el-table-column label="操作" width="100" fixed="right">
          <template #default>
            <el-button size="small" type="primary" link :icon="View"
                       @click="router.push('/scheduling/tasks')">
              查看
            </el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!loading && !rows.length" description="还没有调度任务">
        <el-button type="primary" @click="router.push('/scheduling/tasks')">
          去创建调度
        </el-button>
      </el-empty>
    </el-card>
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

.stat-value.ok {
  color: #67c23a;
}

.expand-body {
  padding: 12px 20px 16px;
  background: #fafafa;
}

.expand-title {
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 8px;
  color: #606266;
}

.score {
  font-family: 'Cascadia Mono', Consolas, monospace;
  font-weight: 600;
}

.ml-sm {
  margin-left: 6px;
  font-size: 12px;
  color: #909399;
}
</style>
