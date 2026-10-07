<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h2 class="page-title">
          <a-button type="text" size="small" @click="router.back()">
            <template #icon><ArrowLeftOutlined /></template>
          </a-button>
          工单详情
        </h2>
        <div class="page-subtitle">
          {{ detail.work_order?.order_no }}　·　{{ detail.work_order?.order_name }}
        </div>
      </div>
      <a-space>
        <a-button :loading="loading" @click="load">
          <template #icon><ReloadOutlined /></template>
          刷新
        </a-button>
        <a-button v-if="perms.can_accept" type="primary" @click="doAccept">接受工单</a-button>
        <a-button v-if="perms.can_reject" danger @click="openAction('reject')">退回</a-button>
        <a-button v-if="perms.can_cancel" @click="openAction('cancel')">取消工单</a-button>
      </a-space>
    </div>

    <a-spin :spinning="loading">
      <!-- ---------------- 基本信息 ---------------- -->
      <a-card :bordered="false" title="工单信息">
        <a-descriptions :column="{ xs: 1, sm: 2, lg: 3 }" bordered size="small">
          <a-descriptions-item label="工单编号">
            <span class="mono">{{ wo.order_no }}</span>
          </a-descriptions-item>
          <a-descriptions-item label="工单名称">{{ wo.order_name }}</a-descriptions-item>
          <a-descriptions-item label="工单类型">
            <a-tag :color="typeColor(wo.order_type)">{{ wo.order_type }}</a-tag>
          </a-descriptions-item>
          <a-descriptions-item label="工单状态">
            <a-tag :color="statusColor(wo.status)">{{ wo.status }}</a-tag>
          </a-descriptions-item>
          <a-descriptions-item label="时间状态">
            <a-tag :color="timeColor(wo.time_status)">{{ wo.time_status }}</a-tag>
          </a-descriptions-item>
          <a-descriptions-item label="来源">
            <a-tag :color="wo.source === 'AI 生成' ? 'purple' : 'default'">{{ wo.source }}</a-tag>
          </a-descriptions-item>
          <a-descriptions-item label="站点（{{ (wo.station_names || []).length }}）" :span="2">
            {{ (wo.station_names || []).join('、') || wo.station_name || '-' }}
          </a-descriptions-item>
          <a-descriptions-item label="站点地点">
            {{ wo.station_address || '-' }}
          </a-descriptions-item>
          <a-descriptions-item label="巡检人员">{{ wo.inspector_name || '未分配' }}</a-descriptions-item>
          <a-descriptions-item label="巡检频率">{{ wo.inspect_frequency }}</a-descriptions-item>
          <a-descriptions-item label="巡检次数">{{ wo.inspect_count }}</a-descriptions-item>
          <a-descriptions-item label="巡检周期">{{ wo.inspect_cycle }}</a-descriptions-item>
          <a-descriptions-item label="巡检日期" :span="2">
            {{ wo.inspect_start_date || '-' }} ~ {{ wo.inspect_end_date || '-' }}
          </a-descriptions-item>
          <a-descriptions-item label="备注" :span="3">{{ wo.remark || '-' }}</a-descriptions-item>
          <a-descriptions-item v-if="wo.reject_reason" label="退回原因" :span="3">
            <span class="text-danger">{{ wo.reject_reason }}</span>
          </a-descriptions-item>
          <a-descriptions-item v-if="wo.cancel_reason" label="取消原因" :span="3">
            <span class="text-danger">{{ wo.cancel_reason }}</span>
          </a-descriptions-item>
        </a-descriptions>

        <a-row :gutter="14" style="margin-top: 16px">
          <a-col :xs="12" :sm="6">
            <StatCard label="子任务总数" :value="stats.total" />
          </a-col>
          <a-col :xs="12" :sm="6">
            <StatCard label="待完成" :value="stats.pending + stats.in_progress" tone="warning" />
          </a-col>
          <a-col :xs="12" :sm="6">
            <StatCard label="已完成" :value="stats.completed" tone="success" />
          </a-col>
          <a-col :xs="12" :sm="6">
            <StatCard label="完成进度" :value="overallPercent" suffix="%" tone="primary" />
          </a-col>
        </a-row>
      </a-card>

      <!-- ---------------- 子任务 ---------------- -->
      <a-card :bordered="false" style="margin-top: 14px">
        <a-tabs v-model:activeKey="activeTab">
          <a-tab-pane key="subtasks">
            <template #tab>
              <ScheduleOutlined /> 待完成子任务（{{ detail.subtasks?.length || 0 }}）
            </template>

            <a-table
              :columns="subtaskColumns"
              :data-source="detail.subtasks || []"
              row-key="id"
              size="small"
              :pagination="{ pageSize: 10, showTotal: (t) => `共 ${t} 条` }"
            >
              <template #bodyCell="{ column, record }">
                <template v-if="column.key === 'seq'">
                  <a-badge :count="record.sequence" :number-style="{ backgroundColor: '#2f6fb5' }" />
                </template>
                <template v-else-if="column.key === 'status'">
                  <a-tag :color="subtaskColor(record.status)">{{ record.status }}</a-tag>
                </template>
                <template v-else-if="column.key === 'summary'">
                  <span class="text-muted">{{ record.item_summary || '-' }}</span>
                </template>
                <template v-else-if="column.key === 'action'">
                  <a
                    v-if="record.status !== '已完成' && record.status !== '已取消'"
                    @click="openInspection(record)"
                  >
                    巡检录入
                  </a>
                  <span v-else class="text-muted">-</span>
                </template>
              </template>
            </a-table>
          </a-tab-pane>

          <a-tab-pane key="inspection">
            <template #tab><FileTextOutlined /> 巡检详情</template>
            <a-empty v-if="!(inspectionData.subtasks || []).length" description="暂无巡检数据" />
            <div v-else>
              <div
                v-for="st in inspectionData.subtasks"
                :key="st.subtask_id"
                class="inspection-block"
              >
                <div class="inspection-head">
                  <a-badge :count="st.sequence" :number-style="{ backgroundColor: '#2f6fb5' }" />
                  <strong style="margin: 0 8px">{{ st.station_name }}</strong>
                  <a-tag :color="subtaskColor(st.status)">{{ st.status }}</a-tag>
                  <span class="text-muted" style="margin-left: 8px; font-size: 12px">
                    {{ st.plan_date }}　{{ st.pile_asset_code || '' }}
                  </span>
                </div>

                <a-empty v-if="!st.records?.length" description="该子任务尚未录入巡检" />
                <div v-for="r in st.records" :key="r.id" class="record-block">
                  <a-descriptions size="small" :column="{ xs: 1, sm: 2, lg: 3 }">
                    <a-descriptions-item label="巡检人">{{ st.assignee_name || '-' }}</a-descriptions-item>
                    <a-descriptions-item label="签到时间">{{ fmt(r.checkin_time) }}</a-descriptions-item>
                    <a-descriptions-item label="签退时间">{{ fmt(r.checkout_time) }}</a-descriptions-item>
                    <a-descriptions-item label="签到定位" :span="2">
                      {{ r.checkin_location || '-' }}
                    </a-descriptions-item>
                    <a-descriptions-item label="巡检结果">
                      <a-tag color="green">正常 {{ r.normal_count }}</a-tag>
                      <a-tag :color="r.abnormal_count ? 'red' : 'default'">
                        异常 {{ r.abnormal_count }}
                      </a-tag>
                    </a-descriptions-item>
                    <a-descriptions-item label="备注" :span="3">
                      {{ r.remark || '-' }}
                    </a-descriptions-item>
                  </a-descriptions>

                  <a-table
                    v-if="st.items?.length"
                    :columns="itemColumns"
                    :data-source="st.items"
                    row-key="id"
                    size="small"
                    :pagination="false"
                    style="margin-top: 8px"
                  >
                    <template #bodyCell="{ column, record }">
                      <template v-if="column.key === 'result'">
                        <a-tag :color="record.result === '异常' ? 'red' : 'green'">
                          {{ record.result }}
                        </a-tag>
                      </template>
                      <template v-else-if="column.key === 'images'">
                        <a-space v-if="record.images?.length" wrap>
                          <a
                            v-for="(img, i) in record.images"
                            :key="i"
                            :href="img"
                            target="_blank"
                            class="text-muted"
                          >
                            <PictureOutlined /> 图{{ i + 1 }}
                          </a>
                        </a-space>
                        <span v-else class="text-muted">无</span>
                      </template>
                    </template>
                  </a-table>
                </div>
              </div>
            </div>
          </a-tab-pane>
        </a-tabs>
      </a-card>
    </a-spin>

    <!-- ---------------- 巡检录入 ---------------- -->
    <a-modal
      v-model:open="inspectionOpen"
      title="巡检情况录入"
      width="900px"
      :confirm-loading="submitting"
      ok-text="提交并结单"
      @ok="submitInspection(false)"
    >
      <a-alert
        type="info"
        show-icon
        style="margin-bottom: 14px"
        :message="`当前工单类型：${wo.order_type}　子任务 #${currentSubtask?.sequence}`"
        description="支持分类显示、正常/异常勾选、多图上传，备注最多 200 字（PDF 3.4）"
      />

      <a-form layout="vertical">
        <a-row :gutter="14">
          <a-col :span="8">
            <a-form-item label="签到位置">
              <a-input v-model:value="inspForm.checkin_location" placeholder="如：阳澄湖服务区" />
            </a-form-item>
          </a-col>
          <a-col :span="8">
            <a-form-item label="签退位置">
              <a-input v-model:value="inspForm.checkout_location" placeholder="选填" />
            </a-form-item>
          </a-col>
        </a-row>

        <a-form-item label="现场照片（多图上传）">
          <ImageUploader
            v-model:value="inspForm.images"
            biz-type="inspection"
            :biz-id="currentSubtask?.work_order_id"
            :max-count="12"
          />
        </a-form-item>

        <a-divider style="margin: 4px 0 12px">巡检项（按分类）</a-divider>

        <div v-for="group in groupedItems" :key="group.name" class="item-group">
          <div class="item-group-title">
            <a-tag color="blue">{{ group.name }}</a-tag>
            <a-space size="small">
              <a @click="setGroup(group.items, '正常')">全部正常</a>
              <a @click="setGroup(group.items, '异常')">全部异常</a>
            </a-space>
          </div>
          <div v-for="item in group.items" :key="item.item_name" class="item-row">
            <div class="item-name">{{ item.item_name }}</div>
            <a-radio-group v-model:value="item.result" size="small" button-style="solid">
              <a-radio-button value="正常">正常</a-radio-button>
              <a-radio-button value="异常">异常</a-radio-button>
            </a-radio-group>
            <a-input
              v-model:value="item.remark"
              size="small"
              :maxlength="200"
              placeholder="异常备注（最多 200 字）"
              style="flex: 1"
              :disabled="item.result !== '异常'"
            />
          </div>
        </div>

        <a-form-item label="巡检总结备注（最多 200 字）" style="margin-top: 14px">
          <a-textarea
            v-model:value="inspForm.remark"
            :rows="2"
            :maxlength="200"
            show-count
            placeholder="现场总体情况说明"
          />
        </a-form-item>

        <a-space>
          <a-button :loading="submitting" @click="submitInspection(true)">
            仅保存（巡检中）
          </a-button>
          <span class="text-muted" style="font-size: 12px">
            正常 {{ normalCount }} 项 · 异常 {{ abnormalCount }} 项
          </span>
        </a-space>
      </a-form>
    </a-modal>

    <!-- ---------------- 退回 / 取消 ---------------- -->
    <a-modal
      v-model:open="actionOpen"
      :title="actionType === 'reject' ? '退回工单' : '取消工单'"
      @ok="submitAction"
    >
      <a-form layout="vertical">
        <a-form-item label="原因" required>
          <a-textarea v-model:value="actionReason" :rows="3" />
        </a-form-item>
      </a-form>
    </a-modal>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import {
  ArrowLeftOutlined,
  FileTextOutlined,
  PictureOutlined,
  ReloadOutlined,
  ScheduleOutlined,
} from '@ant-design/icons-vue'
import dayjs from 'dayjs'
import ImageUploader from '@/components/ImageUploader.vue'
import StatCard from '@/components/StatCard.vue'
import { workOrderApi } from '@/api'

