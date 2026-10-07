<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h2 class="page-title"><BookOutlined /> 知识库 RAG</h2>
        <div class="page-subtitle">
          设备手册 / SOP / 故障案例入库并切分向量化　·　检索增强问答返回命中依据（PDF 4.7）
        </div>
      </div>
      <a-space>
        <a-button :loading="listLoading" @click="loadDocs">
          <template #icon><ReloadOutlined /></template>
          刷新
        </a-button>
        <a-button type="primary" @click="openCreate">
          <template #icon><PlusOutlined /></template>
          新增文档
        </a-button>
      </a-space>
    </div>

    <!-- ---------------- 分类统计 ---------------- -->
    <a-row :gutter="[14, 14]">
      <a-col :xs="12" :sm="8" :md="6" :lg="4">
        <StatCard label="文档片段总数" :value="total" tone="primary" :icon="BookOutlined" />
      </a-col>
      <a-col v-for="c in categories" :key="c.category" :xs="12" :sm="8" :md="6" :lg="4">
        <StatCard
          :label="c.category"
          :value="c.count"
          :icon="TagsOutlined"
          :tone="categoryTone(c.category)"
        />
      </a-col>
    </a-row>

    <a-row :gutter="[14, 14]" style="margin-top: 14px">
      <!-- ================================================ 文档列表 -->
      <a-col :xs="24" :xl="14">
        <a-card size="small" :bordered="false" title="知识库文档">
          <template #extra>
            <a-space>
              <a-tag color="blue">共 {{ total }} 条片段</a-tag>
            </a-space>
          </template>

          <div class="filter-bar" style="margin-bottom: 12px">
            <a-form layout="inline" :model="query">
              <a-form-item label="分类">
                <a-select
                  v-model:value="query.category"
                  style="width: 150px"
                  allow-clear
                  placeholder="全部分类"
                  :options="categoryOptions"
                  @change="search"
                />
              </a-form-item>
              <a-form-item label="标题">
                <a-input
                  v-model:value="query.keyword"
                  placeholder="标题模糊查询"
                  style="width: 200px"
                  allow-clear
                  @press-enter="search"
                >
                  <template #prefix><SearchOutlined /></template>
                </a-input>
              </a-form-item>
              <a-form-item>
                <a-space>
                  <a-button type="primary" :loading="listLoading" @click="search">查询</a-button>
                  <a-button @click="reset">重置</a-button>
                </a-space>
              </a-form-item>
            </a-form>
          </div>

          <a-table
            :columns="columns"
            :data-source="rows"
            :loading="listLoading"
            row-key="id"
            size="small"
            :scroll="{ x: 860 }"
            :pagination="pagination"
            @change="onTableChange"
          >
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'title'">
                <div style="font-weight: 600">{{ record.title }}</div>
                <div v-if="record.summary" class="text-muted" style="font-size: 12px">
                  {{ record.summary }}
                </div>
              </template>

              <template v-else-if="column.key === 'category'">
                <a-tag :color="categoryColor(record.category)">{{ record.category || '未分类' }}</a-tag>
              </template>

              <template v-else-if="column.key === 'tags'">
                <a-tag v-for="t in parseTags(record.tags)" :key="t" color="default">{{ t }}</a-tag>
                <span v-if="!parseTags(record.tags).length" class="text-muted">-</span>
              </template>

              <template v-else-if="column.key === 'chunk_index'">
                <span class="mono">#{{ record.chunk_index ?? 0 }}</span>
                <div class="text-muted" style="font-size: 12px">{{ record.source_type || 'text' }}</div>
              </template>

              <template v-else-if="column.key === 'embedding_status'">
                <a-tag :color="record.embedding_status === 'done' ? 'green' : 'orange'">
                  {{ record.embedding_status || 'pending' }}
                </a-tag>
              </template>

              <template v-else-if="column.key === 'created_at'">
                <span class="mono" style="font-size: 12px">{{ fmtTime(record.created_at) }}</span>
              </template>
            </template>
          </a-table>
        </a-card>
      </a-col>

      <!-- ================================================ 知识库问答 -->
      <a-col :xs="24" :xl="10">
        <a-card size="small" :bordered="false" class="ai-panel" title="知识库问答（RAG）">
          <template #extra>
            <a-tag :color="askResult.llm_used ? 'green' : 'orange'">
              {{ askResult.llm_used ? 'LLM 增强' : '检索原文' }}
            </a-tag>
          </template>

          <a-textarea
            v-model:value="question"
            :rows="3"
            placeholder="例如：充电桩绝缘失效的处置流程是什么？（回车提问，Shift+回车换行）"
            :disabled="asking"
            @press-enter="onQuestionEnter"
          />

          <div class="ask-bar">
            <a-space size="small" wrap>
              <span class="text-muted" style="font-size: 12px">检索范围</span>
              <a-select
                v-model:value="askCategory"
                size="small"
                style="width: 140px"
                allow-clear
                placeholder="全部分类"
                :options="categoryOptions"
              />
              <span class="text-muted" style="font-size: 12px">召回条数</span>
              <a-input-number v-model:value="topK" size="small" :min="1" :max="20" style="width: 72px" />
              <a-button type="primary" size="small" :loading="asking" :disabled="!question.trim()" @click="ask">
                <template #icon><SendOutlined /></template>
                提问
              </a-button>
              <a-button size="small" :disabled="asking" @click="clearAsk">清空</a-button>
            </a-space>
          </div>

          <a-spin :spinning="asking" tip="正在检索知识库并生成回答…">
            <!-- 回答 -->
            <div v-if="askResult.answer" class="answer-box">
              <div class="answer-title"><RobotOutlined /> 回答</div>
              <div class="report-body" style="font-size: 13px">{{ askResult.answer }}</div>
              <div v-if="askResult.llm_error" class="text-danger" style="font-size: 12px; margin-top: 6px">
                LLM 调用异常：{{ askResult.llm_error }}
              </div>
            </div>
            <a-empty
              v-else-if="!asking"
              description="输入问题后，系统将检索知识库并返回答案与命中片段"
              style="margin: 22px 0"
            />

            <!-- 命中依据 -->
            <div v-if="askResult.references?.length" style="margin-top: 14px">
              <div class="answer-title">
                <QuestionCircleOutlined /> 命中依据（{{ askResult.references.length }} 条）
              </div>
              <div v-for="(r, idx) in askResult.references" :key="`${r.doc_id}-${idx}`" class="ref-item">
                <div class="ref-head">
                  <span class="ref-index">{{ idx + 1 }}</span>
                  <span class="ref-title">{{ r.title }}</span>
                  <a-tag :color="categoryColor(r.category)" style="margin-left: 6px">
                    {{ r.category || '未分类' }}
                  </a-tag>
                </div>
                <div class="ref-score">
                  <a-progress
                    :percent="scorePercent(r.score)"
                    size="small"
                    :stroke-color="scoreColor(r.score)"
                    :format="() => `相关度 ${scoreText(r.score)}`"
                  />
                </div>
              </div>
            </div>
          </a-spin>
        </a-card>
      </a-col>
    </a-row>

    <!-- ---------------- 新增文档 ---------------- -->
    <a-modal
      v-model:open="createOpen"
      title="新增知识库文档"
      width="720px"
      :confirm-loading="submitting"
      @ok="submitCreate"
    >
      <a-alert
        type="info"
        show-icon
        style="margin-bottom: 14px"
        message="文档提交后由后端按段落切分为多个片段并写入向量索引"
        description="建议按「设备手册 / SOP 作业指导书 / 故障案例 / 应急预案 / 技术规范」分类录入，便于检索时缩小范围。"
      />

      <a-form ref="formRef" :model="form" :rules="rules" layout="vertical">
        <a-row :gutter="16">
          <a-col :span="14">
            <a-form-item label="文档标题" name="title">
              <a-input v-model:value="form.title" placeholder="例如：直流充电桩绝缘故障处置 SOP" />
            </a-form-item>
          </a-col>
          <a-col :span="10">
            <a-form-item label="文档分类" name="category">
              <a-select
                v-model:value="form.category"
                show-search
                :options="categoryOptions"
                placeholder="选择或输入分类"
              />
            </a-form-item>
          </a-col>

          <a-col :span="24">
            <a-form-item label="标签">
              <a-select
                v-model:value="form.tags"
                mode="tags"
                placeholder="输入后回车添加标签，例如：绝缘、SOP、直流桩"
                :token-separators="[',', '，']"
              />
            </a-form-item>
          </a-col>

          <a-col :span="24">
            <a-form-item label="文档内容" name="content">
              <a-textarea
                v-model:value="form.content"
                :rows="10"
                placeholder="粘贴设备手册、SOP 步骤或故障处理记录正文，建议分段书写以提高检索准确率"
                show-count
              />
            </a-form-item>
          </a-col>
        </a-row>
      </a-form>
    </a-modal>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { message } from 'ant-design-vue'
