<template>
  <div class="page">
    <!-- ---------------- 页头 ---------------- -->
    <div class="page-header">
      <div>
        <h2 class="page-title"><WarningOutlined /> 故障管理</h2>
        <div class="page-subtitle">
          故障上报 · 故障卡片 · 核查跟踪（PDF 3.5）　·　数据权限：{{ store.dataScope }}
        </div>
      </div>
      <a-space>
        <a-button :loading="loading" @click="refreshAll">
          <template #icon><ReloadOutlined /></template>
          刷新
        </a-button>
        <a-button type="primary" @click="openReport">
          <template #icon><PlusOutlined /></template>
          故障上报
        </a-button>
      </a-space>
    </div>

    <!-- ---------------- 故障首页统计卡片（PDF 3.5） ---------------- -->
    <a-row :gutter="[14, 14]">
      <a-col :xs="12" :sm="12" :md="6">
        <StatCard
          label="累计已上报"
          :value="home.total"
          suffix="条"
          tone="primary"
          :icon="WarningOutlined"
        />
      </a-col>
      <a-col :xs="12" :sm="12" :md="6">
        <StatCard
          label="已核查"
          :value="home.verified"
          suffix="条"
          tone="success"
          :icon="CheckCircleOutlined"
          :hint="`核查驳回 ${home.rejected} 条`"
        />
      </a-col>
      <a-col :xs="12" :sm="12" :md="6">
        <StatCard
          label="待核查"
          :value="home.pending"
          suffix="条"
          tone="warning"
          :icon="ClockCircleOutlined"
          hint="按故障等级时限响应"
        />
      </a-col>
      <a-col :xs="12" :sm="12" :md="6">
        <StatCard
          label="核查率"
          :value="home.verify_rate"
          suffix="%"
          tone="success"
          :icon="RiseOutlined"
          :hint="`核查通过 ${home.verified} / 累计上报 ${home.total}`"
        />
      </a-col>
    </a-row>

    <!-- ---------------- 过滤 + tab ---------------- -->
    <a-card size="small" :bordered="false" style="margin-top: 14px">
      <a-tabs v-model:activeKey="query.tab" size="small" @change="onTabChange">
        <a-tab-pane key="全部" tab="全部故障" />
        <a-tab-pane key="待核查" tab="待核查" />
        <a-tab-pane key="已核查" tab="已核查" />
      </a-tabs>

      <div class="filter-bar" style="box-shadow: none; padding: 0 0 14px">
        <a-form layout="inline" :model="query">
          <a-form-item label="站点 / 桩资产码">
            <a-input
              v-model:value="query.keyword"
              placeholder="站点名称 / 桩资产码 / 故障编号"
              allow-clear
              style="width: 260px"
              @press-enter="search"
            >
              <template #prefix><SearchOutlined /></template>
            </a-input>
          </a-form-item>
          <a-form-item label="故障等级">
            <a-select
              v-model:value="query.fault_level"
              placeholder="全部等级"
              allow-clear
              style="width: 130px"
              @change="search"
            >
              <a-select-option v-for="lv in dicts.levels" :key="lv" :value="lv">
                {{ lv }}
              </a-select-option>
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

      <!-- ---------------- 故障卡片信息 ---------------- -->
      <a-spin :spinning="loading">
        <a-empty v-if="!list.length" description="当前条件下暂无故障记录" />
        <a-row v-else :gutter="[12, 12]">
          <a-col v-for="f in list" :key="f.id" :xs="24" :sm="12" :lg="8" :xxl="6">
            <div class="fault-card" @click="goDetail(f.id)">
              <div class="fault-card-head">
                <a-tag :color="statusColor(f.status)">{{ f.status }}</a-tag>
                <a-tag :color="levelColor(f.fault_level)">{{ f.fault_level }}</a-tag>
                <span v-if="f.is_draft" class="text-muted" style="font-size: 12px">草稿</span>
              </div>
              <div class="fault-card-title">
                {{ f.fault_type || '未分类故障' }}
                <span class="mono fault-card-no">{{ f.fault_no }}</span>
              </div>
              <div class="fault-card-line">
                <EnvironmentOutlined /> 站点：{{ f.station_name || '-' }}
              </div>
              <div class="fault-card-line">
                <ThunderboltOutlined /> 资产码：{{ f.pile_asset_code || '-' }}
              </div>
              <div class="fault-card-line">
                <UserOutlined /> 上报人：{{ f.reporter_name || '-' }}
                <span class="text-muted">　{{ formatTime(f.reported_at || f.created_at) }}</span>
              </div>
              <div class="fault-card-desc">{{ f.description || '无故障描述' }}</div>
              <div v-if="f.images && f.images.length" class="fault-card-imgs">
                <span
                  v-for="(img, idx) in f.images.slice(0, 3)"
                  :key="idx"
                  class="thumb-wrap"
                  @click.stop
                >
                  <a-image
                    :src="img"
                    :width="46"
                    :height="46"
                    style="object-fit: cover; border-radius: 4px"
                  />
                </span>
                <span v-if="f.images.length > 3" class="text-muted" style="font-size: 12px">
                  +{{ f.images.length - 3 }} 张
                </span>
              </div>
            </div>
          </a-col>
        </a-row>
      </a-spin>

      <!-- ---------------- 服务端分页 ---------------- -->
      <div class="table-pager">
        <a-pagination
          v-model:current="page.page"
          v-model:page-size="page.page_size"
          :total="page.total"
          :page-size-options="['12', '24', '48', '96']"
          size="small"
          show-size-changer
          show-total
          :show-total="(t) => `共 ${t} 条故障`"
          @change="loadList"
          @showSizeChange="onSizeChange"
        />
      </div>
    </a-card>

    <!-- ---------------- 故障上报弹窗（PDF 3.5） ---------------- -->
    <a-modal
      v-model:open="reportOpen"
      title="故障上报"
      width="720px"
      :confirm-loading="submitting"
      :mask-closable="false"
      @cancel="closeReport"
    >
      <a-form ref="formRef" layout="vertical" :model="form" :rules="rules">
        <a-row :gutter="12">
          <a-col :xs="24" :md="8">
            <a-form-item label="所属项目" name="project_id">
              <a-select
                v-model:value="form.project_id"
                placeholder="请选择项目"
                allow-clear
                show-search
                option-filter-prop="label"
                :options="projectOptions"
                @change="onFormProjectChange"
              />
            </a-form-item>
          </a-col>
          <a-col :xs="24" :md="8">
            <a-form-item label="所属站点" name="station_id">
              <a-select
                v-model:value="form.station_id"
                placeholder="请选择站点"
                allow-clear
                show-search
                option-filter-prop="label"
                :options="formStationOptions"
                :loading="stationLoading"
                @change="onFormStationChange"
              />
            </a-form-item>
          </a-col>
          <a-col :xs="24" :md="8">
            <a-form-item label="充电桩资产码" name="pile_id">
              <a-select
                v-model:value="form.pile_id"
                placeholder="请选择充电桩资产码"
                allow-clear
                show-search
                option-filter-prop="label"
                :options="pileOptions"
                :loading="pileLoading"
              />
            </a-form-item>
          </a-col>
        </a-row>

        <a-row :gutter="12">
          <a-col :xs="24" :md="8">
            <a-form-item label="故障类型" name="fault_type">
              <a-input
                v-model:value="form.fault_type"
                placeholder="如：通信故障 / 绝缘监测报警"
                :maxlength="64"
              />
            </a-form-item>
          </a-col>
          <a-col :xs="24" :md="8">
            <a-form-item label="故障等级" name="fault_level">
              <a-select v-model:value="form.fault_level" placeholder="不选则按描述自动判定">
                <a-select-option v-for="lv in dicts.levels" :key="lv" :value="lv">
                  {{ lv }}（{{ dicts.level_sla_hours?.[lv] ?? '-' }} 小时响应）
                </a-select-option>
              </a-select>
            </a-form-item>
          </a-col>
          <a-col :xs="24" :md="8">
            <a-form-item label="发生时间">
              <a-date-picker
                v-model:value="form.occurred_at"
                show-time
                value-format="YYYY-MM-DD HH:mm:ss"
                placeholder="默认当前时间"
                style="width: 100%"
              />
            </a-form-item>
          </a-col>
        </a-row>

        <a-form-item label="故障描述" name="description">
          <a-textarea
            v-model:value="form.description"
            :rows="4"
            :maxlength="500"
            show-count
            placeholder="请描述故障现象（含「起火、漏电、跳闸、无法充电」等关键词时系统会自动建议等级）"
          />
        </a-form-item>

        <!-- 多图上传（走 /api/v1/uploads/images，图片真实落盘并可回显） -->
        <a-form-item :label="`现场照片（最多 ${MAX_IMAGES} 张）`">
          <ImageUploader
            v-model:value="form.images"
            biz-type="fault"
            :max-count="MAX_IMAGES"
          />
        </a-form-item>
      </a-form>

      <template #footer>
        <a-space>
          <a-button @click="closeReport">取消</a-button>
          <a-button :loading="submitting" @click="submit(false, true)">
            <template #icon><FileTextOutlined /></template>
            保存草稿
          </a-button>
          <a-button type="primary" :loading="submitting" @click="submit(false, false)">
            <template #icon><CheckCircleOutlined /></template>
            确认上报
          </a-button>
        </a-space>
      </template>
    </a-modal>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import {
  CheckCircleOutlined,
  ClockCircleOutlined,
  CloseCircleOutlined,
  EnvironmentOutlined,
  FileTextOutlined,
  PlusOutlined,
  ReloadOutlined,
  RiseOutlined,
  SearchOutlined,
  ThunderboltOutlined,
  UserOutlined,
  WarningOutlined,
} from '@ant-design/icons-vue'
import StatCard from '@/components/StatCard.vue'
import ImageUploader from '@/components/ImageUploader.vue'
import { adminApi, faultApi } from '@/api'
import { useUserStore } from '@/stores/user'

