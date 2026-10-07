<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h2 class="page-title">
          <BellOutlined /> 消息中心
          <a-badge v-if="unread" :count="unread" :overflow-count="99" />
        </h2>
        <div class="page-subtitle">消息卡片 · 类型区分 · 未读小红点 · 消息详情（PDF 3.8）</div>
      </div>
      <a-space>
        <a-button :disabled="!unread" @click="readAll">
          <template #icon><CheckOutlined /></template>
          全部已读
        </a-button>
        <a-button :loading="loading" @click="load">
          <template #icon><ReloadOutlined /></template>
          刷新
        </a-button>
      </a-space>
    </div>

    <!-- ---------------- 消息类型区分 ---------------- -->
    <a-row :gutter="[12, 12]">
      <a-col v-for="t in typeStats" :key="t.type" :xs="12" :sm="8" :md="6" :lg="4">
        <div
          class="type-card"
          :class="{ active: query.msg_type === t.type }"
          @click="toggleType(t.type)"
        >
          <div class="type-name">{{ t.type }}</div>
          <div class="type-count">
            {{ t.total }}
            <span v-if="t.unread" class="type-unread">{{ t.unread }} 未读</span>
          </div>
        </div>
      </a-col>
    </a-row>

    <!-- ---------------- 筛选 ---------------- -->
    <div class="filter-bar" style="margin-top: 14px">
      <a-form layout="inline">
        <a-form-item label="关键词">
          <a-input
            v-model:value="query.keyword"
            placeholder="消息标题"
            style="width: 220px"
            allow-clear
            @press-enter="search"
          >
            <template #prefix><SearchOutlined /></template>
          </a-input>
        </a-form-item>
        <a-form-item label="阅读状态">
          <a-select v-model:value="query.is_read" style="width: 120px" allow-clear placeholder="全部">
            <a-select-option :value="false">未读</a-select-option>
            <a-select-option :value="true">已读</a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item>
          <a-space>
            <a-button type="primary" @click="search">查询</a-button>
            <a-button @click="reset">重置</a-button>
          </a-space>
        </a-form-item>
      </a-form>
    </div>

    <!-- ---------------- 消息卡片 ---------------- -->
    <a-spin :spinning="loading">
      <a-empty v-if="!rows.length" description="暂无消息" />
      <a-list v-else :data-source="rows" item-layout="vertical">
        <template #renderItem="{ item }">
          <a-list-item class="msg-item" @click="openDetail(item)">
            <div class="msg-row">
              <a-badge :dot="!item.is_read">
                <a-tag :color="msgColor(item.msg_type)">{{ item.msg_type }}</a-tag>
              </a-badge>
              <div class="msg-main">
                <div class="msg-title" :class="{ unread: !item.is_read }">{{ item.title }}</div>
                <div class="msg-content">{{ item.content || '-' }}</div>
              </div>
              <div class="msg-time">{{ fmt(item.created_at) }}</div>
            </div>
          </a-list-item>
        </template>
      </a-list>

      <div style="text-align: right; margin-top: 14px">
        <a-pagination
          v-model:current="query.page"
          v-model:page-size="query.page_size"
          :total="total"
          show-size-changer
          :show-total="(t) => `共 ${t} 条`"
          @change="load"
        />
      </div>
    </a-spin>

    <!-- ---------------- 消息详情 ---------------- -->
    <a-modal v-model:open="detailOpen" title="消息详情" :footer="null" width="620px">
      <a-descriptions :column="1" bordered size="small">
        <a-descriptions-item label="消息类型">
          <a-tag :color="msgColor(current.msg_type)">{{ current.msg_type }}</a-tag>
        </a-descriptions-item>
        <a-descriptions-item label="标题">{{ current.title }}</a-descriptions-item>
        <a-descriptions-item label="内容">{{ current.content || '-' }}</a-descriptions-item>
        <a-descriptions-item label="时间">{{ fmt(current.created_at) }}</a-descriptions-item>
      </a-descriptions>

      <template v-if="detailRows.length">
        <a-divider style="margin: 16px 0 10px">工单详情字段</a-divider>
        <a-descriptions :column="2" bordered size="small">
          <a-descriptions-item v-for="row in detailRows" :key="row.label" :label="row.label">
            {{ row.value ?? '-' }}
          </a-descriptions-item>
        </a-descriptions>
      </template>

      <div style="margin-top: 18px; text-align: right">
        <a-space>
          <a-button v-if="current.work_order_id" type="primary" @click="goOrder">
            查看工单
          </a-button>
          <a-button v-if="current.fault_id" @click="goFault">查看故障</a-button>
          <a-button v-if="current.report_id" @click="goReport">查看报告</a-button>
        </a-space>
      </div>
    </a-modal>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  BellOutlined,
  CheckOutlined,
  ReloadOutlined,
  SearchOutlined,
} from '@ant-design/icons-vue'
import dayjs from 'dayjs'
import { messageApi } from '@/api'

