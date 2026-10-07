<script setup>
/**
 * 规则总览：把散落在各处的调度规则集中展示，并给出硬/软约束清单。
 *
 * ★ 为什么需要这一页：规则本身分散在「车辆类型」「地形矩阵」「参数」
 *   三个地方维护，没有一个地方能一次看清「调度器到底受哪些约束」。
 *   本页把求解器**实际执行的**约束原样列出来（后端 rules_overview 提供），
 *   避免文档写的和代码做的不一致。
 */
import { computed, onMounted, ref } from 'vue'
import { Refresh, Warning } from '@element-plus/icons-vue'
import * as api from '@/api'
import { withError } from '@/utils/error'
import { vehicleTypeCode } from '@/utils/enums'

const loading = ref(false)
const overview = ref(null)
const conflicts = ref([])
const scoreDetail = ref(null)

async function load() {
  loading.value = true
  try {
    const [ov, cf] = await Promise.all([
      withError(() => api.fetchRulesOverview()),
      withError(() => api.fetchRuleConflicts()),
    ])
    overview.value = ov
    conflicts.value = cf || []
  } finally {
    loading.value = false
  }
}

const vehicleTypes = computed(() => overview.value?.vehicle_types || [])
const matrix = computed(() => overview.value?.terrain_matrix || [])
const params = computed(() => overview.value?.params || [])
const hardConstraints = computed(() => overview.value?.hard_constraints || [])
const softConstraints = computed(() => overview.value?.soft_constraints || [])
const scoreFunction = computed(() => overview.value?.score_function || {})

const TERRAIN_LABEL = { normal: '普通', medium: '中控', strict: '严控' }
const CAP_LABEL = { all: '全能去', big_small: '大小包能去', small_only: '小包能去' }

/** 通行矩阵按地形分组，便于紧凑展示 */
const matrixByTerrain = computed(() => {
  const g = {}
  for (const m of matrix.value) {
    if (!g[m.terrain_type]) g[m.terrain_type] = []
    g[m.terrain_type].push(m)
  }
  return g
})

/** 冲突统计 */
const conflictStats = computed(() => {
  const s = { error: 0, warning: 0, info: 0 }
  for (const c of conflicts.value) s[c.level] = (s[c.level] || 0) + 1
  return s
})

const showScoreDetail = () => {
  scoreDetail.value = scoreFunction.value
}

onMounted(load)
</script>