const route = useRoute()
const router = useRouter()
const orderId = route.params.id

const loading = ref(false)
const detail = reactive({ work_order: {}, subtasks: [], subtask_stats: {}, permissions: {} })
const inspectionData = reactive({ subtasks: [] })
const activeTab = ref('subtasks')

const wo = computed(() => detail.work_order || {})
const stats = computed(() => detail.subtask_stats || { total: 0, pending: 0, in_progress: 0, completed: 0 })
const perms = computed(() => detail.permissions || {})
const overallPercent = computed(() => {
  const s = stats.value
  return s.total ? Math.round((s.completed / s.total) * 100) : 0
})

const subtaskColumns = [
  { title: '#', key: 'seq', width: 60 },
  { title: '站点', dataIndex: 'station_name', width: 190, ellipsis: true },
  { title: '资产码', dataIndex: 'pile_asset_code', width: 120 },
  { title: '计划日期', dataIndex: 'plan_date', width: 110 },
  { title: '时间段', dataIndex: 'plan_time_window', width: 110 },
  { title: '执行人', dataIndex: 'assignee_name', width: 100 },
  { title: '状态', key: 'status', width: 90 },
  { title: '巡检摘要', key: 'summary', ellipsis: true },
  { title: '操作', key: 'action', width: 100, fixed: 'right' },
]

