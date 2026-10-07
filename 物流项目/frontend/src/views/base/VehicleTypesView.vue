<script setup>
/**
 * 车型能力配置（车辆类型及装载量、趟次规则）。
 *
 * ★ 本页是需求文档 一.3「现有条件」的配置入口，也是调度器的硬约束来源：
 *   四米二 630-800 日 2 趟（上午 1 + 下午 1）
 *   大包   300-420 日 2 趟（上午 1 + 下午 1）
 *   小包   1-300   日 4 趟（上午 2 + 下午 2）
 *
 * ★ 后端会校验「上午趟次 + 下午趟次 == 每日趟次」，不一致会返回 400 ——
 *   这条约束保证趟次规则不会自相矛盾。
 *
 * ★ planned_count 是「不保障满勤」的对比基线（28/3/9），
 *   实际排班按当天的可出勤车辆动态调节。
 */
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh, Edit } from '@element-plus/icons-vue'
import * as api from '@/api'
import { withError, tryAction } from '@/utils/error'
import { vehicleTypeCode } from '@/utils/enums'

const loading = ref(false)
const rows = ref([])

const dialogVisible = ref(false)
const submitting = ref(false)
const current = ref(null)
const form = ref({
  name: '',
  min_load: 0,
  max_load: 0,
  trips_per_day: 1,
  am_trips: 1,
  pm_trips: 0,
  planned_count: 0,
  remark: '',
})

/** 趟次一致性：实时提示，避免提交后才发现 */
const tripsConsistent = computed(
  () => Number(form.value.am_trips) + Number(form.value.pm_trips) === Number(form.value.trips_per_day),
)
const loadConsistent = computed(() => Number(form.value.min_load) <= Number(form.value.max_load))

async function load() {
  loading.value = true
  try {
    rows.value = (await withError(() => api.fetchVehicleTypes())) || []
  } finally {
    loading.value = false
  }
}

function openEdit(row) {
  current.value = row
  form.value = {
    name: row.name,
    min_load: row.min_load,
    max_load: row.max_load,
    trips_per_day: row.trips_per_day,
    am_trips: row.am_trips,
    pm_trips: row.pm_trips,
    planned_count: row.planned_count,
    remark: row.remark,
  }
  dialogVisible.value = true
}

async function submit() {
  if (!tripsConsistent.value) {
    ElMessage.warning('上午趟次 + 下午趟次 必须等于每日趟次')
    return
  }
  if (!loadConsistent.value) {
    ElMessage.warning('最低装载量不能大于最高装载量')
    return
  }

  submitting.value = true
  const { ok } = await tryAction(
    () => api.updateVehicleType(current.value.id, { ...form.value }),
    `${current.value.name} 的规则已更新`,
  )
  submitting.value = false
  if (!ok) return
  dialogVisible.value = false
  await load()
}

/** 计划保有量合计 */
const totalPlanned = computed(() =>
  rows.value.reduce((sum, r) => sum + (r.planned_count || 0), 0),
)
const totalActual = computed(() => rows.value.reduce((sum, r) => sum + (r.vehicle_count || 0), 0))
const totalTrips = computed(() =>
  rows.value.reduce((sum, r) => sum + (r.planned_count || 0) * (r.trips_per_day || 0), 0),
)

onMounted(load)
</script>

