<template>
  <div class="page">
    <!-- ---------------- 页头 ---------------- -->
    <div class="page-header">
      <div>
        <h2 class="page-title"><WarningOutlined /> 故障详情与核查</h2>
        <div class="page-subtitle">
          {{ fault.fault_no || '-' }}　·　数据权限：{{ store.dataScope }}
        </div>
      </div>
      <a-space>
        <a-button @click="router.push('/faults')">
          <template #icon><ArrowLeftOutlined /></template>
          返回列表
        </a-button>
        <a-button :loading="loading" @click="loadAll">
          <template #icon><ReloadOutlined /></template>
          刷新
        </a-button>
      </a-space>
    </div>

    <a-spin :spinning="loading">
      <a-empty v-if="!fault.id && !loading" description="故障记录不存在或已被删除">
        <a-button type="primary" @click="router.push('/faults')">返回故障列表</a-button>
      </a-empty>

      <template v-else>
        <!-- ---------------- 故障信息 ---------------- -->
        <a-card size="small" :bordered="false">
          <template #title>
            <a-space>
              <a-tag :color="statusColor(fault.status)">{{ fault.status }}</a-tag>
              <a-tag :color="levelColor(fault.fault_level)">{{ fault.fault_level }}</a-tag>
              <span>{{ fault.fault_type || '未分类故障' }}</span>
            </a-space>
          </template>
          <template #extra>
            <a-space size="small">
              <a-tag v-if="slaHours" color="blue">响应时限 {{ slaHours }} 小时</a-tag>
              <a-button
                v-if="permissions.can_confirm"
                type="primary"
                size="small"
                :loading="confirming"
                @click="confirmDraft"
              >
                草稿确认上报
              </a-button>
            </a-space>
          </template>

          <a-descriptions bordered size="small" :column="{ xs: 1, sm: 2, lg: 3 }">
            <a-descriptions-item label="故障编号">
              <span class="mono">{{ fault.fault_no || '-' }}</span>
            </a-descriptions-item>
            <a-descriptions-item label="故障类型">{{ fault.fault_type || '-' }}</a-descriptions-item>
            <a-descriptions-item label="故障等级">
              <a-tag :color="levelColor(fault.fault_level)">{{ fault.fault_level || '-' }}</a-tag>
              <span v-if="fault.ai_level_suggestion" class="text-muted" style="font-size: 12px">
                AI 建议：{{ fault.ai_level_suggestion }}
              </span>
            </a-descriptions-item>
            <a-descriptions-item label="所属站点">
              {{ fault.station_name || station?.name || '-' }}
            </a-descriptions-item>
            <a-descriptions-item label="站点地址">
              {{ station?.address || '-' }}
            </a-descriptions-item>
            <a-descriptions-item label="充电桩资产码">
              <span class="mono">{{ fault.pile_asset_code || pile?.asset_code || '-' }}</span>
              <span v-if="pile?.gun_count" class="text-muted" style="font-size: 12px">
                　充电枪 {{ pile.gun_count }} 把
              </span>
            </a-descriptions-item>
            <a-descriptions-item label="上报人">
              {{ fault.reporter_name || '-' }}
            </a-descriptions-item>
            <a-descriptions-item label="上报时间">
              {{ formatTime(fault.reported_at || fault.created_at) }}
            </a-descriptions-item>
            <a-descriptions-item label="发生时间">
              {{ formatTime(fault.occurred_at) }}
            </a-descriptions-item>
          </a-descriptions>

          <div class="section-title">故障描述</div>
          <div class="text-block">{{ fault.description || '无故障描述' }}</div>

          <div class="section-title">
            <PictureOutlined /> 现场照片（{{ (fault.images || []).length }} 张）
          </div>
          <div v-if="(fault.images || []).length" class="img-gallery">
            <a-image
              v-for="(img, idx) in fault.images"
              :key="idx"
              :src="img"
              :width="112"
              :height="112"
              style="object-fit: cover; border-radius: 6px"
            />
          </div>
          <a-empty v-else :image="simpleImage" description="上传故障时未附带照片" />
        </a-card>

        <!-- ---------------- AI 诊断建议 ---------------- -->
        <a-card
          v-if="fault.ai_diagnosis"
          size="small"
          :bordered="false"
          class="ai-panel"
          style="margin-top: 14px"
        >
          <template #title>
            <ExperimentOutlined /> AI 根因分析建议（仅作参考，核查结论以人工为准）
          </template>
          <a-descriptions size="small" :column="1" bordered>
            <a-descriptions-item label="可能根因">
              {{ fault.ai_diagnosis.root_cause || fault.ai_diagnosis.summary || '-' }}
            </a-descriptions-item>
            <a-descriptions-item label="处理建议">
              {{ fault.ai_diagnosis.suggestion || fault.ai_diagnosis.advice || '-' }}
            </a-descriptions-item>
            <a-descriptions-item
              v-if="fault.ai_diagnosis.confidence !== undefined"
              label="置信度"
            >
              {{ fault.ai_diagnosis.confidence }}
            </a-descriptions-item>
          </a-descriptions>
        </a-card>

        <!-- ---------------- 故障核查录入 ---------------- -->
        <a-card size="small" :bordered="false" style="margin-top: 14px">
          <template #title><SafetyCertificateOutlined /> 故障核查录入（PDF 3.5）</template>
          <template #extra>
            <a-tag v-if="!permissions.can_verify" color="default">
              当前状态「{{ fault.status }}」不可核查
            </a-tag>
          </template>

          <a-alert
            v-if="!permissions.can_verify"
            type="info"
            show-icon
            message="仅「待核查 / 核查驳回」状态的故障可以录入核查结论"
            style="margin-bottom: 12px"
          />

          <a-form layout="vertical" :model="form">
            <a-row :gutter="12">
              <a-col :xs="24" :md="8">
                <a-form-item label="核查状态" required>
                  <a-radio-group
                    v-model:value="form.verify_status"
                    button-style="solid"
                    :disabled="formDisabled"
                  >
                    <a-radio-button value="核查通过">核查通过</a-radio-button>
                    <a-radio-button value="核查驳回">核查驳回</a-radio-button>
                  </a-radio-group>
                </a-form-item>
              </a-col>
              <a-col :xs="24" :md="8">
                <a-form-item label="核查等级">
                  <a-select
                    v-model:value="form.verify_level"
                    placeholder="默认沿用故障等级"
                    :disabled="formDisabled"
                  >
                    <a-select-option v-for="lv in dicts.levels" :key="lv" :value="lv">
                      {{ lv }}（{{ dicts.level_sla_hours?.[lv] ?? '-' }} 小时响应）
                    </a-select-option>
                  </a-select>
                </a-form-item>
              </a-col>
              <a-col :xs="24" :md="8">
                <a-form-item label="是否需要转消缺工单">
                  <a-switch
                    v-model:checked="form.need_defect_order"
                    checked-children="需要"
                    un-checked-children="不需要"
                    :disabled="formDisabled"
                  />
                  <span class="text-muted" style="font-size: 12px; margin-left: 8px">
                    核查通过且存在设备缺陷时建议转消缺
                  </span>
                </a-form-item>
              </a-col>
            </a-row>

            <a-form-item label="核查描述" required>
              <a-textarea
                v-model:value="form.verify_desc"
                :rows="4"
                :maxlength="2000"
                show-count
                :disabled="formDisabled"
                placeholder="请填写现场核查过程、测量数据与处理结果"
              />
            </a-form-item>

            <a-form-item :label="`核查照片（最多 ${MAX_IMAGES} 张）`">
              <ImageUploader
                v-model:value="form.images"
                biz-type="verify"
                :max-count="MAX_IMAGES"
              />
              <div v-if="formDisabled" class="text-muted" style="font-size: 12px">
                该故障已核查完成，照片仅供查看
              </div>
            </a-form-item>

            <a-space>
              <a-button type="primary" :loading="submitting" :disabled="formDisabled" @click="submitVerify">
                <template #icon><CheckCircleOutlined /></template>
                提交核查结论
              </a-button>
              <a-button :disabled="formDisabled" @click="resetForm">
                <template #icon><ReloadOutlined /></template>
                重置
              </a-button>
            </a-space>
          </a-form>
        </a-card>

        <!-- ---------------- 核查历史 ---------------- -->
        <a-card
          size="small"
          :bordered="false"
          :title="`核查历史（${verifications.length} 条）`"
          style="margin-top: 14px"
        >
          <a-empty v-if="!verifications.length" description="暂无核查记录" />
          <div v-else class="history-list">
            <div v-for="v in verifications" :key="v.id" class="history-item">
              <div class="history-head">
                <a-tag :color="statusColor(v.verify_status)">{{ v.verify_status }}</a-tag>
                <a-tag v-if="v.verify_level" :color="levelColor(v.verify_level)">
                  核查等级：{{ v.verify_level }}
                </a-tag>
                <a-tag v-if="v.need_defect_order" color="red">已转消缺工单</a-tag>
                <span class="text-muted" style="font-size: 12px">
                  {{ v.verifier_name || '-' }}　·　{{ formatTime(v.created_at) }}
                </span>
              </div>
              <div class="text-block">{{ v.verify_desc || '无核查描述' }}</div>
              <div v-if="(v.images || []).length" class="img-gallery" style="margin-top: 8px">
                <a-image
                  v-for="(img, idx) in v.images"
                  :key="idx"
                  :src="img"
                  :width="86"
                  :height="86"
                  style="object-fit: cover; border-radius: 6px"
                />
              </div>
            </div>
          </div>
        </a-card>
      </template>
    </a-spin>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Empty, message } from 'ant-design-vue'
