<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h2 class="page-title"><ScheduleOutlined /> 作业管理</h2>
        <div class="page-subtitle">
          展示我名下的所有作业子任务（PDF 3.6）　·　当前数据权限：{{ store.dataScope }}
        </div>
      </div>
      <a-space>
        <a-radio-group v-model:value="query.status" button-style="solid" size="small" @change="search">
          <a-radio-button :value="undefined">全部</a-radio-button>
          <a-radio-button value="待完成">待完成</a-radio-button>
          <a-radio-button value="巡检中">巡检中</a-radio-button>
          <a-radio-button value="已完成">已完成</a-radio-button>
        </a-radio-group>
        <a-button :loading="loading" @click="load">
          <template #icon><ReloadOutlined /></template>
          刷新
        </a-button>
      </a-space>
    </div>

    <div class="filter-bar">
      <a-form layout="inline">
        <a-form-item label="模糊查询">
          <a-input
            v-model:value="query.keyword"
            placeholder="工单编号 / 名称 / 站点"
            style="width: 240px"
            allow-clear
            @press-enter="search"
          >
            <template #prefix><SearchOutlined /></template>
          </a-input>
        </a-form-item>
        <a-form-item label="任务类型">
          <a-select v-model:value="query.order_type" style="width: 130px" allow-clear placeholder="全部">
            <a-select-option v-for="t in ORDER_TYPES" :key="t" :value="t">{{ t }}</a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item>
          <a-space>
            <a-button type="primary" @click="search">查询</a-button>
            <a-button @click="reset">重置</a-button>
            <a-checkbox v-model:checked="query.scope_all" @change="search">
              查看全部人员（管理员）
            </a-checkbox>
          </a-space>
        </a-form-item>
      </a-form>
    </div>

    <!-- ---------------- 任务卡片 ---------------- -->
    <a-spin :spinning="loading">
      <a-empty v-if="!rows.length" description="暂无作业任务" />
      <a-row v-else :gutter="[14, 14]">
        <a-col v-for="t in rows" :key="t.id" :xs="24" :sm="12" :lg="8" :xl="6">
          <div class="task-card">
            <div class="task-head">
              <a-tag :color="typeColor(t.order_type)">{{ t.order_type }}</a-tag>
              <a-tag :color="subtaskColor(t.status)">{{ t.status }}</a-tag>
              <span class="task-seq">#{{ t.sequence }}</span>
            </div>

            <div class="task-title">{{ t.order_name || '未命名工单' }}</div>
            <div class="task-no mono">{{ t.order_no }}</div>

            <div class="task-line">
              <EnvironmentOutlined /> {{ t.station_name || '-' }}
            </div>
            <div class="task-line">
              <CalendarOutlined /> {{ t.plan_date || '未排期' }}
              <span v-if="t.plan_time_window" class="text-muted">　{{ t.plan_time_window }}</span>
            </div>
            <div class="task-line">
              <UserOutlined /> {{ t.assignee_name || '未分配' }}
            </div>
            <div v-if="t.pile_asset_code" class="task-line">
              <ThunderboltOutlined /> {{ t.pile_asset_code }}
            </div>
            <div v-if="t.item_summary" class="task-summary">{{ t.item_summary }}</div>

            <div class="task-foot">
              <a-button
                type="primary"
                size="small"
                block
                :disabled="t.status === '已完成' || t.status === '已取消'"
                @click="goInspect(t)"
              >
                {{ t.status === '已完成' ? '已完成' : '去巡检录入' }}
              </a-button>
            </div>
          </div>
        </a-col>
      </a-row>
    </a-spin>

    <div style="text-align: right; margin-top: 16px">
      <a-pagination
        v-model:current="query.page"
        v-model:page-size="query.page_size"
        :total="total"
        show-size-changer
        :show-total="(t) => `共 ${t} 条`"
        @change="load"
      />
    </div>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  CalendarOutlined,
  EnvironmentOutlined,
  ReloadOutlined,
  ScheduleOutlined,
  SearchOutlined,
  ThunderboltOutlined,
  UserOutlined,
} from '@ant-design/icons-vue'
import { workOrderApi } from '@/api'
import { useUserStore } from '@/stores/user'

const router = useRouter()
const store = useUserStore()

const ORDER_TYPES = ['巡视', '特巡', '消缺', '设备检查', '其他']

const loading = ref(false)
const rows = ref([])
const total = ref(0)
const query = reactive({
  keyword: '',
  status: undefined,
  order_type: undefined,
  scope_all: false,
  page: 1,
  page_size: 12,
})

function typeColor(t) {
  return { 巡视: 'blue', 特巡: 'purple', 消缺: 'red', 设备检查: 'cyan', 其他: 'default' }[t] || 'default'
}
function subtaskColor(s) {
  return { 待完成: 'orange', 巡检中: 'blue', 已完成: 'green', 已取消: 'default' }[s] || 'default'
}

async function load() {
  loading.value = true
  try {
    const res = await workOrderApi.mySubtasks({ ...query })
    rows.value = res.data?.items || []
    total.value = res.data?.meta?.total || 0
  } finally {
    loading.value = false
  }
}

function search() {
  query.page = 1
  load()
}

function reset() {
  Object.assign(query, { keyword: '', status: undefined, order_type: undefined, page: 1 })
  load()
}

/** 跳转到所属工单详情并打开巡检录入 */
function goInspect(task) {
  router.push(`/work-orders/${task.work_order_id}`)
}

onMounted(load)
</script>

<style scoped>
.task-card {
  background: #fff;
  border: 1px solid #e8e8e8;
  border-radius: 10px;
  padding: 14px 16px;
  height: 100%;
  display: flex;
  flex-direction: column;
  transition: all 0.2s;
}

.task-card:hover {
  border-color: #2f6fb5;
  box-shadow: 0 4px 14px rgba(47, 111, 181, 0.13);
  transform: translateY(-2px);
}

.task-head {
  display: flex;
  align-items: center;
  gap: 5px;
  margin-bottom: 10px;
}

.task-seq {
  margin-left: auto;
  color: #a0a6ad;
  font-size: 12px;
}

.task-title {
  font-size: 14px;
  font-weight: 600;
  line-height: 1.5;
  margin-bottom: 3px;
}

.task-no {
  font-size: 11px;
  color: #a0a6ad;
  margin-bottom: 10px;
}

.task-line {
  font-size: 12px;
  color: #646a73;
  line-height: 2;
}

.task-summary {
  margin-top: 8px;
  font-size: 12px;
  color: #52c41a;
  background: #f6ffed;
  border-radius: 4px;
  padding: 4px 8px;
}

.task-foot {
  margin-top: auto;
  padding-top: 12px;
}
</style>
