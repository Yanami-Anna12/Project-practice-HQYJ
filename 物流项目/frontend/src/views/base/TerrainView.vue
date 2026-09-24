<script setup>
/**
 * 地形与通行规则。
 *
 * ★ 本页是「哪类车能进哪种地形」的唯一配置点，用矩阵形式呈现：
 *     行 = 地形（普通 / 中控 / 严控）
 *     列 = 车辆地形能力（全能去 / 大小包能去 / 小包能去）
 *   点格子即可切换允许/禁止，改完立即写入后端并记审计日志。
 *
 * ★ 这张矩阵是调度器的硬约束来源之一：车辆地形能力必须覆盖门店地形。
 *   例如「严控 + 小包能去」被禁止，那么严控地形的门店就只能由
 *   「全能去」的车辆服务 —— 如果没有这种车，方案会无解。
 */
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh, Warning } from '@element-plus/icons-vue'
import * as api from '@/api'
import { withError, tryAction } from '@/utils/error'
import { TERRAIN_TYPE_OPTIONS, TERRAIN_CAPABILITY_OPTIONS } from '@/utils/enums'

const loading = ref(false)
const rules = ref([])
const matrix = ref([])
const stores = ref([])

/** 把扁平的矩阵列表转成 地形 → 能力 → 单元格 的二维结构 */
const grid = computed(() => {
  const g = {}
  for (const t of TERRAIN_TYPE_OPTIONS) {
    g[t.value] = { label: t.label, cells: {} }
  }
  for (const cell of matrix.value) {
    if (!g[cell.terrain_type]) {
      g[cell.terrain_type] = { label: cell.terrain_type, cells: {} }
    }
    g[cell.terrain_type].cells[cell.capability] = cell
  }
  return g
})

/** 各地形下的门店数量，用于说明这张矩阵的实际影响面 */
const storeCountByTerrain = computed(() => {
  const map = {}
  for (const s of stores.value) {
    map[s.terrain_type] = (map[s.terrain_type] || 0) + 1
  }
  return map
})

/** 某地形下是否还有允许的车辆能力 —— 全禁则该地形的门店无法被覆盖 */
function countAllowedFor(terrainCode, source) {
  const row = source[terrainCode]
  if (!row) return 0
  return Object.values(row.cells).some((c) => c.allowed) ? 1 : 0
}

async function load() {
  loading.value = true
  try {
    const [ruleList, matrixList, storeList] = await Promise.all([
      withError(() => api.fetchTerrainRules()),
      withError(() => api.fetchTerrainMatrix()),
      withError(() => api.fetchStores()),
    ])
    rules.value = ruleList || []
    matrix.value = matrixList || []
    stores.value = storeList || []
  } finally {
    loading.value = false
  }
}

const togglingId = ref(null)

async function toggle(cell) {
  if (!cell) return
  const terrainLabel = grid.value[cell.terrain_type]?.label || cell.terrain_type
  const capLabel =
    (TERRAIN_CAPABILITY_OPTIONS.find((o) => o.value === cell.capability) || {}).label ||
    cell.capability

  togglingId.value = cell.id
  const { ok } = await tryAction(
    () => api.updateTerrainMatrix(cell.id, { allowed: !cell.allowed }),
    `${terrainLabel} × ${capLabel}：已${cell.allowed ? '禁止' : '允许'}通行`,
  )
  togglingId.value = null
  if (!ok) return

  await load()

  // 全禁时给出明确警示，而不是让人自己去发现问题
  if (!countAllowedFor(cell.terrain_type, grid.value)) {
    ElMessage.warning(
      `${terrainLabel}地形的所有车辆能力都被禁止，该地形的门店将无法被任何方案覆盖`,
    )
  }
}

onMounted(load)
</script>