<template>
  <div class="page-container">
    <div class="page-header">
      <div>
        <h2 class="page-title">调度策略与评分</h2>
        <p class="page-desc">
          集中展示调度器实际执行的<strong>全部硬约束与软约束</strong>，以及评分函数。
          具体阈值在「车辆类型」「地形与通行规则」「参数管理」里维护。
        </p>
      </div>
      <el-button :icon="Refresh" @click="load">刷新</el-button>
    </div>

    <!-- 冲突检测 -->
    <el-card shadow="never" class="mb">
      <template #header>
        <div class="card-head">
          <span class="card-title">规则冲突检测</span>
          <div>
            <el-tag v-if="conflictStats.error" type="danger" size="small" class="mr">
              错误 {{ conflictStats.error }}
            </el-tag>
            <el-tag v-if="conflictStats.warning" type="warning" size="small" class="mr">
              警告 {{ conflictStats.warning }}
            </el-tag>
            <el-tag v-if="conflictStats.info" type="info" size="small">
              提示 {{ conflictStats.info }}
            </el-tag>
            <el-tag v-if="!conflicts.length" type="success" size="small">未发现问题</el-tag>
          </div>
        </div>
      </template>

      <el-table v-if="conflicts.length" :data="conflicts" size="small">
        <el-table-column label="级别" width="90">
          <template #default="{ row }">
            <el-tag
              :type="row.level === 'error' ? 'danger' : row.level === 'warning' ? 'warning' : 'info'"
              size="small"
            >
              {{ row.level === 'error' ? '错误' : row.level === 'warning' ? '警告' : '提示' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="type" label="类型" width="150" />
        <el-table-column prop="message" label="说明" min-width="320" />
        <el-table-column prop="suggestion" label="建议" min-width="220" show-overflow-tooltip />
      </el-table>
      <el-empty v-else description="规则组合没有冲突" />
    </el-card>

    <el-row :gutter="16" class="mb">
      <!-- 硬约束 -->
      <el-col :xs="24" :lg="12">
        <el-card v-loading="loading" shadow="never" class="h-full">
          <template #header>
            <span class="card-title">
              硬约束（{{ hardConstraints.length }} 条）—— 违反即方案无效
            </span>
          </template>
          <div class="constraint-list">
            <div v-for="c in hardConstraints" :key="c.code" class="constraint hard">
              <span class="code">{{ c.code }}</span>
              <div>
                <div class="name">{{ c.name }}</div>
                <div class="source">{{ c.source }}</div>
              </div>
            </div>
          </div>
          <div class="note">
            硬约束由确定性代码与 CP-SAT 求解器保证，<strong>不交给 LLM</strong>
            （对应技术方案「LLM 只做解释和辅助」的设计原则）。
            每套方案生成后都会用 validate_solution() 独立复核一遍。
          </div>
        </el-card>
      </el-col>

      <!-- 软约束 -->
      <el-col :xs="24" :lg="12">
        <el-card v-loading="loading" shadow="never" class="h-full">
          <template #header>
            <span class="card-title">
              软约束与目标（{{ softConstraints.length }} 条）—— 尽量满足，计入评分
            </span>
          </template>
          <div class="constraint-list">
            <div v-for="c in softConstraints" :key="c.code" class="constraint soft">
              <span class="code">{{ c.code }}</span>
              <div>
                <div class="name">{{ c.name }}</div>
                <div class="source">{{ c.source }}</div>
              </div>
            </div>
          </div>

          <el-divider content-position="left">评分函数</el-divider>
          <div class="formula">{{ scoreFunction.formula }}</div>
          <div class="note">{{ scoreFunction.note }}</div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 车型规则 -->
    <el-card shadow="never" class="mb">
      <template #header>
        <span class="card-title">车辆类型规则（装载量与趟次）</span>
      </template>
      <el-table :data="vehicleTypes" stripe>
        <el-table-column label="车型" width="110">
          <template #default="{ row }">
            <el-tag :type="vehicleTypeCode(row.code).type" size="small">{{ row.name }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="装载量区间" width="140">
          <template #default="{ row }">
            <span class="perm-code">{{ row.min_load }} – {{ row.max_load }}</span>
          </template>
        </el-table-column>
        <el-table-column label="每日趟次" width="110" align="center">
          <template #default="{ row }">
            <el-tag size="small" effect="plain">{{ row.trips_per_day }} 趟</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="趟次拆分" width="170">
          <template #default="{ row }">
            <span class="muted">上午 {{ row.am_trips }} + 下午 {{ row.pm_trips }}</span>
          </template>
        </el-table-column>
        <el-table-column label="计划保有量" width="110" align="center">
          <template #default="{ row }">{{ row.planned_count }}</template>
        </el-table-column>
        <el-table-column label="建档车辆" width="100" align="center">
          <template #default="{ row }">{{ row.vehicle_count }}</template>
        </el-table-column>
        <el-table-column prop="remark" label="说明" min-width="220" show-overflow-tooltip />
      </el-table>
    </el-card>

    <!-- 地形矩阵 -->
    <el-card shadow="never" class="mb">
      <template #header>
        <span class="card-title">地形 × 车辆能力 通行矩阵</span>
      </template>
      <table class="matrix">
        <thead>
          <tr>
            <th class="corner">地形 \ 能力</th>
            <th v-for="cap in ['all', 'big_small', 'small_only']" :key="cap">
              {{ CAP_LABEL[cap] }}
            </th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="t in ['normal', 'medium', 'strict']" :key="t">
            <th class="row-head">{{ TERRAIN_LABEL[t] }}</th>
            <td
              v-for="cap in ['all', 'big_small', 'small_only']"
              :key="cap"
              :class="{
                allowed: (matrixByTerrain[t] || []).find((x) => x.capability === cap)?.allowed,
                denied: (matrixByTerrain[t] || []).find((x) => x.capability === cap)?.allowed === false,
              }"
            >
              <template v-if="(matrixByTerrain[t] || []).find((x) => x.capability === cap)">
                {{ (matrixByTerrain[t] || []).find((x) => x.capability === cap).allowed ? '允许' : '禁止' }}
              </template>
              <span v-else class="muted">—</span>
            </td>
          </tr>
        </tbody>
      </table>
      <div class="note">
        这张矩阵是硬约束 C3 的判定依据：车辆的地形能力必须覆盖门店的地形。
        修改入口在「业务基础数据 → 地形与通行规则」。
      </div>
    </el-card>

    <!-- 参数 -->
    <el-card shadow="never">
      <template #header>
        <span class="card-title">调度行为参数</span>
      </template>
      <el-table :data="params" stripe size="small">
        <el-table-column label="参数键" width="290">
          <template #default="{ row }">
            <span class="perm-code">{{ row.key }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="name" label="名称" width="160" />
        <el-table-column label="当前值" width="180">
          <template #default="{ row }">
            <el-tag type="success" effect="plain" class="perm-code">{{ row.value }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="group" label="分组" width="90" />
        <el-table-column prop="remark" label="说明" min-width="220" show-overflow-tooltip />
      </el-table>
      <div class="note">修改入口在「系统管理 → 参数管理」。</div>
    </el-card>

    <el-alert type="info" :closable="false" class="mt">
      <template #title>
        <el-icon><Warning /></el-icon>
        规则改动会影响后续调度结果，但<strong>不会改变已生成的方案</strong> ——
        每次调度任务都记录了当时的 rule_version，保证方案可追溯。
        改动后建议到「规则版本治理」发布一个新版本。
      </template>
    </el-alert>
  </div>
</template>

<style scoped>
.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.card-title {
  font-weight: 600;
}

.mb {
  margin-bottom: 16px;
}

.h-full {
  height: 100%;
}

.constraint-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.constraint {
  display: flex;
  gap: 10px;
  padding: 8px 12px;
  border-radius: 6px;
  border-left: 3px solid;
}

.constraint.hard {
  background: #fef0f0;
  border-color: #f56c6c;
}

.constraint.soft {
  background: #fdf6ec;
  border-color: #e6a23c;
}

.code {
  font-family: 'Cascadia Mono', Consolas, monospace;
  font-size: 11px;
  font-weight: 700;
  color: #909399;
  flex-shrink: 0;
  padding-top: 1px;
}

.name {
  font-size: 13px;
  font-weight: 500;
}

.source {
  font-size: 11px;
  color: #909399;
  margin-top: 2px;
}

.formula {
  padding: 10px 12px;
  background: #f5f7fa;
  border-radius: 6px;
  font-family: 'Cascadia Mono', Consolas, Monaco, monospace;
  font-size: 12px;
  line-height: 1.8;
  word-break: break-all;
}

.note {
  margin-top: 12px;
  font-size: 11px;
  color: #909399;
  line-height: 1.7;
}

.matrix {
  width: 100%;
  border-collapse: collapse;
  table-layout: fixed;
}

.matrix th,
.matrix td {
  border: 1px solid #e4e7ed;
  padding: 10px 8px;
  text-align: center;
  font-size: 13px;
}

.matrix thead th {
  background: #f5f7fa;
  font-weight: 600;
}

.corner {
  width: 150px;
  color: #909399;
  font-size: 12px;
  font-weight: 400;
}

.row-head {
  background: #fafafa;
  font-weight: 600;
}

td.allowed {
  background: #f0f9eb;
  color: #529b2e;
}

td.denied {
  background: #fef0f0;
  color: #c45656;
}
</style>
