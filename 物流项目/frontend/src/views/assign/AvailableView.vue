<script setup>
/**
 * 可出勤车辆 —— 调度当天的运力池。
 *
 * ★ 「可出勤」的判定口径（与后端 build_solve_input 一致）：
 *     车辆启用 + 状态非维保 + 绑定司机未请假
 *   需求文档的「动态车辆调节」指的是不保障每天 28/3/9 台满勤，
 *   实际出勤数按这里的情况动态决定。
 */
import { computed, onMounted, ref } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import * as api from '@/api'
import { withError } from '@/utils/error'
import { terrainCapability, vehicleStatus, vehicleTypeCode } from '@/utils/enums'

const loading = ref(false)
const vehicles = ref([])
const drivers = ref([])
const vehicleTypes = ref([])

async function load() {
  loading.value = true
  try {
    const [v, d, t] = await Promise.all([
      withError(() => api.fetchVehicles()),
      withError(() => api.fetchDrivers()),
      withError(() => api.fetchVehicleTypes()),
    ])
    vehicles.value = v || []
    drivers.value = d || []
    vehicleTypes.value = t || []
  } finally {
    loading.value = false
  }
}

const driverById = computed(() => {
  const m = {}
  for (const d of drivers.value) m[d.id] = d
  return m
})
const typeByCode = computed(() => {
  const m = {}
  for (const t of vehicleTypes.value) m[t.code] = t
  return m
})

/** 请假/停用的司机，其绑定车辆当天不可出勤 */
const unavailableDriverIds = computed(
  () => new Set(drivers.value.filter((d) => d.status !== 'available').map((d) => d.id)),
)

function isAvailable(v) {
  if (!v.is_active) return false
  if (v.status === 'maintenance') return false
  if (v.driver_id && unavailableDriverIds.value.has(v.driver_id)) return false
  return true
}

const available = computed(() => vehicles.value.filter(isAvailable))
const unavailableList = computed(() => vehicles.value.filter((v) => !isAvailable(v)))

/** 按车型统计可出勤数 */
const byType = computed(() => {
  const m = {}
  for (const v of available.value) {
    m[v.vehicle_type_code] = (m[v.vehicle_type_code] || 0) + 1
  }
  return m
})

/** 可出勤运力（趟次容量） */
const capacity = computed(() =>
  available.value.reduce((sum, v) => {
    const t = typeByCode.value[v.vehicle_type_code]
    return sum + (t ? t.max_load * t.trips_per_day : 0)
  }, 0),
)

/** 按车型汇总计划保有量对比 */
const plannedCompare = computed(() =>
  vehicleTypes.value.map((t) => ({
    code: t.code,
    name: t.name,
    planned: t.planned_count,
    actual: t.vehicle_count,
    available: byType.value[t.code] || 0,
    trips: t.trips_per_day,
  })),
)

/** 不可出勤原因 */
function reason(v) {
  if (!v.is_active) return '车辆已停用'
  if (v.status === 'maintenance') return '维保中'
  if (v.driver_id && unavailableDriverIds.value.has(v.driver_id)) {
    const d = driverById.value[v.driver_id]
    return `司机${d?.name || ''}${d?.status === 'leave' ? '请假' : '停用'}`
  }
  return '—'
}

function reasonTag(v) {
  if (!v.is_active) return 'info'
  if (v.status === 'maintenance') return 'warning'
  return 'danger'
}

onMounted(load)
</script>