<template>
  <div class="page-container">
    <div class="page-header">
      <div>
        <h2 class="page-title">车型能力配置</h2>
        <p class="page-desc">
          装载量与趟次规则是调度器的<strong>硬约束</strong>：达到最低装载量才发车、
          不超最高装载量、趟次不超上限。写操作需要
          <code class="perm-code">vehicles:manage</code>。
        </p>
      </div>
      <el-button :icon="Refresh" @click="load">刷新</el-button>
    </div>

    <el-row :gutter="16" class="mb">
      <el-col :xs="24" :sm="8">
        <el-card shadow="never" class="stat">
          <div class="stat-label">计划保有量合计</div>
          <div class="stat-value">{{ totalPlanned }}<span class="unit">台</span></div>
          <div class="stat-note">四米二 28 + 大包 3 + 小包 9</div>
        </el-card>
      </el-col>
      <el-col :xs="24" :sm="8">
        <el-card shadow="never" class="stat">
          <div class="stat-label">实际建档车辆</div>
          <div class="stat-value">{{ totalActual }}<span class="unit">台</span></div>
          <div class="stat-note">来自车辆档案</div>
        </el-card>
      </el-col>
      <el-col :xs="24" :sm="8">
        <el-card shadow="never" class="stat">
          <div class="stat-label">理论日趟次上限</div>
          <div class="stat-value">{{ totalTrips }}<span class="unit">趟</span></div>
          <div class="stat-note">Σ(保有量 × 每日趟次)，实际动态调节</div>
        </el-card>
      </el-col>
    </el-row>

    <el-card shadow="never">
      <el-table v-loading="loading" :data="rows" stripe>
        <el-table-column label="车型" width="110">
          <template #default="{ row }">
            <el-tag :type="vehicleTypeCode(row.code).type" size="small">
              {{ row.name }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="车型码" width="90">
          <template #default="{ row }">
            <span class="perm-code">{{ row.code }}</span>
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
        <el-table-column label="趟次拆分" width="160">
          <template #default="{ row }">
            <span class="muted">上午 {{ row.am_trips }} 趟 + 下午 {{ row.pm_trips }} 趟</span>
          </template>
        </el-table-column>
        <el-table-column label="计划保有量" width="110" align="center">
          <template #default="{ row }">
            {{ row.planned_count }}
          </template>
        </el-table-column>
        <el-table-column label="实际车辆" width="100" align="center">
          <template #default="{ row }">
            <el-tag
              size="small"
              :type="row.vehicle_count === row.planned_count ? 'success' : 'warning'"
              effect="plain"
            >
              {{ row.vehicle_count }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="remark" label="说明" min-width="200" show-overflow-tooltip />
        <el-table-column label="操作" width="90" fixed="right">
          <template #default="{ row }">
            <el-button
              v-permission="'vehicles:manage'"
              size="small"
              type="primary"
              link
              :icon="Edit"
              @click="openEdit(row)"
            >
              编辑
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-alert type="info" :closable="false" class="mt">
      <template #title>
        「计划保有量」是<strong>不保障满勤</strong>的对比基线（需求：不保障每天 28/3/9 台满勤）。
        调度按当天可出勤车辆动态调节，本数值只用于计算使用率与达成率。
      </template>
    </el-alert>

    <el-dialog v-model="dialogVisible" :title="`编辑 ${current?.name} 的规则`" width="540px">
      <el-form label-width="110px">
        <el-form-item label="车型名称">
          <el-input v-model="form.name" />
        </el-form-item>
        <el-row :gutter="12">
          <el-col :span="12">
            <el-form-item label="最低装载量">
              <el-input-number v-model="form.min_load" :min="0" :max="9999" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="最高装载量">
              <el-input-number v-model="form.max_load" :min="0" :max="9999" style="width: 100%" />
            </el-form-item>
          </el-col>
        </el-row>

        <el-form-item v-if="!loadConsistent" label=" ">
          <el-alert type="error" :closable="false">
            <template #title>最低装载量不能大于最高装载量</template>
          </el-alert>
        </el-form-item>

        <el-form-item label="每日趟次">
          <el-input-number v-model="form.trips_per_day" :min="1" :max="10" />
        </el-form-item>
        <el-row :gutter="12">
          <el-col :span="12">
            <el-form-item label="上午趟次">
              <el-input-number v-model="form.am_trips" :min="0" :max="10" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="下午趟次">
              <el-input-number v-model="form.pm_trips" :min="0" :max="10" style="width: 100%" />
            </el-form-item>
          </el-col>
        </el-row>

        <el-form-item label=" ">
          <el-alert :type="tripsConsistent ? 'success' : 'error'" :closable="false">
            <template #title>
              上午 {{ form.am_trips }} + 下午 {{ form.pm_trips }} =
              {{ Number(form.am_trips) + Number(form.pm_trips) }}，
              每日趟次为 {{ form.trips_per_day }}
              {{ tripsConsistent ? '✓ 一致' : '✗ 不一致，无法保存' }}
            </template>
          </el-alert>
        </el-form-item>

        <el-form-item label="计划保有量">
          <el-input-number v-model="form.planned_count" :min="0" :max="999" />
        </el-form-item>
        <el-form-item label="说明">
          <el-input v-model="form.remark" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button
          type="primary"
          :loading="submitting"
          :disabled="!tripsConsistent || !loadConsistent"
          @click="submit"
        >
          保存
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
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

.stat-note {
  font-size: 11px;
  color: #c0c4cc;
}
</style>