const router = useRouter()

const loading = ref(false)
const rows = ref([])
const total = ref(0)
const unread = ref(0)
const typeStats = ref([])

const query = reactive({
  keyword: '',
  msg_type: undefined,
  is_read: undefined,
  page: 1,
  page_size: 15,
})

const detailOpen = ref(false)
const current = ref({})

const detailRows = computed(() => {
  const d = current.value?.detail
  if (!d || typeof d !== 'object') return []
  return Object.entries(d).map(([label, value]) => ({ label, value }))
})

function msgColor(type) {
  return (
    {
      工单退回提醒: 'red',
      紧急工单提醒: 'orange',
      逾期工单提醒: 'volcano',
      工单取消提醒: 'default',
      工单下发提醒: 'blue',
      故障待核查提醒: 'gold',
      报告生成提醒: 'purple',
      系统消息: 'default',
    }[type] || 'default'
  )
}

function fmt(v) {
  return v ? dayjs(v).format('YYYY-MM-DD HH:mm') : '-'
}

async function load() {
  loading.value = true
  try {
    const [listRes, typeRes] = await Promise.all([
      messageApi.list({ ...query }),
      messageApi.types(),
    ])
    rows.value = listRes.data?.items || []
    total.value = listRes.data?.meta?.total || 0
    unread.value = listRes.data?.unread_count || 0
    typeStats.value = (typeRes.data || []).filter((t) => t.total > 0)
  } finally {
    loading.value = false
  }
}

function search() {
  query.page = 1
  load()
}

function reset() {
  Object.assign(query, { keyword: '', msg_type: undefined, is_read: undefined, page: 1 })
  load()
}

function toggleType(type) {
  query.msg_type = query.msg_type === type ? undefined : type
  search()
}

async function openDetail(item) {
  current.value = item
  detailOpen.value = true
  if (!item.is_read) {
    await messageApi.read(item.id)
    item.is_read = true
    unread.value = Math.max(0, unread.value - 1)
  }
}

async function readAll() {
  await messageApi.readAll()
  unread.value = 0
  load()
}

function goOrder() {
  router.push(`/work-orders/${current.value.work_order_id}`)
  detailOpen.value = false
}
function goFault() {
  router.push(`/faults/${current.value.fault_id}`)
  detailOpen.value = false
}
function goReport() {
  router.push(`/reports/${current.value.report_id}`)
  detailOpen.value = false
}

onMounted(load)
</script>

<style scoped>
.type-card {
  background: #fff;
  border: 1px solid #e8e8e8;
  border-radius: 8px;
  padding: 10px 12px;
  cursor: pointer;
  transition: all 0.2s;
}

.type-card:hover,
.type-card.active {
  border-color: #2f6fb5;
  background: #f6f9ff;
}

.type-name {
  font-size: 12px;
  color: #646a73;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.type-count {
  font-size: 18px;
  font-weight: 600;
  margin-top: 4px;
}

.type-unread {
  font-size: 11px;
  color: #f5222d;
  font-weight: 400;
  margin-left: 6px;
}

.msg-item {
  cursor: pointer;
  border-radius: 8px;
  padding: 12px 14px !important;
}

.msg-item:hover {
  background: #fafbfc;
}

.msg-row {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  width: 100%;
}

.msg-main {
  flex: 1;
  min-width: 0;
}

.msg-title {
  font-size: 14px;
  color: #646a73;
  margin-bottom: 4px;
}

.msg-title.unread {
  font-weight: 600;
  color: #1f2329;
}

.msg-content {
  font-size: 12px;
  color: #8c8c8c;
  display: -webkit-box;
  -webkit-line-clamp: 1;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.msg-time {
  font-size: 12px;
  color: #a0a6ad;
  white-space: nowrap;
}
</style>
