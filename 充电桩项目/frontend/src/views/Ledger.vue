<template>
  <div class="page">
    <!-- ---------------- 页头 ---------------- -->
    <div class="page-header">
      <div>
        <h2 class="page-title"><DatabaseOutlined /> 台账管理</h2>
        <div class="page-subtitle">
          站台台账 / 充电桩台账 · 复杂模糊查询 · 信息导出（PDF 3.7）　·　数据权限：{{ store.dataScope }}
        </div>
      </div>
      <a-space>
        <a-button :loading="loading" @click="loadList">
          <template #icon><ReloadOutlined /></template>
          刷新
        </a-button>
        <a-button :loading="syncing" @click="syncLedger">
          <template #icon><SyncOutlined /></template>
          同步台账
        </a-button>
        <a-button type="primary" :loading="exporting" @click="exportLedger">
          <template #icon><ExportOutlined /></template>
          信息导出 Excel
        </a-button>
      </a-space>
    </div>

    <!-- ---------------- 统计概览 ---------------- -->
    <a-row :gutter="[14, 14]">
      <a-col :xs="12" :md="8">
        <StatCard
          label="站台台账"
          :value="stationTabTotal"
          suffix="个站点"
          tone="primary"
          :icon="EnvironmentOutlined"
          :hint="`当前 tab 记录 ${activeKey === 'station' ? page.total : stationTabTotal} 条`"
        />
      </a-col>
      <a-col :xs="12" :md="8">
        <StatCard
          label="充电桩台账"
          :value="pileTabTotal"
          suffix="台充电桩"
          tone="primary"
          :icon="ThunderboltOutlined"
          :hint="`累计充电枪 ${gunTotal} 把（PDF 3.10 二期扩展）`"
        />
      </a-col>
      <a-col :xs="12" :md="8">
        <StatCard
          label="灭火器 / 摄像头"
          :value="stationTabTotal"
          suffix="个站点已维护"
          :icon="SafetyOutlined"
          hint="灭火器支持「无」选项，摄像头含球机 / 枪机与监控密码"
        />
      </a-col>
    </a-row>

    <!-- ---------------- 查询 + 台账表格 ---------------- -->
    <a-card size="small" :bordered="false" style="margin-top: 14px">
      <a-tabs v-model:activeKey="activeKey" size="small" @change="onTabChange">
        <a-tab-pane key="station" tab="站台台账" />
        <a-tab-pane key="pile" tab="充电桩台账" />
      </a-tabs>

      <!-- 复杂模糊查询（PDF 3.7） -->
      <div class="filter-bar" style="box-shadow: none; padding: 0 0 14px">
        <a-form layout="inline" :model="query">
          <a-form-item label="所属项目">
            <a-select
              v-model:value="query.project_id"
              placeholder="全部项目"
              allow-clear
              show-search
              option-filter-prop="label"
              style="width: 180px"
              :options="projectOptions"
              @change="onProjectChange"
            />
          </a-form-item>
          <a-form-item label="所属站点">
            <a-select
              v-model:value="query.station_id"
              placeholder="全部站点"
              allow-clear
              show-search
              option-filter-prop="label"
              style="width: 210px"
              :options="stationOptions"
              :loading="stationLoading"
              @change="search"
            />
          </a-form-item>
          <a-form-item label="模糊查询">
            <a-input
              v-model:value="query.keyword"
              placeholder="资产编码 / 名称 / 站点"
              allow-clear
              style="width: 220px"
              @press-enter="search"
            >
              <template #prefix><SearchOutlined /></template>
            </a-input>
          </a-form-item>
          <a-form-item label="状态">
            <a-select
              v-model:value="query.status"
              placeholder="全部状态"
              allow-clear
              style="width: 120px"
              @change="search"
            >
              <a-select-option value="正常">正常</a-select-option>
              <a-select-option value="停用">停用</a-select-option>
              <a-select-option value="在线">在线</a-select-option>
              <a-select-option value="离线">离线</a-select-option>
            </a-select>
          </a-form-item>
          <a-form-item>
            <a-space>
              <a-button type="primary" @click="search">
                <template #icon><SearchOutlined /></template>
                查询
              </a-button>
              <a-button @click="resetQuery">
                <template #icon><ReloadOutlined /></template>
                重置
              </a-button>
            </a-space>
          </a-form-item>
        </a-form>
      </div>

      <!-- 站点二期扩展：导航与地图分享 / 灭火器与摄像头维护 -->
      <a-space style="margin-bottom: 12px" wrap>
        <a-tooltip :title="currentStationId ? '' : '请先在上方筛选「所属站点」'">
          <a-button :disabled="!currentStationId" @click="openExtensions">
            <template #icon><EditOutlined /></template>
            灭火器 / 摄像头维护
          </a-button>
        </a-tooltip>
        <a-button :disabled="!currentStationId" @click="openNavigation">
          <template #icon><EnvironmentOutlined /></template>
          站点导航与地图分享
        </a-button>
        <span class="text-muted" style="font-size: 12px">
          二期扩展（PDF 3.10）：灭火器含「无」选项，选「无」自动隐藏规格与生产日期；摄像头维护球机 / 枪机数量与监控密码。
        </span>
      </a-space>

      <a-table
        :columns="columns"
        :data-source="list"
        :loading="loading"
        :pagination="false"
        row-key="id"
        size="small"
        :scroll="{ x: 1180 }"
        :custom-row="customRow"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.dataIndex === 'ledger_type'">
            <a-tag :color="record.ledger_type === 'station' ? 'blue' : 'green'">
              {{ ledgerTypeText(record.ledger_type) }}
            </a-tag>
          </template>

          <template v-else-if="column.dataIndex === 'asset_code'">
            <span class="mono">{{ record.asset_code }}</span>
          </template>

          <template v-else-if="column.dataIndex === 'status'">
            <a-tag :color="statusColor(record.status)">{{ record.status || '-' }}</a-tag>
          </template>

          <template v-else-if="column.dataIndex === 'gun_count'">
            <a-tag v-if="record.gun_count !== undefined && record.gun_count !== null" color="blue">
              {{ record.gun_count }} 把
            </a-tag>
            <span v-else class="text-muted">-</span>
          </template>

          <template v-else-if="column.dataIndex === 'extinguisher'">
            <a-tag v-if="record.extinguisher_type" :color="record.extinguisher_type === '无' ? 'default' : 'orange'">
              {{ record.extinguisher_type }}
              <template v-if="record.extinguisher_type !== '无'">
                <span v-if="record.extinguisher_spec">　{{ record.extinguisher_spec }}</span>
                <span v-if="record.extinguisher_produced_at">
                  　{{ formatDate(record.extinguisher_produced_at) }}
                </span>
              </template>
            </a-tag>
            <span v-else class="text-muted">-</span>
          </template>

          <template v-else-if="column.dataIndex === 'action'">
            <a-space size="small">
              <a class="clickable" @click.stop="openDetail(record)">详情</a>
              <a
                v-if="record.ledger_type === 'station'"
                class="clickable"
                @click.stop="openExtensions(record)"
              >
                二期字段
              </a>
              <a
                v-if="record.ledger_type === 'station'"
                class="clickable"
                @click.stop="openNavigation(record)"
              >
                <EnvironmentOutlined /> 导航
              </a>
            </a-space>
          </template>

          <template v-else>
            {{ formatCell(record[column.dataIndex]) }}
          </template>
        </template>
      </a-table>

      <div class="table-pager">
        <a-pagination
          v-model:current="page.page"
          v-model:page-size="page.page_size"
          :total="page.total"
          :page-size-options="['10', '20', '50', '100']"
          size="small"
          show-size-changer
          show-total
          :show-total="(t) => `共 ${t} 条台账记录`"
          @change="loadList"
          @showSizeChange="onSizeChange"
        />
      </div>
    </a-card>

    <!-- ---------------- 台账详情抽屉 ---------------- -->
    <a-drawer v-model:open="detailOpen" :title="detailTitle" width="520px">
      <a-descriptions bordered size="small" :column="1">
        <a-descriptions-item label="台账类型">
          {{ ledgerTypeText(detailRecord.ledger_type) }}
        </a-descriptions-item>
        <a-descriptions-item label="资产编码">
          <span class="mono">{{ detailRecord.asset_code || '-' }}</span>
        </a-descriptions-item>
        <a-descriptions-item label="资产名称">{{ detailRecord.asset_name || '-' }}</a-descriptions-item>
        <a-descriptions-item v-if="detailRecord.ledger_type === 'pile'" label="所属站点">
          {{ detailRecord.station_name || '-' }}
        </a-descriptions-item>
        <a-descriptions-item v-if="detailRecord.ledger_type === 'pile'" label="所属项目">
          {{ detailRecord.project_name || '-' }}
        </a-descriptions-item>
        <a-descriptions-item label="状态">
          <a-tag :color="statusColor(detailRecord.status)">{{ detailRecord.status || '-' }}</a-tag>
        </a-descriptions-item>
        <a-descriptions-item
          v-for="key in detailAttrKeys"
          :key="key"
          :label="ATTR_LABELS[key] || key"
        >
          {{ formatCell(detailRecord[key]) }}
        </a-descriptions-item>
        <a-descriptions-item label="更新时间">
          {{ formatTime(detailRecord.updated_at) }}
        </a-descriptions-item>
      </a-descriptions>

      <template #extra>
        <a-button
          v-if="detailRecord.ledger_type === 'station'"
          size="small"
          @click="openExtensions(detailRecord)"
        >
          <template #icon><EditOutlined /></template>
          维护二期字段
        </a-button>
      </template>
    </a-drawer>

    <!-- ---------------- 二期扩展编辑：灭火器（含「无」）+ 摄像头 ---------------- -->
    <a-modal
      v-model:open="extOpen"
      title="站点二期扩展字段（PDF 3.10）"
      width="680px"
      :confirm-loading="extSubmitting"
      :mask-closable="false"
      @ok="submitExtensions"
    >
      <a-form layout="vertical" :model="extForm">
        <a-form-item label="所属站点" required>
          <a-select
            v-model:value="extForm.station_id"
            placeholder="请选择站点"
            show-search
            option-filter-prop="label"
            :options="stationOptions"
            :loading="stationLoading"
          />
        </a-form-item>

        <a-divider orientation="left" style="margin: 8px 0 14px">灭火器信息</a-divider>
        <a-row :gutter="12">
          <a-col :xs="24" :md="8">
            <a-form-item label="灭火器类型">
              <a-select
                v-model:value="extForm.extinguisher_type"
                placeholder="请选择类型"
                show-search
                option-filter-prop="label"
                @change="onExtinguisherChange"
              >
                <a-select-option v-for="t in extinguisherTypes" :key="t" :value="t">
                  {{ t }}
                </a-select-option>
              </a-select>
            </a-form-item>
          </a-col>

          <!-- 选择「无」时隐藏规格与生产日期（动态表单） -->
          <template v-if="extForm.extinguisher_type !== '无'">
            <a-col :xs="24" :md="8">
              <a-form-item label="单瓶规格">
                <a-input
                  v-model:value="extForm.extinguisher_spec"
                  placeholder="如：4kg 干粉灭火器"
                />
              </a-form-item>
            </a-col>
            <a-col :xs="24" :md="8">
              <a-form-item label="生产日期">
                <a-date-picker
                  v-model:value="extForm.extinguisher_produced_at"
                  value-format="YYYY-MM-DD 00:00:00"
                  placeholder="请选择生产日期"
                  style="width: 100%"
                />
              </a-form-item>
            </a-col>
          </template>
          <a-col v-else :span="24">
            <a-alert
              type="warning"
              show-icon
              message="该站点无灭火器配置，保存后规格与生产日期将被清空"
            />
          </a-col>
        </a-row>

        <a-divider orientation="left" style="margin: 8px 0 14px">摄像头信息</a-divider>
        <a-row :gutter="12">
          <a-col :xs="24" :md="8">
            <a-form-item label="球机数量">
              <a-input-number
                v-model:value="extForm.dome_camera_count"
                :min="0"
                :precision="0"
                style="width: 100%"
              />
            </a-form-item>
          </a-col>
          <a-col :xs="24" :md="8">
            <a-form-item label="枪机数量">
              <a-input-number
                v-model:value="extForm.bullet_camera_count"
                :min="0"
                :precision="0"
                style="width: 100%"
              />
            </a-form-item>
          </a-col>
          <a-col :xs="24" :md="8">
            <a-form-item label="监控密码">
              <a-input-password
                v-model:value="extForm.camera_password"
                placeholder="留空表示不修改"
              />
            </a-form-item>
          </a-col>
        </a-row>
      </a-form>
    </a-modal>

    <!-- ---------------- 站点导航与地图分享 ---------------- -->
    <a-modal v-model:open="navOpen" title="站点导航与地图分享（PDF 3.10）" :footer="null" width="620px">
      <a-spin :spinning="navLoading">
        <a-empty v-if="!nav" description="暂无导航信息（站点可能未维护经纬度）" />
        <template v-else>
          <a-descriptions bordered size="small" :column="1">
            <a-descriptions-item label="站点名称">{{ nav.station_name }}</a-descriptions-item>
            <a-descriptions-item label="站点地址">{{ nav.address || '-' }}</a-descriptions-item>
            <a-descriptions-item label="经纬度">
              {{ nav.longitude }}, {{ nav.latitude }}
            </a-descriptions-item>
            <a-descriptions-item label="分享文案">
              {{ nav.share_text }}
            </a-descriptions-item>
          </a-descriptions>

          <a-space style="margin-top: 14px" wrap>
            <a-button type="primary" @click="openLink(nav.navigation_uri)">
              <template #icon><EnvironmentOutlined /></template>
              高德路线导航
            </a-button>
            <a-button @click="openLink(nav.amap_uri)">
              <template #icon><PictureOutlined /></template>
              高德地图查看
            </a-button>
            <a-button @click="openLink(nav.baidu_uri)">
              <template #icon><PictureOutlined /></template>
              百度地图查看
            </a-button>
            <a-button @click="copyText(nav.share_text)">
              <template #icon><CopyOutlined /></template>
              复制分享文案
            </a-button>
          </a-space>
        </template>
      </a-spin>
    </a-modal>

    <!-- ---------------- 导出进度（PDF 3.7：加载动画 + 充分提示） ---------------- -->
    <a-modal
      v-model:open="exportOpen"
      title="台账信息导出"
      :footer="null"
      :closable="!exporting"
      :mask-closable="false"
      width="480px"
    >
      <div class="export-box">
        <a-spin :spinning="exporting" size="large">
          <a-progress
            :percent="exportTask.progress || 0"
            :status="exportStatus"
            :stroke-color="exportStatus === 'exception' ? '#f5222d' : '#2f6fb5'"
          />
        </a-spin>
        <div class="export-title">{{ exportTask.title || '台账导出任务' }}</div>
        <div class="text-muted" style="font-size: 13px">
          {{ exportTask.message || '正在创建导出任务…' }}
        </div>
        <div v-if="exportTask.row_count" class="text-muted" style="font-size: 12px; margin-top: 4px">
          共 {{ exportTask.row_count }} 行数据
        </div>
        <div v-if="exportTask.error" class="text-danger" style="font-size: 12px; margin-top: 6px">
          {{ exportTask.error }}
        </div>

        <a-space style="margin-top: 16px">
          <a-button v-if="exportStatus === 'success'" type="primary" @click="downloadExport">
            <template #icon><DownloadOutlined /></template>
            下载 Excel
          </a-button>
          <a-button v-if="!exporting" @click="exportOpen = false">关闭</a-button>
          <a-button v-else @click="exportOpen = false">后台运行</a-button>
        </a-space>
      </div>
    </a-modal>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { message } from 'ant-design-vue'
