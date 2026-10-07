<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h2 class="page-title"><SettingOutlined /> 参数与规则</h2>
        <div class="page-subtitle">
          系统参数热更新（PDF 3.2）　·　规则中心硬约束 / 软约束版本管理（PDF 9.3）
        </div>
      </div>
      <a-space>
        <a-button :loading="configLoading" @click="loadConfigs">
          <template #icon><ReloadOutlined /></template>
          刷新参数
        </a-button>
      </a-space>
    </div>

    <a-tabs v-model:activeKey="activeTab">
      <!-- ================================================ 系统参数 -->
      <a-tab-pane key="configs">
        <template #tab>
          <span><SettingOutlined /> 系统参数</span>
        </template>

        <div class="filter-bar">
          <a-form layout="inline">
            <a-form-item label="参数分组">
              <a-select
                v-model:value="groupFilter"
                style="width: 180px"
                allow-clear
                placeholder="全部分组"
                :options="groupFilterOptions"
                @change="loadConfigs"
              />
            </a-form-item>
            <a-form-item label="模糊查询">
              <a-input
                v-model:value="configKeyword"
                placeholder="参数名称 / 参数键"
                style="width: 220px"
                allow-clear
              >
                <template #prefix><SearchOutlined /></template>
              </a-input>
            </a-form-item>
            <a-form-item>
              <a-tag color="blue">共 {{ filteredConfigs.length }} 项</a-tag>
              <a-tag color="default">可编辑 {{ editableCount }} 项</a-tag>
            </a-form-item>
          </a-form>
        </div>

        <a-spin :spinning="configLoading">
          <a-empty v-if="!filteredConfigs.length" description="暂无系统参数" />
          <a-card
            v-for="g in groupedConfigs"
            :key="g.group"
            size="small"
            :bordered="false"
            class="group-card"
          >
            <template #title>
              <a-tag :color="groupColor(g.group)">{{ groupLabel(g.group) }}</a-tag>
              <span class="text-muted" style="font-size: 12px">{{ g.list.length }} 项参数</span>
            </template>

            <a-table
              :columns="configColumns"
              :data-source="g.list"
              row-key="config_key"
              size="small"
              :pagination="false"
            >
              <template #bodyCell="{ column, record }">
                <template v-if="column.key === 'config_name'">
                  <div style="font-weight: 600">{{ record.config_name }}</div>
                  <div class="mono text-muted" style="font-size: 12px">
                    {{ record.config_key }}
                  </div>
                </template>

                <template v-else-if="column.key === 'config_value'">
                  <template v-if="editingKey === record.config_key">
                    <a-switch
                      v-if="record.value_type === 'bool'"
                      v-model:checked="editValue"
                      checked-children="开启"
                      un-checked-children="关闭"
                    />
                    <a-input-number
                      v-else-if="record.value_type === 'int'"
                      v-model:value="editValue"
                      :min="0"
                      :step="1"
                      style="width: 130px"
                    />
                    <a-textarea
                      v-else-if="record.value_type === 'json'"
                      v-model:value="editValue"
                      :rows="3"
                      class="mono"
                      placeholder='JSON 格式，例如 ["日","周","月"]'
                    />
                    <a-input v-else v-model:value="editValue" style="width: 100%" />
                  </template>
                  <template v-else>
                    <a-tag v-if="record.value_type === 'bool'" :color="record.config_value === 'true' ? 'green' : 'default'">
                      {{ record.config_value === 'true' ? '开启' : '关闭' }}
                    </a-tag>
                    <a-tag v-else-if="record.value_type === 'int'" color="geekblue">
                      {{ record.config_value }}
                    </a-tag>
                    <span v-else class="mono value-text">{{ record.config_value }}</span>
                    <div v-if="record.description" class="text-muted" style="font-size: 12px">
                      {{ record.description }}
                    </div>
                  </template>
                </template>

                <template v-else-if="column.key === 'value_type'">
                  <a-tag :color="typeColor(record.value_type)">{{ record.value_type }}</a-tag>
                </template>

                <template v-else-if="column.key === 'updated_at'">
                  <span class="mono" style="font-size: 12px">{{ fmtTime(record.updated_at) }}</span>
                </template>

                <template v-else-if="column.key === 'action'">
                  <a-space size="small">
                    <template v-if="editingKey === record.config_key">
                      <a :class="{ disabled: savingKey === record.config_key }" @click="saveConfig(record)">
                        保存
                      </a>
                      <a @click="cancelEdit">取消</a>
                    </template>
                    <template v-else>
                      <a v-if="record.editable" @click="startEdit(record)">编辑</a>
                      <a-tooltip v-else title="只读参数，需要修改请调整后端初始化配置">
                        <span class="disabled">只读</span>
                      </a-tooltip>
                    </template>
                  </a-space>
                </template>
              </template>
            </a-table>
          </a-card>
        </a-spin>
      </a-tab-pane>

      <!-- ================================================ 规则中心 -->
      <a-tab-pane key="rules">
        <template #tab>
          <span><SafetyOutlined /> 规则中心</span>
        </template>

        <a-spin :spinning="ruleLoading">
          <!-- 当前生效规则 -->
          <a-card size="small" :bordered="false" class="group-card ai-panel">
            <template #title>
              <span style="font-weight: 600">当前生效规则版本</span>
            </template>
            <template #extra>
              <a-space>
                <a-tag color="green">{{ activeRule.version || '-' }}</a-tag>
                <a-tag color="blue">{{ activeRule.source || '规则中心' }}</a-tag>
                <a-button size="small" :loading="ruleLoading" @click="loadRules">
                  <template #icon><ReloadOutlined /></template>
                  刷新
                </a-button>
              </a-space>
            </template>

            <a-descriptions :column="2" size="small" bordered>
              <a-descriptions-item label="版本号">{{ activeRule.version || '-' }}</a-descriptions-item>
              <a-descriptions-item label="是否生效">
                <a-badge
                  :status="activeRule.is_active ? 'success' : 'default'"
                  :text="activeRule.is_active ? '生效中' : '未生效'"
                />
              </a-descriptions-item>
              <a-descriptions-item label="生效时间">
                {{ fmtTime(activeRule.effective_at) }}
              </a-descriptions-item>
              <a-descriptions-item label="规则来源">{{ activeRule.source || '-' }}</a-descriptions-item>
              <a-descriptions-item label="变更说明" :span="2">
                {{ activeRule.change_log || '（无）' }}
              </a-descriptions-item>
            </a-descriptions>

            <a-row :gutter="[14, 14]" style="margin-top: 14px">
              <a-col :xs="24" :lg="12">
                <div class="constraint-title">
                  <a-tag color="red">硬约束</a-tag>
                  <span class="text-muted" style="font-size: 12px">
                    由确定性代码保证，AI 不可违反
                  </span>
                </div>
                <div class="ai-trace">{{ prettyJson(activeRule.hard_constraints) }}</div>
              </a-col>
              <a-col :xs="24" :lg="12">
                <div class="constraint-title">
                  <a-tag color="orange">软约束</a-tag>
                  <span class="text-muted" style="font-size: 12px">
                    多方案评分的权重与上限
                  </span>
                </div>
                <div class="ai-trace">{{ prettyJson(activeRule.soft_constraints) }}</div>
              </a-col>
            </a-row>
          </a-card>

          <!-- 历史版本 -->
          <a-card size="small" :bordered="false" class="group-card" style="margin-top: 14px">
            <template #title>
              <span style="font-weight: 600">规则版本历史</span>
              <span class="text-muted" style="font-size: 12px; margin-left: 8px">
                共 {{ rules.length }} 个版本
              </span>
            </template>

            <a-table
              :columns="ruleColumns"
              :data-source="rules"
              row-key="id"
              size="small"
              :pagination="false"
            >
              <template #bodyCell="{ column, record }">
                <template v-if="column.key === 'version'">
                  <span class="mono" style="font-weight: 600">{{ record.version }}</span>
                </template>

                <template v-else-if="column.key === 'is_active'">
                  <a-tag :color="record.is_active ? 'green' : 'default'">
                    {{ record.is_active ? '生效中' : '历史版本' }}
                  </a-tag>
                </template>

                <template v-else-if="column.key === 'change_log'">
                  <span class="text-muted" style="font-size: 12px">{{ record.change_log || '-' }}</span>
                </template>

                <template v-else-if="column.key === 'effective_at'">
                  <span class="mono" style="font-size: 12px">{{ fmtTime(record.effective_at) }}</span>
                </template>

                <template v-else-if="column.key === 'created_at'">
                  <span class="mono" style="font-size: 12px">{{ fmtTime(record.created_at) }}</span>
                </template>

                <template v-else-if="column.key === 'action'">
                  <a @click="openRuleDetail(record)">查看约束</a>
                </template>
              </template>
            </a-table>
          </a-card>
        </a-spin>
      </a-tab-pane>
    </a-tabs>

    <!-- ---------------- 历史版本约束详情 ---------------- -->
    <a-modal v-model:open="ruleDetailOpen" :title="`规则版本 ${ruleDetail.version || ''}`" width="860px" :footer="null">
      <a-descriptions :column="2" size="small" bordered style="margin-bottom: 14px">
        <a-descriptions-item label="版本号">{{ ruleDetail.version || '-' }}</a-descriptions-item>
        <a-descriptions-item label="是否生效">
          {{ ruleDetail.is_active ? '生效中' : '历史版本' }}
        </a-descriptions-item>
        <a-descriptions-item label="生效时间">{{ fmtTime(ruleDetail.effective_at) }}</a-descriptions-item>
        <a-descriptions-item label="创建时间">{{ fmtTime(ruleDetail.created_at) }}</a-descriptions-item>
        <a-descriptions-item label="变更说明" :span="2">{{ ruleDetail.change_log || '（无）' }}</a-descriptions-item>
      </a-descriptions>

      <a-row :gutter="[14, 14]">
        <a-col :xs="24" :lg="12">
          <div class="constraint-title"><a-tag color="red">硬约束</a-tag></div>
          <div class="ai-trace">{{ prettyJson(ruleDetail.hard_constraints) }}</div>
        </a-col>
        <a-col :xs="24" :lg="12">
          <div class="constraint-title"><a-tag color="orange">软约束</a-tag></div>
          <div class="ai-trace">{{ prettyJson(ruleDetail.soft_constraints) }}</div>
        </a-col>
      </a-row>
    </a-modal>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { message } from 'ant-design-vue'