import {
  BookOutlined,
  PlusOutlined,
  QuestionCircleOutlined,
  ReloadOutlined,
  RobotOutlined,
  SearchOutlined,
  SendOutlined,
  TagsOutlined,
} from '@ant-design/icons-vue'
import StatCard from '@/components/StatCard.vue'
import { aiApi } from '@/api'

// ================================================================ 文档列表
const listLoading = ref(false)
const rows = ref([])
const total = ref(0)
const categories = ref([])

const query = reactive({
  category: undefined,
  keyword: '',
  page: 1,
  page_size: 10,
})

const columns = [
  { title: '标题 / 摘要', key: 'title', width: 260, fixed: 'left' },
  { title: '分类', key: 'category', width: 120 },
  { title: '标签', key: 'tags', width: 160 },
  { title: '片段', key: 'chunk_index', width: 100 },
  { title: '向量状态', key: 'embedding_status', width: 110 },
  { title: '入库时间', key: 'created_at', width: 160 },
]

const pagination = computed(() => ({
  current: query.page,
  pageSize: query.page_size,
  total: total.value,
  showSizeChanger: true,
  showTotal: (t) => `共 ${t} 条`,
}))

const categoryOptions = computed(() =>
  categories.value.map((c) => ({ label: `${c.category}（${c.count}）`, value: c.category })),
)