const itemColumns = [
  { title: '分类', dataIndex: 'item_group', width: 120 },
  { title: '巡检项', dataIndex: 'item_name', ellipsis: true },
  { title: '结果', key: 'result', width: 80 },
  { title: '备注', dataIndex: 'remark', ellipsis: true },
  { title: '图片', key: 'images', width: 150 },
]

function typeColor(t) {
  return { 巡视: 'blue', 特巡: 'purple', 消缺: 'red', 设备检查: 'cyan', 其他: 'default' }[t] || 'default'
}
function statusColor(s) {
  return { 待接单: 'orange', 待完成: 'blue', 已完成: 'green', 已取消: 'default', 已退回: 'red' }[s] || 'default'
}
function timeColor(s) {
  return { 正常: 'green', 紧急: 'orange', 逾期: 'red' }[s] || 'default'
}
function subtaskColor(s) {
  return { 待完成: 'orange', 巡检中: 'blue', 已完成: 'green', 已取消: 'default' }[s] || 'default'
}
function fmt(v) {
  return v ? dayjs(v).format('YYYY-MM-DD HH:mm') : '-'
}

async function load() {
  loading.value = true
  try {
    const [d, insp] = await Promise.all([
      workOrderApi.detail(orderId),
      workOrderApi.inspectionDetail(orderId).catch(() => ({ data: { subtasks: [] } })),
    ])
    Object.assign(detail, d.data || {})
    Object.assign(inspectionData, insp.data || { subtasks: [] })
  } finally {
    loading.value = false
  }
}