import {
  ReloadOutlined,
  SafetyOutlined,
  SearchOutlined,
  SettingOutlined,
} from '@ant-design/icons-vue'
import { adminApi } from '@/api'

const activeTab = ref('configs')

// ================================================================ 系统参数
const configLoading = ref(false)
const configs = ref([])
const groupFilter = ref(undefined)
const configKeyword = ref('')
const editingKey = ref('')
const savingKey = ref('')
const editValue = ref('')

const GROUP_LABEL = {
  work_order: '工单参数',
  fault: '故障参数',
  inspection: '巡检参数',
  report: '报告参数',
  ai: 'AI 参数',
  ledger: '台账参数',
}

function groupLabel(g) {
  return GROUP_LABEL[g] || g || '未分组'
}
function groupColor(g) {
  return (
    {
      work_order: 'blue',
      fault: 'red',
      inspection: 'cyan',
      report: 'purple',
      ai: 'geekblue',
      ledger: 'green',
    }[g] || 'default'
  )
}
function typeColor(t) {
  return { json: 'purple', int: 'geekblue', bool: 'green', string: 'default' }[t] || 'default'
}
function fmtTime(v) {
  if (!v) return '-'
  return String(v).replace('T', ' ').slice(0, 19)
}
function prettyJson(v) {
  if (v === null || v === undefined) return '（空）'
  if (typeof v === 'string') {
    try {
      return JSON.stringify(JSON.parse(v), null, 2)
    } catch {
      return v
    }
  }
  try {
    return JSON.stringify(v, null, 2)
  } catch {
    return String(v)
  }
}