// ---------------------------------------------------------------- 展示辅助
const CATEGORY_COLORS = {
  设备手册: 'blue',
  故障案例: 'red',
  SOP作业指导书: 'green',
  应急预案: 'orange',
  技术规范: 'purple',
  未分类: 'default',
}

function categoryColor(c) {
  if (!c) return 'default'
  if (CATEGORY_COLORS[c]) return CATEGORY_COLORS[c]
  const keys = Object.keys(CATEGORY_COLORS)
  const idx = c.split('').reduce((acc, ch) => acc + ch.charCodeAt(0), 0) % keys.length
  return CATEGORY_COLORS[keys[idx]]
}
function categoryTone(c) {
  const color = categoryColor(c)
  return { red: 'danger', green: 'success', orange: 'warning', blue: 'primary' }[color] || ''
}
function fmtTime(v) {
  if (!v) return '-'
  return String(v).replace('T', ' ').slice(0, 19)
}
/** 标签兼容字符串与数组两种返回 */
function parseTags(tags) {
  if (!tags) return []
  if (Array.isArray(tags)) return tags.filter(Boolean)
  try {
    const parsed = JSON.parse(tags)
    if (Array.isArray(parsed)) return parsed.filter(Boolean)
  } catch {
    /* 非 JSON，按分隔符切分 */
  }
  return String(tags)
    .split(/[,，、;；\s]+/)
    .filter(Boolean)
}

// ---------------------------------------------------------------- 加载数据
async function loadDocs() {
  listLoading.value = true
  try {
    const params = { page: query.page, page_size: query.page_size }
    if (query.category) params.category = query.category
    if (query.keyword) params.keyword = query.keyword
    const res = await aiApi.knowledgeList(params)
    rows.value = res.data?.items || []
    total.value = res.data?.meta?.total || 0
  } finally {
    listLoading.value = false
  }
}

async function loadCategories() {
  try {
    const res = await aiApi.knowledgeCategories()
    categories.value = res.data || []
  } catch {
    categories.value = []
  }
}

function search() {
  query.page = 1
  loadDocs()
}