const router = useRouter()
const store = useUserStore()

const MAX_IMAGES = 6

// ---------------------------------------------------------------- 状态
const loading = ref(false)
const submitting = ref(false)
const stationLoading = ref(false)
const pileLoading = ref(false)

const home = reactive({ total: 0, verified: 0, pending: 0, rejected: 0, verify_rate: 0 })
const dicts = reactive({ levels: [], statuses: [], verify_results: [], level_sla_hours: {} })
const list = ref([])

const query = reactive({ tab: '全部', keyword: '', fault_level: undefined })
const page = reactive({ page: 1, page_size: 12, total: 0 })

// ---------------------------------------------------------------- 故障上报表单
const reportOpen = ref(false)
const formRef = ref(null)
const projectOptions = ref([])
const formStationOptions = ref([])
const pileOptions = ref([])

const form = reactive({
  project_id: undefined,
  station_id: undefined,
  pile_id: undefined,
  fault_type: '',
  fault_level: undefined,
  description: '',
  occurred_at: undefined,
  images: [],
})

const rules = {
  project_id: [{ required: true, message: '请选择所属项目', trigger: 'change' }],
  station_id: [{ required: true, message: '请选择所属站点', trigger: 'change' }],
  fault_type: [{ required: true, message: '请填写故障类型', trigger: 'blur' }],
  description: [{ required: true, message: '请填写故障描述', trigger: 'blur' }],
}