<template>
  <div class="page-container">
    <div class="page-header">
      <div>
        <h2 class="page-title">可出勤车辆</h2>
        <p class="page-desc">
          调度当天的运力池：车辆启用、状态非维保、绑定司机未请假才算可出勤。
          需求文档的「动态车辆调节」即不保障每天 28/3/9 台满勤，按实际出勤数排班。
        </p>
      </div>
      <el-button :icon="Refresh" @click="load">刷新</el-button>
    </div>

    <el-row :gutter="16" class="mb">
      <el-col :xs="12" :sm="6">
        <el-card shadow="never" class="stat">
          <div class="stat-label">可出勤车辆</div>
          <div class="stat-value ok">{{ available.length }}</div>
          <div class="stat-note">共 {{ vehicles.length }} 台建档</div>
        </el-card>
      </el-col>
      <el-col :xs="12" :sm="6">
        <el-card shadow="never" class="stat">
          <div class="stat-label">不可出勤</div>
          <div class="stat-value warn">{{ unavailableList.length }}</div>
          <div class="stat-note">维保 / 司机请假 / 停用</div>
        </el-card>
      </el-col>
      <el-col :xs="12" :sm="6">
        <el-card shadow="never" class="stat">
          <div class="stat-label">日运力</div>
          <div class="stat-value">{{ capacity.toFixed(0) }}</div>
          <div class="stat-note">Σ(最大装载量 × 日趟次)</div>
        </el-card>
      </el-col>
      <el-col :xs="12" :sm="6">
        <el-card shadow="never" class="stat">
          <div class="stat-label">日趟次上限</div>
          <div class="stat-value">
            {{ available.reduce((s, v) => s + (typeByCode[v.vehicle_type_code]?.trips_per_day || 0), 0) }}
          </div>
          <div class="stat-note">Σ(可出勤车辆日趟次)</div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 计划保有量对比 -->
    <el-card shadow="never" class="mb">
      <template #header>
        <span class="card-title">与计划保有量的对比</span>
      </template>
      <el-table :data="plannedCompare" size="small">
        <el-table-column prop="name" label="车型" width="100" />
        <el-table-column label="计划保有量" width="120" align="center">
          <template #default="{ row }">{{ row.planned }}</template>
        </el-table-column>
        <el-table-column label="实际建档" width="110" align="center">
          <template #default="{ row }">{{ row.actual }}</template>
        </el-table-column>
        <el-table-column label="当日可出勤" width="120" align="center">
          <template #default="{ row }">
            <el-tag
              size="small"
              :type="row.available === row.planned ? 'success' : 'warning'"
              effect="plain"
            >
              {{ row.available }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="日趟次" width="90" align="center">
          <template #default="{ row }">{{ row.trips }}</template>
        </el-table-column>
        <el-table-column label="达成情况" min-width="200">
          <template #default="{ row }">
            <el-progress
              :percentage="row.planned ? Math.min(100, (row.available / row.planned) * 100) : 0"
              :stroke-width="12"
              :color="row.available >= row.planned ? '#67c23a' : '#e6a23c'"
              :format="() => `${row.available}/${row.planned}`"
            />
          </template>
        </el-table-column>
      </el-table>
      <div class="source-note">
        需求：不保障每天有 28 台四米二、3 台大包、9 台小包满勤，可动态调节。
      </div>
    </el-card>

    <!-- 不可出勤清单 -->
    <el-alert v-if="unavailableList.length" type="warning" :closable="false" class="mb">
      <template #title>
        有 {{ unavailableList.length }} 台车辆当日不可出勤，调度时会被排除：
        <el-tag
          v-for="v in unavailableList.slice(0, 8)"
          :key="v.id"
          :type="reasonTag(v)"
          size="small"
          effect="plain"
          class="mr mt-xs"
        >
          {{ v.plate_no }}（{{ reason(v) }}）
        </el-tag>
        <span v-if="unavailableList.length > 8" class="muted">
          等 {{ unavailableList.length }} 台
        </span>
      </template>
    </el-alert>

    <el-card shadow="never">
      <template #header>
        <span class="card-title">可出勤车辆明细（{{ available.length }}）</span>
      </template>
      <el-table v-loading="loading" :data="available" stripe max-height="520">
        <el-table-column prop="plate_no" label="车牌号" width="110">
          <template #default="{ row }">
            <span class="perm-code">{{ row.plate_no }}</span>
          </template>
        </el-table-column>
        <el-table-column label="车型" width="100">
          <template #default="{ row }">
            <el-tag :type="vehicleTypeCode(row.vehicle_type_code).type" size="small">
              {{ row.vehicle_type_name || vehicleTypeCode(row.vehicle_type_code).text }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="装载量 / 日趟次" width="150">
          <template #default="{ row }">
            <span class="perm-code">
              {{ typeByCode[row.vehicle_type_code]?.min_load }}–{{
                typeByCode[row.vehicle_type_code]?.max_load
              }}
              / {{ typeByCode[row.vehicle_type_code]?.trips_per_day }} 趟
            </span>
          </template>
        </el-table-column>
        <el-table-column label="地形能力" width="130">
          <template #default="{ row }">
            <el-tag :type="terrainCapability(row.terrain_capability).type" size="small" effect="plain">
              {{ terrainCapability(row.terrain_capability).text }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="可跑线路" min-width="120">
          <template #default="{ row }">
            <template v-if="row.route_scope">
              <el-tag
                v-for="r in row.route_scope.split(',')"
                :key="r"
                size="small"
                effect="plain"
                class="mr perm-code"
              >
                {{ r }}
              </el-tag>
            </template>
            <span v-else class="muted">不限制</span>
          </template>
        </el-table-column>
        <el-table-column label="司机" width="120">
          <template #default="{ row }">
            <span v-if="row.driver_name">{{ row.driver_name }}</span>
            <span v-else class="muted">未绑定</span>
          </template>
        </el-table-column>
        <el-table-column label="车辆状态" width="100">
          <template #default="{ row }">
            <el-tag :type="vehicleStatus(row.status).type" size="small" effect="plain">
              {{ vehicleStatus(row.status).text }}
            </el-tag>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<style scoped>
.mb {
  margin-bottom: 16px;
}

.card-title {
  font-weight: 600;
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

.stat-value.warn {
  color: #e6a23c;
}

.stat-note {
  font-size: 11px;
  color: #c0c4cc;
}

.source-note {
  margin-top: 10px;
  font-size: 11px;
  color: #c0c4cc;
}

.mt-xs {
  margin-top: 4px;
}
</style>
