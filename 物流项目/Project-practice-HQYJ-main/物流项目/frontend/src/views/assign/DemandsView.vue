<script setup>
/**
 * 门店配送需求（当日货量）—— 调度的输入。
 *
 * ★ 货量在真实场景来自 OMS 的「订单/货量接口」。本项目按确认的方案
 *   支持系统内手工维护，并提供「生成演示货量」按钮（按门店编码哈希取量，
 *   同一天反复点击结果一致，不会让数据漂移）。
 *
 * ★ 这里能看到一个关键的调度约束：单店货量常常超过单车最大装载量
 *   （四米二上限 800），所以一个门店的货量需要拆分到多个趟次配送。
 *   页面上的「至少需趟数」列就是按四米二上限估算的下限。
 */
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh, MagicStick, Edit, Delete } from '@element-plus/icons-vue'
import * as api from '@/api'
import { withError, tryAction } from '@/utils/error'
import { terrainType, timeWindow } from '@/utils/enums'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const canManage = computed(() => auth.has('stores:manage'))

/** 默认看明天（当天数据留给看板演示） */
const scheduleDate = ref(toISO(new Date(Date.now() + 86400000)))

function toISO(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

const loading = ref(false)
const rows = ref([])
const summary = ref(null)
const generating = ref(false)

async function load() {
  loading.value = true
  try {
    const [list, sum] = await Promise.all([
      withError(() => api.fetchDemands(scheduleDate.value)),
      withError(() => api.fetchDemandSummary(scheduleDate.value)),
    ])
    rows.value = list || []
    summary.value = sum
  } finally {
    loading.value = false
  }
}

async function generate() {
  generating.value = true
  const { ok, result } = await tryAction(
    () => api.generateDemands({ schedule_date: scheduleDate.value, overwrite: false }),
    null,
  )
  generating.value = false
  if (!ok) return
  ElMessage.success(
    `已生成：新增 ${result.created}、更新 ${result.updated}、跳过 ${result.skipped}（共 ${result.stores} 个门店）`,
  )
  await load()
}

/* ---------------- 编辑单店货量 ---------------- */
const dialogVisible = ref(false)
const submitting = ref(false)
const current = ref(null)
const quantity = ref(0)
const remark = ref('')

function openEdit(row) {
  current.value = row
  quantity.value = Number(row.quantity)
  remark.value = row.remark || ''
  dialogVisible.value = true
}

async function submit() {
  if (quantity.value < 0) {
    ElMessage.warning('货量不能为负')
    return
  }
  submitting.value = true
  const { ok } = await tryAction(
    () =>
      api.upsertDemand({
        schedule_date: scheduleDate.value,
        store_id: current.value.store_id,
        quantity: Number(quantity.value),
        remark: remark.value,
      }),
    `已更新 ${current.value.store_code} 的货量`,
  )
  submitting.value = false
  if (!ok) return
  dialogVisible.value = false
  await load()
}

async function remove(row) {
  const { ok } = await tryAction(() => api.deleteDemand(row.id))
  if (ok) await load()
}

/* ---------------- 派生统计 ---------------- */
const amRows = computed(() => rows.value.filter((r) => r.delivery_window === 'AM'))
const pmRows = computed(() => rows.value.filter((r) => r.delivery_window === 'PM'))

/** 需要拆单的门店：货量超过单车最大装载量（四米二 800） */
const needSplit = computed(() => rows.value.filter((r) => Number(r.quantity) > 800))

/** 按四米二上限估算的趟次下限 */
const estimatedTrips = computed(() =>
  rows.value.reduce((sum, r) => sum + Math.ceil(Number(r.quantity) / 800), 0),
)

/** 最多货量的门店 */
const topStores = computed(() =>
  [...rows.value].sort((a, b) => Number(b.quantity) - Number(a.quantity)).slice(0, 5),
)

onMounted(load)
</script>

<template>
  <div class="page-container">
    <div class="page-header">
      <div>
        <h2 class="page-title">门店配送需求</h2>
        <p class="page-desc">
          当日各门店的配送货量，是调度的输入。真实场景由 OMS 的「订单/货量接口」推送，
          本版支持系统内手工维护。写操作需要 <code class="perm-code">stores:manage</code>。
        </p>
      </div>
      <div class="actions">
        <el-date-picker
          v-model="scheduleDate"
          type="date"
          value-format="YYYY-MM-DD"
          placeholder="调度日期"
          style="width: 160px"
          @change="load"
        />
        <el-button :icon="Refresh" @click="load">刷新</el-button>
        <el-button
          v-if="canManage"
          type="primary"
          :icon="MagicStick"
          :loading="generating"
          @click="generate"
        >
          生成演示货量
        </el-button>
      </div>
    </div>

    <!-- 概览 -->
    <el-row :gutter="16" class="mb">
      <el-col :xs="12" :sm="6">
        <el-card shadow="never" class="stat">
          <div class="stat-label">门店数</div>
          <div class="stat-value">{{ rows.length }}</div>
        </el-card>
      </el-col>
      <el-col :xs="12" :sm="6">
        <el-card shadow="never" class="stat">
          <div class="stat-label">总货量</div>
          <div class="stat-value">{{ (summary?.total_quantity || 0).toFixed(0) }}</div>
        </el-card>
      </el-col>
      <el-col :xs="12" :sm="6">
        <el-card shadow="never" class="stat">
          <div class="stat-label">上午 / 下午门店</div>
          <div class="stat-value small">
            <span class="am">{{ amRows.length }}</span> /
            <span class="pm">{{ pmRows.length }}</span>
          </div>
        </el-card>
      </el-col>
      <el-col :xs="12" :sm="6">
        <el-card shadow="never" class="stat">
          <div class="stat-label">按四米二估算最少趟次</div>
          <div class="stat-value">{{ estimatedTrips }}</div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 需要拆单的门店提示 -->
    <el-alert
      v-if="needSplit.length"
      type="warning"
      :closable="false"
      class="mb"
    >
      <template #title>
        <strong>{{ needSplit.length }}</strong> 个门店的货量超过单车最大装载量（四米二 800），
        这些门店的货量会被<strong>拆分到多个趟次</strong>配送。
        单店最大：
        {{ topStores[0]?.store_code }} {{ topStores[0]?.store_name }}
        = {{ Number(topStores[0]?.quantity).toFixed(0) }}
        （需至少 {{ Math.ceil(Number(topStores[0]?.quantity) / 800) }} 趟）
      </template>
    </el-alert>

    <el-card shadow="never">
      <el-table v-loading="loading" :data="rows" stripe>
        <el-table-column prop="store_code" label="门店" width="90">
          <template #default="{ row }">
            <span class="perm-code">{{ row.store_code }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="store_name" label="门店名称" min-width="140" />
        <el-table-column label="地形" width="90">
          <template #default="{ row }">
            <el-tag :type="terrainType(row.terrain_type).type" size="small">
              {{ terrainType(row.terrain_type).text }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="时段" width="90">
          <template #default="{ row }">
            <el-tag :type="timeWindow(row.delivery_window).type" size="small" effect="plain">
              {{ timeWindow(row.delivery_window).text }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="所属线路" min-width="120">
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
            <span v-if="!row.route_codes.length" class="muted">未映射</span>
          </template>
        </el-table-column>
        <el-table-column label="货量" width="110" align="right">
          <template #default="{ row }">
            <span class="qty">{{ Number(row.quantity).toFixed(0) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="至少需趟数" width="120" align="center">
          <template #default="{ row }">
            <el-tag
              size="small"
              :type="row.min_trips_4_2m > 1 ? 'warning' : 'info'"
              effect="plain"
            >
              {{ row.min_trips_4_2m }} 趟
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="remark" label="备注" min-width="140" show-overflow-tooltip />
        <el-table-column v-if="canManage" label="操作" width="130" fixed="right">
          <template #default="{ row }">
            <el-button size="small" type="primary" link :icon="Edit" @click="openEdit(row)">
              改货量
            </el-button>
            <el-button size="small" type="danger" link :icon="Delete" @click="remove(row)">
              删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!loading && !rows.length" description="该日期还没有货量数据">
        <el-button v-if="canManage" type="primary" :icon="MagicStick" @click="generate">
          生成演示货量
        </el-button>
      </el-empty>
    </el-card>

    <el-alert type="info" :closable="false" class="mt">
      <template #title>
        货量准备好后，到「智能调度 Agent → 调度任务」创建调度任务。
        总货量 {{ (summary?.total_quantity || 0).toFixed(0) }}，
        按四米二上限 800 估算至少需要 {{ estimatedTrips }} 趟；
        系统有 40 台车（日趟次上限合计 76 趟），运力充足。
      </template>
    </el-alert>

    <el-dialog v-model="dialogVisible" :title="`修改 ${current?.store_code} 的货量`" width="460px">
      <el-form label-width="90px">
        <el-form-item label="门店">
          <el-input :model-value="`${current?.store_code} ${current?.store_name}`" disabled />
        </el-form-item>
        <el-form-item label="配送时段">
          <el-input :model-value="timeWindow(current?.delivery_window).text" disabled />
        </el-form-item>
        <el-form-item label="货量">
          <el-input-number v-model="quantity" :min="0" :max="999999" :step="10" style="width: 100%" />
          <div class="field-note">
            超过 800 时会被拆分到多个趟次配送
          </div>
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="remark" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submit">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  align-items: center;
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
  font-size: 20px;
}

.am {
  color: #409eff;
}

.pm {
  color: #e6a23c;
}

.qty {
  font-family: 'Cascadia Mono', Consolas, monospace;
  font-weight: 600;
}

.field-note {
  font-size: 12px;
  color: #909399;
  line-height: 1.6;
}
</style>