<template>
  <div class="page-container">
    <div class="page-header">
      <div>
        <h2 class="page-title">地形与通行规则</h2>
        <p class="page-desc">
          车辆的<strong>地形能力</strong>必须覆盖门店的<strong>地形限制</strong>，否则该车无法服务该门店。
          点格子即可切换允许/禁止，改完立即生效并记入审计日志。
          需要 <code class="perm-code">terrain:manage</code>。
        </p>
      </div>
      <el-button :icon="Refresh" @click="load">刷新</el-button>
    </div>

    <!-- 地形等级说明 -->
    <el-card shadow="never" class="mb">
      <template #header>
        <span class="card-title">地形管控等级</span>
      </template>
      <el-table :data="rules" size="small">
        <el-table-column label="地形" width="110">
          <template #default="{ row }">
            <el-tag size="small">{{ row.name }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="编码" width="100">
          <template #default="{ row }">
            <span class="perm-code">{{ row.code }}</span>
          </template>
        </el-table-column>
        <el-table-column label="管控等级" width="100" align="center">
          <template #default="{ row }">
            <el-tag size="small" effect="plain">{{ row.level }} 级</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="受影响门店" width="110" align="center">
          <template #default="{ row }">
            <el-tag
              size="small"
              :type="storeCountByTerrain[row.code] ? 'warning' : 'info'"
              effect="plain"
            >
              {{ storeCountByTerrain[row.code] || 0 }} 个
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="description" label="说明" min-width="240" />
      </el-table>
    </el-card>

    <!-- 通行矩阵 -->
    <el-card v-loading="loading" shadow="never">
      <template #header>
        <span class="card-title">地形 × 车辆能力 通行矩阵</span>
      </template>

      <table class="matrix">
        <thead>
          <tr>
            <th class="corner">地形 \ 车辆能力</th>
            <th v-for="c in TERRAIN_CAPABILITY_OPTIONS" :key="c.value">
              {{ c.label }}
              <div class="cap-code perm-code">{{ c.value }}</div>
            </th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="t in TERRAIN_TYPE_OPTIONS" :key="t.value">
            <th class="row-head">
              {{ t.label }}
              <div class="cap-code perm-code">{{ t.value }}</div>
            </th>
            <td
              v-for="c in TERRAIN_CAPABILITY_OPTIONS"
              :key="c.value"
              class="cell"
              :class="{
                allowed: grid[t.value]?.cells[c.value]?.allowed,
                denied: grid[t.value]?.cells[c.value] && !grid[t.value].cells[c.value].allowed,
                busy: togglingId === grid[t.value]?.cells[c.value]?.id,
              }"
              @click="toggle(grid[t.value]?.cells[c.value])"
            >
              <template v-if="grid[t.value]?.cells[c.value]">
                <el-icon v-if="grid[t.value].cells[c.value].allowed" :size="18">
                  <Select />
                </el-icon>
                <el-icon v-else :size="18"><CloseBold /></el-icon>
                <div class="cell-text">
                  {{ grid[t.value].cells[c.value].allowed ? '允许' : '禁止' }}
                </div>
              </template>
              <span v-else class="muted">—</span>
            </td>
          </tr>
        </tbody>
      </table>

      <div class="legend">
        <span class="legend-item"><i class="dot green"></i>允许通行</span>
        <span class="legend-item"><i class="dot red"></i>禁止通行</span>
        <span class="legend-item muted">点击格子切换</span>
      </div>
    </el-card>

    <el-alert type="warning" :closable="false" class="mt">
      <template #title>
        <el-icon><Warning /></el-icon>
        注意：如果某个地形的所有车辆能力都被禁止，该地形的门店将<strong>无法被任何方案覆盖</strong>，
        调度会无解。当前配置：普通地形允许
        {{ Object.values(grid.normal?.cells || {}).filter((c) => c.allowed).length }} 种能力，
        中控 {{ Object.values(grid.medium?.cells || {}).filter((c) => c.allowed).length }} 种，
        严控 {{ Object.values(grid.strict?.cells || {}).filter((c) => c.allowed).length }} 种。
      </template>
    </el-alert>
  </div>
</template>

<style scoped>
.card-title {
  font-weight: 600;
}

.mb {
  margin-bottom: 16px;
}

.matrix {
  width: 100%;
  border-collapse: collapse;
  table-layout: fixed;
}

.matrix th,
.matrix td {
  border: 1px solid #e4e7ed;
  padding: 12px 8px;
  text-align: center;
  font-size: 13px;
}

.matrix thead th {
  background: #f5f7fa;
  font-weight: 600;
}

.corner {
  width: 160px;
  color: #909399;
  font-size: 12px;
  font-weight: 400;
}

.row-head {
  background: #fafafa;
  font-weight: 600;
  width: 160px;
}

.cap-code {
  font-size: 11px;
  color: #a8abb2;
  font-weight: 400;
  margin-top: 2px;
}

.cell {
  cursor: pointer;
  transition: all 0.15s;
  user-select: none;
}

.cell:hover {
  background: #ecf5ff;
}

.cell.allowed {
  background: #f0f9eb;
  color: #529b2e;
}

.cell.denied {
  background: #fef0f0;
  color: #c45656;
}

.cell.busy {
  opacity: 0.5;
}

.cell-text {
  font-size: 12px;
  margin-top: 2px;
}

.legend {
  display: flex;
  gap: 16px;
  margin-top: 12px;
  font-size: 12px;
  color: #606266;
}

.legend-item {
  display: flex;
  align-items: center;
  gap: 5px;
}

.dot {
  display: inline-block;
  width: 10px;
  height: 10px;
  border-radius: 2px;
}

.dot.green {
  background: #b3e19d;
}

.dot.red {
  background: #fab6b6;
}
</style>