// ---------------------------------------------------------------- 展示辅助
function levelColor(level) {
  return { 一般: 'green', 严重: 'orange', 危急: 'red' }[level] || 'default'
}

function statusColor(status) {
  return (
    {
      待上报: 'default',
      待核查: 'orange',
      核查通过: 'green',
      核查驳回: 'red',
    }[status] || 'default'
  )
}

function formatTime(value) {
  if (!value) return '-'
  return String(value).replace('T', ' ').slice(0, 16)
}

// ---------------------------------------------------------------- 列表加载
async function loadHome() {
  try {
    const res = await faultApi.home()
    const d = res.data || {}
    home.total = d.total || 0
    home.verified = d.verified || 0
    home.pending = d.pending || 0
    home.rejected = d.rejected || 0
    home.verify_rate = d.verify_rate || 0
  } catch {
    /* 拦截器已提示 */
  }
}

async function loadDicts() {
  try {
    const res = await faultApi.dicts()
    const d = res.data || {}
    dicts.levels = d.levels || ['一般', '严重', '危急']
    dicts.statuses = d.statuses || []
    dicts.verify_results = d.verify_results || []
    dicts.level_sla_hours = d.level_sla_hours || {}
  } catch {
    dicts.levels = ['一般', '严重', '危急']
  }
}

async function loadList() {
  loading.value = true
  try {
    const params = {
      page: page.page,
      page_size: page.page_size,
      tab: query.tab,
    }
    if (query.keyword) params.keyword = query.keyword
    if (query.fault_level) params.fault_level = query.fault_level
    const res = await faultApi.list(params)
    list.value = res.data?.items || []
    page.total = res.data?.meta?.total || 0
  } catch {
    list.value = []
    page.total = 0
  } finally {
    loading.value = false
  }
}

function search() {
  page.page = 1
  loadList()
}

function onTabChange() {
  search()
}

function onSizeChange(_current, size) {
  page.page = 1
  page.page_size = size
  loadList()
}

function resetQuery() {
  query.keyword = ''
  query.fault_level = undefined
  search()
}

function refreshAll() {
  loadHome()
  loadList()
}

function goDetail(id) {
  router.push(`/faults/${id}`)
}