import {
  ArrowLeftOutlined,
  CheckCircleOutlined,
  ExperimentOutlined,
  PictureOutlined,
  ReloadOutlined,
  SafetyCertificateOutlined,
  WarningOutlined,
} from '@ant-design/icons-vue'
import ImageUploader from '@/components/ImageUploader.vue'
import { faultApi } from '@/api'
import { useUserStore } from '@/stores/user'

const route = useRoute()
const router = useRouter()
const store = useUserStore()

const MAX_IMAGES = 6
const simpleImage = Empty.PRESENTED_IMAGE_SIMPLE

const faultId = route.params.id

const loading = ref(false)
const submitting = ref(false)
const confirming = ref(false)

const fault = ref({})
const verifications = ref([])
const station = ref(null)
const pile = ref(null)
const slaHours = ref(0)
const permissions = reactive({ can_verify: false, can_confirm: false })
const dicts = reactive({ levels: ['一般', '严重', '危急'], level_sla_hours: {} })

const form = reactive({
  verify_status: '核查通过',
  verify_level: undefined,
  verify_desc: '',
  images: [],
  need_defect_order: false,
})

/** 核查表单是否只读：仅「待核查 / 核查驳回」状态可录入 */
const formDisabled = computed(() => !permissions.can_verify)

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

