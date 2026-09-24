<script setup>
/**
 * 车辆档案。
 *
 * ★ 车辆的两个属性决定它能服务哪些门店：
 *   terrain_capability  车辆地形能力 → 必须覆盖门店的 terrain_type
 *   route_scope         可跑线路     → 门店必须属于这些线路（空 = 不限制）
 *
 * ★ 车辆类型（四米二/大包/小包）决定装载量区间与每日趟次，
 *   那部分规则在「车辆类型」页维护，这里只引用类型码。
 */
import { computed, onMounted, ref } from 'vue'
import { Plus, Refresh } from '@element-plus/icons-vue'
import * as api from '@/api'
import { useCrud } from '@/utils/crud'
import { withError } from '@/utils/error'
import {
  terrainCapability,
  vehicleStatus,
  vehicleTypeCode,
  TERRAIN_CAPABILITY_OPTIONS,
  VEHICLE_STATUS_OPTIONS,
} from '@/utils/enums'

const formRef = ref()
const vehicleTypes = ref([])
const drivers = ref([])

const {
  loading,
  rows,
  submitting,
  dialogVisible,
  form,
  isEditing,
  dialogTitle,
  load,
  openCreate,
  openEdit,
  submit,
  confirmRemove,
} = useCrud(
  {
    list: api.fetchVehicles,
    create: api.createVehicle,
    update: api.updateVehicle,
    remove: api.deleteVehicle,
  },
  {
    formRef,
    label: '车辆',
    blank: () => ({
      plate_no: '',
      vehicle_type_code: '4.2m',
      terrain_capability: 'all',
      route_scope: '',
      status: 'idle',
      driver_id: null,
      remark: '',
    }),
    toForm: (row) => ({
      // ★ plate_no 编辑时只读但校验必填，必须回填（详见 StoresView 的说明）
      plate_no: row.plate_no,
      vehicle_type_code: row.vehicle_type_code,
      terrain_capability: row.terrain_capability,
      route_scope: row.route_scope,
      status: row.status,
      driver_id: row.driver_id,
      remark: row.remark,
    }),
    nameOf: (row) => row.plate_no,
  },
)

const rules = {
  plate_no: [{ required: true, message: '请输入车牌号', trigger: 'blur' }],
  vehicle_type_code: [{ required: true, message: '请选择车辆类型', trigger: 'change' }],
}

/** 按车型统计，用于页头概览 */
const stats = computed(() => {
  const base = { '4.2m': 0, big: 0, small: 0 }
  for (const v of rows.value) {
    if (base[v.vehicle_type_code] !== undefined) base[v.vehicle_type_code] += 1
  }
  return base
})

/** 过滤：车型与状态 */
const filterType = ref('')
const filterStatus = ref('')
const filtered = computed(() =>
  rows.value
    .filter((v) => (filterType.value ? v.vehicle_type_code === filterType.value : true))
    .filter((v) => (filterStatus.value ? v.status === filterStatus.value : true)),
)

async function loadAll() {
  await load()
  vehicleTypes.value = (await withError(() => api.fetchVehicleTypes())) || []
  drivers.value = (await withError(() => api.fetchDrivers())) || []
}

onMounted(loadAll)
</script>