function reset() {
  Object.assign(query, { category: undefined, keyword: '', page: 1 })
  loadDocs()
}

function onTableChange(pag) {
  query.page = pag.current
  query.page_size = pag.pageSize
  loadDocs()
}

// ================================================================ 新增文档
const createOpen = ref(false)
const submitting = ref(false)
const formRef = ref(null)
const form = reactive({
  title: '',
  category: '故障案例',
  content: '',
  tags: [],
})

const rules = {
  title: [{ required: true, message: '请输入文档标题' }],
  category: [{ required: true, message: '请选择文档分类' }],
  content: [
    { required: true, message: '请输入文档内容' },
    { min: 10, message: '文档内容至少 10 个字符' },
  ],
}

function openCreate() {
  Object.assign(form, { title: '', category: '故障案例', content: '', tags: [] })
  createOpen.value = true
  formRef.value?.clearValidate?.()
}

async function submitCreate() {
  try {
    await formRef.value?.validate()
  } catch {
    return
  }
  submitting.value = true
  try {
    const res = await aiApi.knowledgeCreate({
      title: form.title,
      category: form.category,
      content: form.content,
      tags: form.tags || [],
    })
    message.success(res.message || `已入库并切分为 ${res.data?.doc_count || 0} 个片段`)
    createOpen.value = false
    search()
    loadCategories()
  } catch {
    /* 拦截器已提示 */
  } finally {
    submitting.value = false
  }
}

// ================================================================ 知识库问答
const question = ref('')
const askCategory = ref(undefined)
const topK = ref(5)
const asking = ref(false)
const askResult = reactive({
  answer: '',
  references: [],
  llm_used: false,
  llm_error: '',
})

function scorePercent(score) {
  const n = Number(score)
  if (Number.isNaN(n)) return 0
  return Math.max(0, Math.min(100, Math.round(n * 100)))
}
function scoreText(score) {
  const n = Number(score)
  if (Number.isNaN(n)) return '-'
  return n.toFixed(4)
}
function scoreColor(score) {
  const p = scorePercent(score)
  if (p >= 60) return '#52c41a'
  if (p >= 30) return '#2f6fb5'
  return '#faad14'
}

async function ask() {
  const q = question.value.trim()
  if (!q) {
    message.warning('请输入问题')
    return
  }
  asking.value = true
  try {
    const payload = { question: q, top_k: topK.value || 5 }
    if (askCategory.value) payload.category = askCategory.value
    const res = await aiApi.knowledgeAsk(payload)
    const d = res.data || {}
    askResult.answer = d.answer || '（无回答）'
    askResult.references = d.references || []
    askResult.llm_used = Boolean(d.llm_used)
    askResult.llm_error = d.llm_error || ''
  } catch {
    /* 拦截器已提示 */
  } finally {
    asking.value = false
  }
}

/** 回车提问（Shift+回车换行） */
function onQuestionEnter(e) {
  if (e?.shiftKey) return
  ask()
}

function clearAsk() {
  question.value = ''
  askResult.answer = ''
  askResult.references = []
  askResult.llm_used = false
  askResult.llm_error = ''
}

onMounted(() => {
  loadDocs()
  loadCategories()
})
</script>

<style scoped>
.ask-bar {
  margin: 10px 0 12px;
}

.answer-box {
  background: #fff;
  border: 1px solid #d6e4ff;
  border-radius: 8px;
  padding: 12px 14px;
}

.answer-title {
  font-size: 13px;
  font-weight: 600;
  color: #1f4e79;
  margin-bottom: 8px;
  display: flex;
  align-items: center;
  gap: 6px;
}

.ref-item {
  background: #fff;
  border: 1px solid #e8e8e8;
  border-radius: 8px;
  padding: 8px 12px;
  margin-bottom: 8px;
}

.ref-head {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px;
}

.ref-index {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: #2f6fb5;
  color: #fff;
  font-size: 11px;
  margin-right: 4px;
}

.ref-title {
  font-weight: 600;
  font-size: 13px;
}

.ref-score {
  margin-top: 2px;
}

.ref-score :deep(.ant-progress-text) {
  font-size: 12px;
  color: #646a73;
}
</style>
