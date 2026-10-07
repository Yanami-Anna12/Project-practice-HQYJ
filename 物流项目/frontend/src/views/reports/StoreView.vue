<script setup>
/**
 * 门店配送达成与线路覆盖（需求文档 二.5）。
 *
 * ★ 达成率 = 实际配送量 ÷ 当日货量。分母来自「门店配送需求」，
 *   所以只有在货量已生成、且调度已跑过的日期才有完整数据。
 *
 * ★ 交界门店单列出来看：它们挂在多条线路上，
 *   需求文档专门提到「交界门店归属策略」，这里可以验证归属效果是否合理
 *   （不应该出现某个交界门店完全没被配送）。
 */
import { computed, onMounted, ref } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import * as api from '@/api'
import { withError } from '@/utils/error'
import EChart from '@/components/EChart.vue'
import { terrainType, timeWindow } from '@/utils/enums'
import { useReportDate } from '@/utils/reportDate'

const { scheduleDate, dates, loadDates } = useReportDate()

const loading = ref(false)
const data = ref(null)
const onlyUnmet = ref(false)

async function load() {
  loading.value = true
  try {
    data.value = await withError(() => api.fetchStoreReport(scheduleDate.value || undefined))
  } finally {
    loading.value = false
  }
}

const stores = computed(() => data.value?.stores || [])
const routes = computed(() => data.value?.routes || [])

const shownStores = computed(() =>
  onlyUnmet.value ? stores.value.filter((s) => s.achievement_rate < 99.99) : stores.value,
)

const intersections = computed(() => stores.value.filter((s) => s.is_intersection))

/** 线路覆盖率柱状图 */
const routeOption = computed(() => {
  const r = routes.value
  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    legend: { data: ['门店数', '已覆盖'] },
    grid: { left: 50, right: 20, top: 40, bottom: 40 },
    xAxis: {
      type: 'category',
      data: r.map((x) => x.route_code),
      axisLabel: { rotate: 0 },
    },
    yAxis: { type: 'value', name: '个' },
    series: [
      { name: '门店数', type: 'bar', data: r.map((x) => x.store_count), itemStyle: { color: '#c0c4cc' } },
      {
        name: '已覆盖',
        type: 'bar',
        data: r.map((x) => x.covered_count),
        itemStyle: { color: '#67c23a' },
        label: { show: true, position: 'top' },
      },
    ],
  }
})

/** 门店达成率分布 */
const storeDistOption = computed(() => {
  const s = stores.value
  const buckets = [
    { label: '100%', count: s.filter((x) => x.achievement_rate >= 99.99).length },
    { label: '80–99%', count: s.filter((x) => x.achievement_rate >= 80 && x.achievement_rate < 99.99).length },
    { label: '50–79%', count: s.filter((x) => x.achievement_rate >= 50 && x.achievement_rate < 80).length },
    { label: '< 50%', count: s.filter((x) => x.achievement_rate < 50).length },
  ]
  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    grid: { left: 50, right: 20, top: 30, bottom: 30 },
    xAxis: { type: 'category', data: buckets.map((b) => b.label) },
    yAxis: { type: 'value', name: '门店数' },
    series: [
      {
        type: 'bar',
        data: buckets.map((b) => b.count),
        itemStyle: { color: (p) => ['#67c23a', '#95d475', '#e6a23c', '#f56c6c'][p.dataIndex] },
        label: { show: true, position: 'top' },
        barMaxWidth: 70,
      },
    ],
  }
})

onMounted(async () => {
  await loadDates()
  await load()
})
</script>