<template>
  <div class="page-container">
    <div class="page-header">
      <div>
        <h2 class="page-title">车辆档案</h2>
        <p class="page-desc">
          车辆的地形能力必须能覆盖门店地形，可跑线路必须包含门店所在线路，否则该车无法服务该门店。
          写操作需要 <code class="perm-code">vehicles:manage</code>。
        </p>
      </div>
      <div class="actions">
        <el-select v-model="filterType" placeholder="全部车型" clearable style="width: 130px">
          <el-option v-for="t in vehicleTypes" :key="t.code" :label="t.name" :value="t.code" />
        </el-select>
        <el-select v-model="filterStatus" placeholder="全部状态" clearable style="width: 130px">
          <el-option
            v-for="o in VEHICLE_STATUS_OPTIONS"
            :key="o.value"
            :label="o.label"
            :value="o.value"
          />
        </el-select>
        <el-button :icon="Refresh" @click="loadAll">刷新</el-button>
        <el-button
          v-permission="'vehicles:manage'"
          type="primary"
          :icon="Plus"
          @click="openCreate"
        >
          新建车辆
        </el-button>
      </div>
    </div>

    <el-row :gutter="16" class="mb">
      <el-col :xs="8" :sm="8">
        <el-card shadow="never" class="stat">
          <div class="stat-label">四米二</div>
          <div class="stat-value">{{ stats['4.2m'] }}<span class="unit">台</span></div>
        </el-card>
      </el-col>
      <el-col :xs="8" :sm="8">
        <el-card shadow="never" class="stat">
          <div class="stat-label">大包</div>
          <div class="stat-value">{{ stats.big }}<span class="unit">台</span></div>
        </el-card>
      </el-col>
      <el-col :xs="8" :sm="8">
        <el-card shadow="never" class="stat">
          <div class="stat-label">小包</div>
          <div class="stat-value">{{ stats.small }}<span class="unit">台</span></div>
        </el-card>
      </el-col>
    </el-row>

    <el-card shadow="never">
      <el-table v-loading="loading" :data="filtered" stripe>
        <el-table-column prop="plate_no" label="车牌号" width="120">
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
        <el-table-column label="地形能力" width="130">
          <template #default="{ row }">
            <el-tag
              :type="terrainCapability(row.terrain_capability).type"
              size="small"
              effect="plain"
            >
              {{ terrainCapability(row.terrain_capability).text }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="可跑线路" min-width="140">
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
        <el-table-column label="绑定司机" width="110">
          <template #default="{ row }">
            <span v-if="row.driver_name">{{ row.driver_name }}</span>
            <span v-else class="muted">未绑定</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="vehicleStatus(row.status).type" size="small">
              {{ vehicleStatus(row.status).text }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="remark" label="备注" min-width="120" show-overflow-tooltip />
        <el-table-column label="操作" width="120" fixed="right">
          <template #default="{ row }">
            <el-button
              v-permission="'vehicles:manage'"
              size="small"
              type="primary"
              link
              @click="openEdit(row)"
            >
              编辑
            </el-button>
            <el-button
              v-permission="'vehicles:manage'"
              size="small"
              type="danger"
              link
              @click="confirmRemove(row)"
            >
              删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!loading && !filtered.length" description="没有匹配的车辆" />
    </el-card>

    <el-dialog v-model="dialogVisible" :title="dialogTitle" width="580px">
      <el-form ref="formRef" :model="form" :rules="rules" label-width="100px">
        <el-form-item label="车牌号" prop="plate_no">
          <el-input v-model="form.plate_no" :disabled="isEditing" placeholder="例如 沪A1029" />
        </el-form-item>
        <el-form-item label="车辆类型" prop="vehicle_type_code">
          <el-select v-model="form.vehicle_type_code" style="width: 100%">
            <el-option
              v-for="t in vehicleTypes"
              :key="t.code"
              :label="`${t.name}（装载 ${t.min_load}-${t.max_load}，日 ${t.trips_per_day} 趟）`"
              :value="t.code"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="地形能力">
          <el-select v-model="form.terrain_capability" style="width: 100%">
            <el-option
              v-for="o in TERRAIN_CAPABILITY_OPTIONS"
              :key="o.value"
              :label="o.label"
              :value="o.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="可跑线路">
          <el-input
            v-model="form.route_scope"
            placeholder="逗号分隔的线路编码，留空表示不限制"
          />
        </el-form-item>
        <el-form-item label="绑定司机">
          <el-select
            v-model="form.driver_id"
            clearable
            filterable
            placeholder="不绑定"
            style="width: 100%"
          >
            <el-option
              v-for="d in drivers"
              :key="d.id"
              :label="`${d.code} ${d.name}`"
              :value="d.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="form.status" style="width: 100%">
            <el-option
              v-for="o in VEHICLE_STATUS_OPTIONS"
              :key="o.value"
              :label="o.label"
              :value="o.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.remark" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submit()">保存</el-button>
      </template>
    </el-dialog>
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

.unit {
  font-size: 12px;
  font-weight: 400;
  color: #909399;
  margin-left: 3px;
}
</style>