function resetForm() {
  form.verify_status = '核查通过'
  form.verify_level = fault.value.fault_level
  form.verify_desc = ''
  form.images = []
  form.need_defect_order = false
}

// ---------------------------------------------------------------- 数据加载
async function loadDicts() {
  try {
    const res = await faultApi.dicts()
    const d = res.data || {}
    dicts.levels = d.levels || ['一般', '严重', '危急']
    dicts.level_sla_hours = d.level_sla_hours || {}
  } catch {
    /* 使用默认字典 */
  }
}

async function loadDetail() {
  const res = await faultApi.detail(faultId)
  const d = res.data || {}
  fault.value = d.fault || {}
  verifications.value = d.verifications || []
  station.value = d.station || null
  pile.value = d.pile || null
  slaHours.value = d.sla_hours || 0
  permissions.can_verify = Boolean(d.permissions?.can_verify)
  permissions.can_confirm = Boolean(d.permissions?.can_confirm)
  resetForm()
}

async function loadAll() {
  loading.value = true
  try {
    await loadDetail()
  } catch {
    fault.value = {}
  } finally {
    loading.value = false
  }
}

// ---------------------------------------------------------------- 多图上传
// 由 ImageUploader 组件负责：逐张调 /api/v1/uploads/images 拿真实 URL；
// 核查提交后后端会把 attachment.biz_id 回填到该核查记录。

// ---------------------------------------------------------------- 核查提交
async function submitVerify() {
  if (!form.verify_desc.trim()) {
    message.warning('请填写核查描述')
    return
  }
  submitting.value = true
  try {
    const res = await faultApi.verify(faultId, {
      verify_status: form.verify_status,
      verify_level: form.verify_level || null,
      verify_desc: form.verify_desc.trim(),
      images: [...form.images],
      need_defect_order: form.need_defect_order,
    })
    message.success(res.message || '核查结论已提交')
    await loadAll()
  } catch {
    /* 拦截器已提示 */
  } finally {
    submitting.value = false
  }
}

async function confirmDraft() {
  confirming.value = true
  try {
    const res = await faultApi.confirm(faultId)
    message.success(res.message || '已确认上报，等待核查')
    await loadAll()
  } catch {
    /* 拦截器已提示 */
  } finally {
    confirming.value = false
  }
}

onMounted(() => {
  loadDicts()
  loadAll()
})
</script>

<style scoped>
.section-title {
  font-weight: 600;
  color: #1f4e79;
  margin: 16px 0 8px;
  font-size: 14px;
}

.text-block {
  background: #fafafa;
  border: 1px solid #f0f0f0;
  border-radius: 6px;
  padding: 10px 12px;
  line-height: 1.9;
  white-space: pre-wrap;
  word-break: break-word;
}

.img-gallery {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.history-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.history-item {
  border: 1px solid #e8e8e8;
  border-radius: 8px;
  padding: 12px 14px;
  background: #fff;
}

.history-head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 8px;
}
</style>