const configColumns = [
  { title: '参数名称 / 键', key: 'config_name', width: 250 },
  { title: '参数值', key: 'config_value' },
  { title: '类型', key: 'value_type', width: 90 },
  { title: '更新时间', key: 'updated_at', width: 160 },
  { title: '操作', key: 'action', width: 130 },
]

/** 分组下拉：按后端返回的 config_group 动态生成 */
const groupFilterOptions = computed(() => {
  const groups = Array.from(new Set(configs.value.map((c) => c.config_group).filter(Boolean)))
  return groups.map((g) => ({ label: groupLabel(g), value: g }))
})

const filteredConfigs = computed(() => {
  const kw = configKeyword.value.trim().toLowerCase()
  return configs.value.filter((c) => {
    if (groupFilter.value && c.config_group !== groupFilter.value) return false
    if (!kw) return true
    return (
      (c.config_name || '').toLowerCase().includes(kw) ||
      (c.config_key || '').toLowerCase().includes(kw)
    )
  })
})

const editableCount = computed(() => filteredConfigs.value.filter((c) => c.editable).length)

/** 按 config_group 分组展示：工单 / 故障 / 巡检 / 报告 / AI / 台账 */
const groupedConfigs = computed(() => {
  const order = ['work_order', 'fault', 'inspection', 'report', 'ai', 'ledger']
  const map = new Map()
  filteredConfigs.value.forEach((c) => {
    const g = c.config_group || 'other'
    if (!map.has(g)) map.set(g, [])
    map.get(g).push(c)
  })
  return Array.from(map.entries())
    .sort((a, b) => {
      const ia = order.indexOf(a[0])
      const ib = order.indexOf(b[0])
      return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib)
    })
    .map(([group, list]) => ({ group, list }))
})