import {
  CopyOutlined,
  DatabaseOutlined,
  DownloadOutlined,
  EditOutlined,
  EnvironmentOutlined,
  ExportOutlined,
  PictureOutlined,
  ReloadOutlined,
  SearchOutlined,
  SafetyOutlined,
  SyncOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons-vue'
import StatCard from '@/components/StatCard.vue'
import { adminApi, exportApi } from '@/api'
import { useUserStore } from '@/stores/user'

const store = useUserStore()

/** 灭火器类型（PDF 3.10：增加「无」选项，与后端 EXTINGUISHER_TYPES 保持一致） */
const EXTINGUISHER_TYPES = ['无', '干粉', '二氧化碳', '水基', '洁净气体']
/** attributes 中的字段中文名 */
const ATTR_LABELS = {
  站点地址: '站点地址',
  地形: '地形',
  经度: '经度',
  纬度: '纬度',
  灭火器类型: '灭火器类型',
  灭火器规格: '灭火器规格',
  灭火器生产日期: '灭火器生产日期',
  球机数量: '球机数量',
  枪机数量: '枪机数量',
  联系人: '联系人',
  联系电话: '联系电话',
  设备型号: '设备型号',
  额定功率: '额定功率(kW)',
  充电枪数量: '充电枪数量',
  枪型: '枪型',
  生产厂商: '生产厂商',
  安装日期: '安装日期',
  质保到期: '质保到期',
}

/** 站台台账不重复展示已在列上的字段 */
const STATION_HIDDEN = ['站点地址', '灭火器类型', '灭火器规格', '灭火器生产日期', '充电枪数量']

const activeKey = ref('station')
const loading = ref(false)
const syncing = ref(false)
const stationLoading = ref(false)

const extinguisherTypes = ref(EXTINGUISHER_TYPES)
const list = ref([])
const projectOptions = ref([])
const stationOptions = ref([])
const gunTotal = ref(0)
const tabTotals = reactive({ station: 0, pile: 0 })

const query = reactive({ project_id: undefined, station_id: undefined, keyword: '', status: undefined })
const page = reactive({ page: 1, page_size: 20, total: 0 })

// ---------------------------------------------------------------- 统计卡片
const stationTabTotal = computed(() => (activeKey.value === 'station' ? page.total : tabTotals.station))
const pileTabTotal = computed(() => (activeKey.value === 'pile' ? page.total : tabTotals.pile))

// ---------------------------------------------------------------- 表格列
const columns = computed(() => {
  const base = [
    { title: '台账类型', dataIndex: 'ledger_type', width: 100, fixed: 'left' },
    { title: '资产编码', dataIndex: 'asset_code', width: 170 },
    { title: '资产名称', dataIndex: 'asset_name', width: 160, ellipsis: true },
  ]
  if (activeKey.value === 'pile') {
    base.push(
      { title: '所属项目', dataIndex: 'project_name', width: 150, ellipsis: true },
      { title: '所属站点', dataIndex: 'station_name', width: 170, ellipsis: true },
      { title: '设备型号', dataIndex: '设备型号', width: 140, ellipsis: true },
      { title: '额定功率(kW)', dataIndex: '额定功率(kW)', width: 120 },
      { title: '充电枪数量', dataIndex: 'gun_count', width: 110 },
      { title: '枪型', dataIndex: '枪型', width: 120, ellipsis: true },
      { title: '生产厂商', dataIndex: '生产厂商', width: 150, ellipsis: true },
      { title: '安装日期', dataIndex: '安装日期', width: 120 },
      { title: '质保到期', dataIndex: '质保到期', width: 120 },
    )
  } else {
    base.push(
      { title: '地形', dataIndex: '地形', width: 110 },
      { title: '灭火器', dataIndex: 'extinguisher', width: 200 },
      { title: '球机数量', dataIndex: '球机数量', width: 100 },
      { title: '枪机数量', dataIndex: '枪机数量', width: 100 },
      { title: '联系人', dataIndex: '联系人', width: 110 },
      { title: '联系电话', dataIndex: '联系电话', width: 140 },
    )
  }
  base.push(
    { title: '状态', dataIndex: 'status', width: 100 },
    { title: '更新时间', dataIndex: 'updated_at', width: 160 },
    { title: '操作', dataIndex: 'action', width: 170, fixed: 'right' },
  )
  return base
})

const currentStationId = computed(() => query.station_id)

// ---------------------------------------------------------------- 展示辅助
function ledgerTypeText(type) {
  return type === 'station' ? '站台台账' : '充电桩台账'
}

function statusColor(status) {
  return (
    {
      正常: 'green',
      在线: 'green',
      停用: 'default',
      离线: 'red',
      故障: 'red',
      维修中: 'orange',
    }[status] || 'blue'
  )
}

function formatDate(value) {
  if (!value) return '-'
  return String(value).replace('T', ' ').slice(0, 10)
}

function formatTime(value) {
  if (!value) return '-'
  return String(value).replace('T', ' ').slice(0, 16)
}

function formatCell(value) {
  if (value === null || value === undefined || value === '') return '-'
  if (Array.isArray(value)) return value.join('、')
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

/** 把台账 attributes 平铺到行上，便于按列取值（台账类型列统一用 ledger_type 取中文） */
function flat(record) {
  const attrs = record.attributes || {}
  return {
    ...record,
    ...attrs,
    gun_count: attrs['充电枪数量'],
    // 灭火器三个字段归一到英文键，避免模板里书写中文标识符
    extinguisher_type: attrs['灭火器类型'],
    extinguisher_spec: attrs['灭火器规格'],
    extinguisher_produced_at: attrs['灭火器生产日期'],
  }
}

function customRow(record) {
  return { onClick: () => openDetail(record) }
}

// ---------------------------------------------------------------- 列表加载
async function loadList() {
  loading.value = true
  try {
    const params = {
      ledger_type: activeKey.value,
      page: page.page,
      page_size: page.page_size,
    }
    if (query.keyword) params.keyword = query.keyword
    if (query.project_id) params.project_id = query.project_id
    if (query.station_id) params.station_id = query.station_id
    if (query.status) params.status = query.status
    const res = await adminApi.ledger(params)
    list.value = (res.data?.items || []).map(flat)
    page.total = res.data?.meta?.total || 0
    tabTotals[activeKey.value] = page.total
  } catch {
    list.value = []
    page.total = 0
  } finally {
    loading.value = false
  }
}

/** 另一类台账的记录数（仅用于概览卡片） */
async function loadOtherTotal() {
  const other = activeKey.value === 'station' ? 'pile' : 'station'
  try {
    const res = await adminApi.ledger({ ledger_type: other, page: 1, page_size: 1 })
    tabTotals[other] = res.data?.meta?.total || 0
  } catch {
    /* 忽略 */
  }
}

async function loadGunTotal() {
  try {
    const res = await adminApi.pileStatusSummary()
    gunTotal.value = res.data?.gun_total || 0
  } catch {
    gunTotal.value = 0
  }
}

async function loadProjects() {
  try {
    const res = await adminApi.projects()
    projectOptions.value = (res.data || []).map((p) => ({ value: p.id, label: p.name }))
  } catch {
    projectOptions.value = []
  }
}

async function loadStations(projectId) {
  stationLoading.value = true
  try {
    const res = await adminApi.stationOptions(projectId ? { project_id: projectId } : undefined)
    stationOptions.value = (res.data || []).map((s) => ({
      value: s.id,
      label: `${s.name}（${s.code}）`,
    }))
  } catch {
    stationOptions.value = []
  } finally {
    stationLoading.value = false
  }
}

async function loadExtinguisherTypes() {
  try {
    // 后端参数名为 group，返回参数数组（含 ledger.extinguisher_types）
    const res = await adminApi.configs({ group: 'ledger' })
    const rows = Array.isArray(res.data) ? res.data : res.data?.items || []
    const cfg = rows.find((i) => i.config_key === 'ledger.extinguisher_types')
    if (cfg?.config_value) {
      const parsed = JSON.parse(cfg.config_value)
      if (Array.isArray(parsed) && parsed.length) extinguisherTypes.value = parsed
    }
  } catch {
    /* 使用内置默认选项 */
  }
}

function search() {
  page.page = 1
  loadList()
}

function onTabChange() {
  // 充电桩台账按站点筛选，站台台账不需要站点筛选
  if (activeKey.value === 'station') query.station_id = undefined
  page.page = 1
  loadList()
  loadOtherTotal()
}

function onProjectChange(value) {
  query.station_id = undefined
  loadStations(value)
  search()
}

function onSizeChange(_current, size) {
  page.page = 1
  page.page_size = size
  loadList()
}

function resetQuery() {
  query.project_id = undefined
  query.station_id = undefined
  query.keyword = ''
  query.status = undefined
  loadStations()
  search()
}

async function syncLedger() {
  syncing.value = true
  try {
    const res = await adminApi.syncLedger()
    const d = res.data || {}
    message.success(`台账同步完成：新增 ${d.created || 0} 条，更新 ${d.updated || 0} 条`)
    await Promise.all([loadList(), loadOtherTotal(), loadGunTotal()])
  } catch {
    /* 拦截器已提示 */
  } finally {
    syncing.value = false
  }
}

// ---------------------------------------------------------------- 详情抽屉
const detailOpen = ref(false)
const detailRecord = ref({})

const detailTitle = computed(
  () => `${ledgerTypeText(detailRecord.value.ledger_type)} · ${detailRecord.value.asset_name || ''}`,
)

const detailAttrKeys = computed(() => {
  const keys = Object.keys(detailRecord.value.attributes || {})
  if (detailRecord.value.ledger_type === 'station') {
    return keys.filter((k) => !STATION_HIDDEN.includes(k))
  }
  return keys.filter((k) => k !== '充电枪数量')
})

function openDetail(record) {
  detailRecord.value = record
  detailOpen.value = true
}

// ---------------------------------------------------------------- 二期扩展字段
const extOpen = ref(false)
const extSubmitting = ref(false)
const extForm = reactive({
  station_id: undefined,
  extinguisher_type: '无',
  extinguisher_spec: '',
  extinguisher_produced_at: undefined,
  dome_camera_count: 0,
  bullet_camera_count: 0,
  camera_password: '',
})

function openExtensions(record) {
  const raw = record?.ledger_type === 'station' ? record : null
  const stationId = raw?.station_id || query.station_id
  if (!stationId) {
    message.warning('请先在上方筛选「所属站点」，或在站台台账中选择站点')
    return
  }
  // 台账 attributes 含中文键（灭火器类型 / 球机数量 等），统一用取值函数读取
  const attrs = raw?.attributes || {}
  detailOpen.value = false
  extOpen.value = true
  extForm.station_id = stationId
  extForm.extinguisher_type = attrs['灭火器类型'] || '无'
  extForm.extinguisher_spec = attrs['灭火器规格'] || ''
  extForm.extinguisher_produced_at = attrs['灭火器生产日期'] || undefined
  extForm.dome_camera_count = attrs['球机数量'] ?? 0
  extForm.bullet_camera_count = attrs['枪机数量'] ?? 0
  extForm.camera_password = ''
  // 打开弹窗时同步站点下拉，保证可切换站点
  if (!stationOptions.value.length) loadStations(query.project_id)
}

/** 选择「无」时清空规格与生产日期 */
function onExtinguisherChange(value) {
  if (value === '无') {
    extForm.extinguisher_spec = ''
    extForm.extinguisher_produced_at = undefined
  }
}

async function submitExtensions() {
  if (!extForm.station_id) {
    message.warning('请选择站点')
    return
  }
  extSubmitting.value = true
  try {
    const payload = {
      extinguisher_type: extForm.extinguisher_type,
      extinguisher_spec: extForm.extinguisher_type === '无' ? null : extForm.extinguisher_spec || null,
      extinguisher_produced_at:
        extForm.extinguisher_type === '无' ? null : extForm.extinguisher_produced_at || null,
      dome_camera_count: extForm.dome_camera_count || 0,
      bullet_camera_count: extForm.bullet_camera_count || 0,
    }
    if (extForm.camera_password) payload.camera_password = extForm.camera_password

    await adminApi.updateStationExtensions(extForm.station_id, payload)
    message.success('二期扩展字段已保存')
    extOpen.value = false
    await loadList()
  } catch {
    /* 拦截器已提示 */
  } finally {
    extSubmitting.value = false
  }
}

// ---------------------------------------------------------------- 站点导航与地图分享
const navOpen = ref(false)
const navLoading = ref(false)
const nav = ref(null)

async function openNavigation(record) {
  const stationId =
    record?.ledger_type === 'station' ? record.station_id || undefined : query.station_id
  if (!stationId) {
    message.warning('请先在上方筛选「所属站点」，或在站台台账中选择站点')
    return
  }
  detailOpen.value = false
  navOpen.value = true
  navLoading.value = true
  nav.value = null
  try {
    const res = await adminApi.stationNavigation(stationId)
    nav.value = res.data || null
  } catch {
    nav.value = null
  } finally {
    navLoading.value = false
  }
}

function openLink(uri) {
  if (!uri) {
    message.warning('暂无可用的地图链接')
    return
  }
  window.open(uri, '_blank')
}

async function copyText(text) {
  if (!text) return
  try {
    await navigator.clipboard.writeText(text)
    message.success('分享文案已复制，可直接粘贴到微信分享')
  } catch {
    message.warning('浏览器不支持自动复制，请手动复制分享文案')
  }
}

// ---------------------------------------------------------------- 台账信息导出（任务式 + 进度）
const exportOpen = ref(false)
const exporting = ref(false)
const exportTask = reactive({
  task_id: '',
  title: '台账信息导出',
  status: '',
  progress: 0,
  message: '',
  row_count: 0,
  error: null,
  file_name: '',
})

const exportStatus = computed(() => {
  if (exportTask.status === 'failed') return 'exception'
  if (exportTask.status === 'success') return 'success'
  return 'active'
})

async function exportLedger() {
  exportOpen.value = true
  exporting.value = true
  Object.assign(exportTask, {
    task_id: '',
    title: activeKey.value === 'station' ? '站台台账导出' : '充电桩台账导出',
    status: 'running',
    progress: 0,
    message: '正在创建导出任务…',
    row_count: 0,
    error: null,
    file_name: '',
  })

  try {
    const payload = { ledger_type: activeKey.value }
    if (query.keyword) payload.keyword = query.keyword
    if (query.project_id) payload.project_id = query.project_id
    if (query.station_id) payload.station_id = query.station_id
    if (query.status) payload.status = query.status

    const created = await exportApi.createLedger(payload)
    const task = created.data || {}
    exportTask.task_id = task.task_id
    exportTask.title = task.title || exportTask.title
    exportTask.progress = task.progress || 0
    exportTask.message = task.message || '导出任务已创建'

    const finalTask = await exportApi.poll(exportTask.task_id, (t) => {
      Object.assign(exportTask, {
        status: t.status,
        progress: t.progress || 0,
        message: t.message || '',
        row_count: t.row_count || 0,
        error: t.error || null,
        file_name: t.file_name || '',
        title: t.title || exportTask.title,
      })
    })

    Object.assign(exportTask, {
      status: finalTask.status,
      progress: finalTask.progress || 100,
      message: finalTask.message || '',
      row_count: finalTask.row_count || 0,
      error: finalTask.error || null,
      file_name: finalTask.file_name || '',
    })

    if (finalTask.status === 'success') {
      message.success(`导出完成，共 ${exportTask.row_count} 行，请点击下载`)
    } else {
      message.error(exportTask.error || '导出失败，请稍后重试')
    }
  } catch (err) {
    exportTask.status = 'failed'
    exportTask.error = err?.message || '导出异常'
    exportTask.message = '导出异常'
  } finally {
    exporting.value = false
  }
}

async function downloadExport() {
  if (!exportTask.task_id) return
  try {
    await exportApi.download(exportTask.task_id, exportTask.file_name || 'asset_ledger.xlsx')
    message.success('已开始下载导出文件')
  } catch {
    /* 拦截器已提示 */
  }
}

onMounted(() => {
  loadProjects()
  loadStations()
  loadExtinguisherTypes()
  loadGunTotal()
  loadList()
  loadOtherTotal()
})
</script>

<style scoped>
.table-pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 14px;
}

.export-box {
  text-align: center;
  padding: 6px 0 2px;
}

.export-title {
  font-size: 15px;
  font-weight: 600;
  color: #1f4e79;
  margin: 14px 0 4px;
}
</style>