// ---------------------------------------------------------------- 上报弹窗
async function loadProjects() {
  try {
    const res = await adminApi.projects()
    projectOptions.value = (res.data || []).map((p) => ({ value: p.id, label: p.name }))
  } catch {
    projectOptions.value = []
  }
}

/** 项目 → 站点级联 */
async function loadFormStations(projectId) {
  stationLoading.value = true
  try {
    const res = await adminApi.stationOptions(
      projectId ? { project_id: projectId } : undefined,
    )
    formStationOptions.value = (res.data || []).map((s) => ({
      value: s.id,
      label: `${s.name}（${s.code}）`,
    }))
  } catch {
    formStationOptions.value = []
  } finally {
    stationLoading.value = false
  }
}

/** 站点（或项目）→ 充电桩资产码级联 */
async function loadPileOptions({ projectId, stationId } = {}) {
  pileLoading.value = true
  try {
    const params = {}
    if (stationId) params.station_id = stationId
    else if (projectId) params.project_id = projectId
    const res = await faultApi.pileOptions(params)
    pileOptions.value = (res.data || []).map((p) => ({
      value: p.id,
      label: `${p.asset_code}　${p.name || ''}${p.station_name ? `　(${p.station_name})` : ''}`,
    }))
  } catch {
    pileOptions.value = []
  } finally {
    pileLoading.value = false
  }
}

function onFormProjectChange(value) {
  form.station_id = undefined
  form.pile_id = undefined
  formStationOptions.value = []
  pileOptions.value = []
  loadFormStations(value)
  loadPileOptions({ projectId: value })
}

function onFormStationChange(value) {
  form.pile_id = undefined
  loadPileOptions({ stationId: value })
}

async function openReport() {
  reportOpen.value = true
  form.project_id = undefined
  form.station_id = undefined
  form.pile_id = undefined
  form.fault_type = ''
  form.fault_level = undefined
  form.description = ''
  form.occurred_at = undefined
  form.images = []
  formStationOptions.value = []
  pileOptions.value = []
  if (!projectOptions.value.length) await loadProjects()
}

function closeReport() {
  reportOpen.value = false
}

// ---------------------------------------------------------------- 多图上传
// 由 ImageUploader 组件负责：逐张调 /api/v1/uploads/images 拿到真实 URL，
// 随故障表单提交后，后端会把 attachment.biz_id 回填到该故障单。

// ---------------------------------------------------------------- 提交
async function submit(_, isDraft) {
  try {
    await formRef.value?.validate()
  } catch {
    return
  }
  submitting.value = true
  try {
    const payload = {
      project_id: form.project_id,
      station_id: form.station_id,
      pile_id: form.pile_id || null,
      fault_type: form.fault_type,
      fault_level: form.fault_level || null,
      description: form.description,
      images: [...form.images],
      occurred_at: form.occurred_at || null,
      is_draft: isDraft,
    }
    const res = await faultApi.report(payload)
    message.success(res.message || (isDraft ? '故障草稿已保存' : '故障上报成功，等待核查'))
    reportOpen.value = false
    page.page = 1
    // 上报成功后刷新统计与列表
    await Promise.all([loadHome(), loadList()])
  } catch {
    /* 拦截器已提示 */
  } finally {
    submitting.value = false
  }
}

onMounted(() => {
  loadDicts()
  loadProjects()
  loadHome()
  loadList()
})
</script>

<style scoped>
.fault-card {
  border: 1px solid #e8e8e8;
  border-radius: 8px;
  padding: 12px 14px;
  cursor: pointer;
  transition: all 0.2s;
  height: 100%;
  background: #fff;
}

.fault-card:hover {
  border-color: #2f6fb5;
  box-shadow: 0 4px 14px rgba(47, 111, 181, 0.14);
}

.fault-card-head {
  display: flex;
  align-items: center;
  gap: 5px;
  margin-bottom: 8px;
  flex-wrap: wrap;
}

.fault-card-title {
  font-weight: 600;
  font-size: 14px;
  margin-bottom: 6px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.fault-card-no {
  font-size: 12px;
  font-weight: 400;
  color: #a0a6ad;
}

.fault-card-line {
  font-size: 12px;
  color: #646a73;
  line-height: 1.9;
}

.fault-card-desc {
  font-size: 12px;
  color: #8c8c8c;
  margin-top: 6px;
  min-height: 34px;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.fault-card-imgs {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 8px;
}

/* 卡片内的缩略图：阻止点击冒泡到卡片跳转 */
.thumb-wrap {
  display: inline-flex;
  line-height: 0;
}

.table-pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 14px;
}
</style>