async function doAccept() {
  await workOrderApi.accept(orderId)
  message.success('已接受工单')
  load()
}

const actionOpen = ref(false)
const actionType = ref('reject')
const actionReason = ref('')

function openAction(type) {
  actionType.value = type
  actionReason.value = ''
  actionOpen.value = true
}

async function submitAction() {
  if (!actionReason.value.trim()) {
    message.warning('请填写原因')
    return
  }
  if (actionType.value === 'reject') {
    await workOrderApi.reject(orderId, { reason: actionReason.value })
    message.success('工单已退回')
  } else {
    await workOrderApi.cancel(orderId, { reason: actionReason.value })
    message.success('工单已取消')
  }
  actionOpen.value = false
  load()
}

// ---------------------------------------------------------------- 巡检录入
const inspectionOpen = ref(false)
const submitting = ref(false)
const currentSubtask = ref(null)
const templateItems = ref([])
const inspForm = reactive({
  checkin_location: '',
  checkout_location: '',
  remark: '',
  images: [],
})

const groupedItems = computed(() => {
  const map = new Map()
  for (const item of templateItems.value) {
    const key = item.item_group || '通用'
    if (!map.has(key)) map.set(key, [])
    map.get(key).push(item)
  }
  return [...map.entries()].map(([name, items]) => ({ name, items }))
})

const normalCount = computed(() => templateItems.value.filter((i) => i.result === '正常').length)
const abnormalCount = computed(() => templateItems.value.filter((i) => i.result === '异常').length)

function setGroup(items, result) {
  items.forEach((i) => {
    i.result = result
  })
}

async function openInspection(subtask) {
  currentSubtask.value = subtask
  Object.assign(inspForm, {
    checkin_location: subtask.station_name || '',
    checkout_location: subtask.station_name || '',
    remark: '',
    images: [],
  })
  const res = await workOrderApi.inspectionTemplate({ order_type: wo.value.order_type || '巡视' })
  templateItems.value = (res.data?.template || []).map((t) => ({
    ...t,
    result: '正常',
    remark: '',
  }))
  inspectionOpen.value = true
}

async function submitInspection(saveOnly) {
  if (!templateItems.value.length) {
    message.warning('未加载到巡检项模板')
    return
  }
  submitting.value = true
  try {
    await workOrderApi.createInspection({
      subtask_id: currentSubtask.value.id,
      items: templateItems.value.map((i) => ({
        item_name: i.item_name,
        item_group: i.item_group,
        result: i.result,
        remark: i.remark || '',
        images: [],
      })),
      images: inspForm.images || [],
      remark: inspForm.remark,
      checkin_location: inspForm.checkin_location,
      checkout_location: inspForm.checkout_location,
      finish: !saveOnly,
    })
    message.success(saveOnly ? '已保存为巡检中' : '巡检提交成功，子任务已结单')
    inspectionOpen.value = false
    load()
  } catch {
    /* 已提示 */
  } finally {
    submitting.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.inspection-block {
  border: 1px solid #e8e8e8;
  border-radius: 8px;
  padding: 12px 14px;
  margin-bottom: 12px;
}

.inspection-head {
  display: flex;
  align-items: center;
  margin-bottom: 10px;
}

.record-block {
  background: #fafbfc;
  border-radius: 6px;
  padding: 10px 12px;
  margin-bottom: 10px;
}

.item-group {
  margin-bottom: 14px;
}

.item-group-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}

.item-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 0;
  border-bottom: 1px dashed #f0f0f0;
}

.item-name {
  width: 320px;
  font-size: 13px;
}
</style>