async function loadConfigs() {
  configLoading.value = true
  try {
    const res = await adminApi.configs()
    configs.value = res.data || []
  } finally {
    configLoading.value = false
  }
}

function startEdit(record) {
  editingKey.value = record.config_key
  editValue.value = record.value_type === 'bool' ? record.config_value === 'true' : record.config_value
}

function cancelEdit() {
  editingKey.value = ''
  editValue.value = ''
}

/** 行内编辑保存：PUT /admin/configs/{config_key} */
async function saveConfig(record) {
  let value = editValue.value
  if (record.value_type === 'json') {
    try {
      JSON.parse(String(value))
    } catch {
      message.warning('JSON 格式不正确，请检查后保存')
      return
    }
  }
  if (record.value_type === 'bool') value = value ? 'true' : 'false'
  if (value === null || value === undefined || value === '') {
    message.warning('参数值不能为空')
    return
  }

  savingKey.value = record.config_key
  try {
    await adminApi.updateConfig(record.config_key, { config_value: value })
    message.success(`参数「${record.config_name}」已热更新`)
    cancelEdit()
    await loadConfigs()
  } catch {
    /* 拦截器已提示 */
  } finally {
    savingKey.value = ''
  }
}

// ================================================================ 规则中心
const ruleLoading = ref(false)
const activeRule = ref({})
const rules = ref([])
const ruleDetailOpen = ref(false)
const ruleDetail = ref({})

const ruleColumns = [
  { title: '版本号', key: 'version', width: 130 },
  { title: '状态', key: 'is_active', width: 110 },
  { title: '变更说明', key: 'change_log' },
  { title: '生效时间', key: 'effective_at', width: 165 },
  { title: '创建时间', key: 'created_at', width: 165 },
  { title: '操作', key: 'action', width: 100 },
]

async function loadRules() {
  ruleLoading.value = true
  try {
    const [activeRes, listRes] = await Promise.all([adminApi.activeRule(), adminApi.rules()])
    activeRule.value = activeRes.data || {}
    rules.value = listRes.data || []
  } finally {
    ruleLoading.value = false
  }
}

function openRuleDetail(record) {
  ruleDetail.value = { ...record }
  ruleDetailOpen.value = true
}

onMounted(() => {
  loadConfigs()
  loadRules()
})
</script>

<style scoped>
.group-card {
  border-radius: 10px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
}

.group-card + .group-card {
  margin-top: 14px;
}

.constraint-title {
  margin-bottom: 8px;
  display: flex;
  align-items: center;
  gap: 6px;
}

.value-text {
  font-size: 12px;
  word-break: break-all;
}

.disabled {
  color: #bfbfbf !important;
  cursor: not-allowed;
}
</style>