<template>
  <div class="page-container">
    <div class="page-header">
      <div>
        <h2 class="page-title">门店配送达成</h2>
        <p class="page-desc">
          达成率 = 实际配送量 ÷ 当日货量。<strong>交界门店</strong>单独列出，
          用于验证多线路门店的归属策略是否合理。
        </p>
      </div>
      <div class="actions">
        <el-select
          v-model="scheduleDate"
          placeholder="全部日期"
          clearable
          style="width: 160px"
          @change="load"
        >
          <el-option v-for="d in dates" :key="d" :label="d" :value="d" />
        </el-select>
        <el-checkbox v-model="onlyUnmet" label="只看未完全满足" />
        <el-button :icon="Refresh" @click="load">刷新</el-button>
      </div>
    </div>

    <el-row v-if="data" :gutter="16" class="mb">
      <el-col :xs="12" :sm="6">
        <el-card shadow="never" class="stat">
          <div class="stat-label">有货量门店</div>
          <div class="stat-value">{{ data.store_count }}</div>
        </el-card>
      </el-col>
      <el-col :xs="12" :sm="6">
        <el-card shadow="never" class="stat">
          <div class="stat-label">完全满足</div>
          <div class="stat-value ok">{{ data.fully_served }}</div>
        </el-card>
      </el-col>
      <el-col :xs="12" :sm="6">
        <el-card shadow="never" class="stat">
          <div class="stat-label">门店达成率</div>
          <div class="stat-value" :class="data.achievement_rate >= 95 ? 'ok' : 'warn'">
            {{ data.achievement_rate }}%
          </div>
        </el-card>
      </el-col>
      <el-col :xs="12" :sm="6">
        <el-card shadow="never" class="stat">
          <div class="stat-label">交界门店</div>
          <div class="stat-value">{{ data.intersection_count }}</div>
          <div class="stat-note">挂多条线路</div>
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="16" class="mb">
      <el-col :xs="24" :lg="14">
        <el-card v-loading="loading" shadow="never" class="h-full">
          <template #header>
            <span class="card-title">线路覆盖（门店数 vs 已覆盖）</span>
          </template>
          <EChart :option="routeOption" height="290px" />
        </el-card>
      </el-col>
      <el-col :xs="24" :lg="10">
        <el-card v-loading="loading" shadow="never" class="h-full">
          <template #header>
            <span class="card-title">门店达成率分布</span>
          </template>
          <EChart :option="storeDistOption" height="290px" />
        </el-card>
      </el-col>
    </el-row>

    <!-- 交界门店 -->
    <el-card v-if="intersections.length" shadow="never" class="mb">
      <template #header>
        <span class="card-title">
          交界门店（{{ intersections.length }} 个）—— 归属策略验证
        </span>
      </template>
      <el-table :data="intersections" size="small" stripe>
        <el-table-column prop="store_code" label="门店" width="90">
          <template #default="{ row }">
            <span class="perm-code">{{ row.store_code }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="store_name" label="门店名称" width="140" />
        <el-table-column label="所属线路" min-width="140">
          <template #default="{ row }">
            <el-tag
              v-for="c in row.route_codes"
              :key="c"
              size="small"
              effect="plain"
              class="mr perm-code"
            >
              {{ c }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="地形 / 时段" width="150">
          <template #default="{ row }">
            <el-tag :type="terrainType(row.terrain_type).type" size="small">
              {{ terrainType(row.terrain_type).text }}
            </el-tag>
            <el-tag :type="timeWindow(row.delivery_window).type" size="small" effect="plain" class="ml">
              {{ timeWindow(row.delivery_window).text }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="货量" width="90" align="right">
          <template #default="{ row }">{{ row.demand ? row.demand.toFixed(0) : '—' }}</template>
        </el-table-column>
        <el-table-column label="配送量" width="90" align="right">
          <template #default="{ row }">{{ row.delivered.toFixed(0) }}</template>
        </el-table-column>
        <el-table-column label="趟次" width="80" align="center">
          <template #default="{ row }">{{ row.trip_count }}</template>
        </el-table-column>
        <el-table-column label="达成率" min-width="180">
          <template #default="{ row }">
            <el-progress
              :percentage="Math.min(100, row.achievement_rate)"
              :stroke-width="12"
              :color="row.achievement_rate >= 99.99 ? '#67c23a' : '#e6a23c'"
              :format="() => `${row.achievement_rate.toFixed(1)}%`"
            />
          </template>
        </el-table-column>
      </el-table>
      <div class="note">
        交界门店被多条线路覆盖，需要按优先级决定归属。这里逐个核对是否都被实际配送到了。
      </div>
    </el-card>

    <!-- 线路明细 -->
    <el-card shadow="never" class="mb">
      <template #header>
        <span class="card-title">线路覆盖明细</span>
      </template>
      <el-table :data="routes" stripe>
        <el-table-column prop="route_code" label="线路" width="90">
          <template #default="{ row }">
            <span class="perm-code">{{ row.route_code }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="route_name" label="线路名称" width="130" />
        <el-table-column prop="store_count" label="门店数" width="90" align="center" />
        <el-table-column prop="covered_count" label="已覆盖" width="90" align="center">
          <template #default="{ row }">
            <el-tag
              size="small"
              :type="row.covered_count === row.store_count ? 'success' : 'warning'"
              effect="plain"
            >
              {{ row.covered_count }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="覆盖率" min-width="200">
          <template #default="{ row }">
            <el-progress
              :percentage="row.coverage_rate"
              :stroke-width="14"
              :color="row.coverage_rate >= 99.99 ? '#67c23a' : '#e6a23c'"
              :format="() => `${row.coverage_rate.toFixed(1)}%`"
            />
          </template>
        </el-table-column>
        <el-table-column label="配送量" width="120" align="right">
          <template #default="{ row }">{{ row.total_delivered.toFixed(0) }}</template>
        </el-table-column>
        <el-table-column label="禁限行" width="90" align="center">
          <template #default="{ row }">
            <el-tag :type="row.is_restricted ? 'danger' : 'success'" size="small" effect="plain">
              {{ row.is_restricted ? '受限' : '正常' }}
            </el-tag>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 门店明细 -->
    <el-card shadow="never">
      <template #header>
        <span class="card-title">
          门店配送明细（{{ shownStores.length }} / {{ stores.length }}）
        </span>
      </template>
      <el-table :data="shownStores" stripe max-height="460" size="small">
        <el-table-column prop="store_code" label="门店" width="80" fixed>
          <template #default="{ row }">
            <span class="perm-code">{{ row.store_code }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="store_name" label="名称" width="130" fixed />
        <el-table-column label="地形" width="80">
          <template #default="{ row }">
            <el-tag :type="terrainType(row.terrain_type).type" size="small">
              {{ terrainType(row.terrain_type).text }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="时段" width="70">
          <template #default="{ row }">
            {{ timeWindow(row.delivery_window).text }}
          </template>
        </el-table-column>
        <el-table-column label="货量" width="90" align="right">
          <template #default="{ row }">
            {{ row.demand ? row.demand.toFixed(0) : '—' }}
          </template>
        </el-table-column>
        <el-table-column label="配送量" width="90" align="right">
          <template #default="{ row }">{{ row.delivered.toFixed(0) }}</template>
        </el-table-column>
        <el-table-column label="趟次" width="70" align="center">
          <template #default="{ row }">{{ row.trip_count }}</template>
        </el-table-column>
        <el-table-column label="达成率" width="110" align="right">
          <template #default="{ row }">
            <span :class="{ unmet: row.achievement_rate < 99.99 }">
              {{ row.achievement_rate.toFixed(1) }}%
            </span>
          </template>
        </el-table-column>
        <el-table-column label="线路" min-width="120">
          <template #default="{ row }">
            <el-tag
              v-for="c in row.route_codes"
              :key="c"
              size="small"
              effect="plain"
              class="mr perm-code"
            >
              {{ c }}
            </el-tag>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!shownStores.length" description="没有匹配的门店" />
    </el-card>
  </div>
</template>

<style scoped>
.actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  align-items: center;
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

.note {
  margin-top: 10px;
  font-size: 11px;
  color: #c0c4cc;
}

.ml {
  margin-left: 4px;
}

.unmet {
  color: #e6a23c;
  font-weight: 600;
}
</style>
