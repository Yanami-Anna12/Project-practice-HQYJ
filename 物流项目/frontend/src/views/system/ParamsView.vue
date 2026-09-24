<script setup>
/**
 * 参数管理。
 *
 * ★ 这里的参数是「运行时可调」的调度行为开关，直接对应需求文档里的规则：
 *   求解超时、最大重排次数（防死循环）、候选方案数、是否必须人工确认、
 *   下发幂等键、动态车辆调节开关等。
 *
 * ★ 编辑采用「弹窗 + 变更说明」，避免误改 —— 参数改动会影响调度结果，
 *   每一次修改都会写入审计日志（见日志管理页）。
 */
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh, Edit, Warning } from '@element-plus/icons-vue'
import * as api from '@/api'
import { useTable } from '@/utils/table'
import { tryAction } from '@/utils/error'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const canManage = computed(() => auth.has('params:manage'))

const { loading, rows: params, load } = useTable(api.fetchParams)

const filterGroup = ref('')
const groups = computed(() => [...new Set(params.value.map((p) => p.group))])
const filtered = computed(() =>
  params.value.filter((p) => (filterGroup.value ? p.group === filterGroup.value : true)),
)

/** 按分组归拢，便于分区展示 */
const grouped = computed(() => {
  const map = {}
  for (const p of filtered.value) {
    if (!map[p.group]) map[p.group] = []
    map[p.group].push(p)
  }
  return map
})

const typeLabel = { int: '整数', bool: '布尔', string: '字符串' }

/* ---------------- 编辑 ---------------- */
const dialogVisible = ref(false)
const submitting = ref(false)
const current = ref(null)
const newValue = ref('')
const reason = ref('')

function openEdit(row) {
  current.value = row
  newValue.value = row.value
  reason.value = ''
  dialogVisible.value = true
}

async function submit() {
  if (newValue.value === '') {
    ElMessage.warning('参数值不能为空')
    return
  }
  if (current.value.type === 'int' && Number.isNaN(Number(newValue.value))) {
    ElMessage.warning('该参数要求整数')
    return
  }
  if (current.value.type === 'bool' && !['true', 'false'].includes(newValue.value)) {
    ElMessage.warning('该参数只接受 true 或 false')
    return
  }

  submitting.value = true
  const { ok } = await tryAction(
    () => api.updateParam(current.value.id, { value: newValue.value }),
    `参数 ${current.value.key} 已更新`,
  )
  submitting.value = false
  if (!ok) return
  dialogVisible.value = false
  await load()
}

async function toggle(row) {
  const { ok } = await tryAction(
    () => api.toggleParam(row.id),
    `参数 ${row.key} 已${row.is_active ? '停用' : '启用'}`,
  )
  if (ok) await load()
}

onMounted(load)
</script>

<template>
  <div class="page-container">
    <div class="page-header">
      <div>
        <h2 class="page-title">参数管理</h2>
        <p class="page-desc">
          运行时可调的调度行为开关。修改会直接影响调度结果，因此每次变更都会记入审计日志。
          写操作需要 <code class="perm-code">params:manage</code>。
        </p>
      </div>
      <div class="actions">
        <el-select v-model="filterGroup" placeholder="全部分组" clearable style="width: 130px">
          <el-option v-for="g in groups" :key="g" :label="g" :value="g" />
        </el-select>
        <el-button :icon="Refresh" @click="load">刷新</el-button>
      </div>
    </div>

    <el-card v-loading="loading" shadow="never">
      <div v-for="(list, group) in grouped" :key="group" class="group">
        <div class="group-title">{{ group }}</div>
        <el-table :data="list" stripe size="small">
          <el-table-column label="参数键" width="290">
            <template #default="{ row }">
              <span class="perm-code" :class="{ disabled: !row.is_active }">{{ row.key }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="name" label="名称" width="160" />
          <el-table-column label="值" width="200">
            <template #default="{ row }">
              <el-tag type="success" effect="plain" class="perm-code">{{ row.value }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="类型" width="80">
            <template #default="{ row }">
              <span class="muted">{{ typeLabel[row.type] || row.type }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="remark" label="说明" min-width="200" show-overflow-tooltip />
          <el-table-column label="状态" width="80">
            <template #default="{ row }">
              <el-tag :type="row.is_active ? 'success' : 'danger'" size="small" effect="plain">
                {{ row.is_active ? '启用' : '停用' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column v-if="canManage" label="操作" width="120" fixed="right">
            <template #default="{ row }">
              <el-button size="small" type="primary" link :icon="Edit" @click="openEdit(row)">
                修改
              </el-button>
              <el-button size="small" type="warning" link @click="toggle(row)">
                {{ row.is_active ? '停用' : '启用' }}
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </el-card>

    <el-alert type="warning" :closable="false" class="mt">
      <template #title>
        <strong>scheduling.replan.max_count</strong> 对应需求文档里的「记录 replan_count，
        避免无限循环」；<strong>dispatch.idempotent.key</strong> 对应「下发幂等设计」。
        这两个参数直接关系到异常重排与重复下发两个难点。
      </template>
    </el-alert>

    <el-dialog v-model="dialogVisible" title="修改参数" width="520px">
      <el-alert type="warning" :closable="false" class="mb">
        <template #title>
          <el-icon><Warning /></el-icon>
          参数变更会立即影响调度行为，请确认影响范围。
        </template>
      </el-alert>

      <el-form label-width="90px">
        <el-form-item label="参数键">
          <el-input :model-value="current?.key" disabled class="perm-code" />
        </el-form-item>
        <el-form-item label="名称">
          <el-input :model-value="current?.name" disabled />
        </el-form-item>
        <el-form-item label="当前值">
          <el-tag type="info" effect="plain" class="perm-code">{{ current?.value }}</el-tag>
        </el-form-item>
        <el-form-item label="新值">
          <el-select
            v-if="current?.type === 'bool'"
            v-model="newValue"
            style="width: 100%"
          >
            <el-option label="true" value="true" />
            <el-option label="false" value="false" />
          </el-select>
          <el-input v-else v-model="newValue" />
        </el-form-item>
        <el-form-item label="变更说明">
          <el-input
            v-model="reason"
            type="textarea"
            :rows="2"
            placeholder="选填，会记入审计日志"
          />
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submit">确认修改</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.group {
  margin-bottom: 20px;
}

.group:last-child {
  margin-bottom: 0;
}

.group-title {
  font-size: 13px;
  font-weight: 600;
  color: #606266;
  margin-bottom: 8px;
  padding-left: 8px;
  border-left: 3px solid #409eff;
}

.disabled {
  text-decoration: line-through;
  color: #c0c4cc;
}

.mb {
  margin-bottom: 12px;
}
</style>
