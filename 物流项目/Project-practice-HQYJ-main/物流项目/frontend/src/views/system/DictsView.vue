<script setup>
/**
 * 字典管理（主从结构：左侧字典类型，右侧字典项）。
 *
 * ★ 本页承载了调度业务的关键枚举：车辆类型、地形限制、车辆地形能力、
 *   配送时段、任务状态、方案编号 —— 这些值在需求文档里是业务规则的一部分
 *   （例如「四米二装载 630-800，日 2 趟」），所以放在字典里可配置。
 *
 * ★ 删除保护：字典类型下还有字典项时不允许删除。
 */
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Refresh } from '@element-plus/icons-vue'
import * as api from '@/api'
import { withError, tryAction } from '@/utils/error'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const canManage = computed(() => auth.has('dicts:manage'))

const typeLoading = ref(false)
const types = ref([])
const currentType = ref(null)

const itemLoading = ref(false)
const items = ref([])

async function loadTypes() {
  typeLoading.value = true
  try {
    const list = await withError(() => api.fetchDictTypes())
    types.value = list || []
    if (types.value.length) {
      // 保持当前选中项；若已被删除则回退到第一项
      const stillExists = types.value.find((t) => t.id === currentType.value?.id)
      await selectType(stillExists || types.value[0])
    } else {
      currentType.value = null
      items.value = []
    }
  } finally {
    typeLoading.value = false
  }
}

async function selectType(type) {
  currentType.value = type
  itemLoading.value = true
  try {
    items.value = (await withError(() => api.fetchDictItems(type.code))) || []
  } finally {
    itemLoading.value = false
  }
}

/* ---------------- 字典类型 ---------------- */
const typeDialogVisible = ref(false)
const typeSubmitting = ref(false)
const typeFormRef = ref()
const typeForm = ref({ code: '', name: '', description: '' })

const typeRules = {
  code: [
    { required: true, message: '请输入字典类型编码', trigger: 'blur' },
    { pattern: /^[a-z][a-z0-9_]*$/, message: '只能用小写字母、数字和下划线', trigger: 'blur' },
  ],
  name: [{ required: true, message: '请输入名称', trigger: 'blur' }],
}

function openCreateType() {
  typeForm.value = { code: '', name: '', description: '' }
  typeDialogVisible.value = true
}

async function submitType() {
  const valid = await typeFormRef.value.validate().catch(() => false)
  if (!valid) return
  typeSubmitting.value = true
  const { ok } = await tryAction(() => api.createDictType({ ...typeForm.value }), '字典类型已创建')
  typeSubmitting.value = false
  if (!ok) return
  typeDialogVisible.value = false
  await loadTypes()
}

async function toggleType(type) {
  const { ok } = await tryAction(
    () => api.toggleDictType(type.id),
    `字典类型 ${type.code} 已${type.is_active ? '停用' : '启用'}`,
  )
  if (ok) await loadTypes()
}

async function removeType(type) {
  try {
    await ElMessageBox.confirm(
      type.item_count > 0
        ? `字典类型 ${type.code} 下还有 ${type.item_count} 个字典项，删除会被拒绝。仍要尝试吗？`
        : `确定删除字典类型 ${type.code}？`,
      '删除确认',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  const { ok, result } = await tryAction(() => api.deleteDictType(type.id))
  if (ok) {
    ElMessage.success(`字典类型 ${result.deleted} 已删除`)
    await loadTypes()
  }
}

/* ---------------- 字典项 ---------------- */
const itemDialogVisible = ref(false)
const itemSubmitting = ref(false)
const itemFormRef = ref()
const editingItemId = ref(null)
const itemForm = ref({ label: '', value: '', sort: 1, remark: '' })

const itemRules = {
  label: [{ required: true, message: '请输入标签', trigger: 'blur' }],
  value: [{ required: true, message: '请输入值', trigger: 'blur' }],
}

function openCreateItem() {
  editingItemId.value = null
  const nextSort = items.value.length ? Math.max(...items.value.map((i) => i.sort)) + 1 : 1
  itemForm.value = { label: '', value: '', sort: nextSort, remark: '' }
  itemDialogVisible.value = true
}

function openEditItem(row) {
  editingItemId.value = row.id
  itemForm.value = { label: row.label, value: row.value, sort: row.sort, remark: row.remark || '' }
  itemDialogVisible.value = true
}

async function submitItem() {
  const valid = await itemFormRef.value.validate().catch(() => false)
  if (!valid) return
  itemSubmitting.value = true
  const { ok } = await tryAction(
    () =>
      editingItemId.value
        ? api.updateDictItem(editingItemId.value, { ...itemForm.value })
        : api.createDictItem({ type_code: currentType.value.code, ...itemForm.value }),
    editingItemId.value ? '字典项已更新' : '字典项已创建',
  )
  itemSubmitting.value = false
  if (!ok) return
  itemDialogVisible.value = false
  await selectType(currentType.value)
  await loadTypes()
}

async function removeItem(row) {
  try {
    await ElMessageBox.confirm(`确定删除字典项「${row.label}」？`, '删除确认', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  const { ok } = await tryAction(() => api.deleteDictItem(row.id))
  if (ok) {
    await selectType(currentType.value)
    await loadTypes()
  }
}

onMounted(loadTypes)
</script>

<template>
  <div class="page-container">
    <div class="page-header">
      <div>
        <h2 class="page-title">字典管理</h2>
        <p class="page-desc">
          维护系统枚举值。车辆类型、地形限制、车辆地形能力、配送时段等业务枚举都在这里配置。
          写操作需要 <code class="perm-code">dicts:manage</code>。
        </p>
      </div>
      <div class="actions">
        <el-button :icon="Refresh" @click="loadTypes">刷新</el-button>
        <el-button v-if="canManage" type="primary" :icon="Plus" @click="openCreateType">
          新建字典类型
        </el-button>
      </div>
    </div>

    <el-row :gutter="16">
      <!-- 字典类型 -->
      <el-col :xs="24" :lg="9">
        <el-card shadow="never" class="type-card">
          <template #header>
            <span class="card-title">字典类型（{{ types.length }}）</span>
          </template>
          <el-table
            v-loading="typeLoading"
            :data="types"
            highlight-current-row
            :current-row-key="currentType?.id"
            row-key="id"
            @current-change="(row) => row && selectType(row)"
          >
            <el-table-column label="类型" min-width="170">
              <template #default="{ row }">
                <div class="type-name">
                  <span :class="{ disabled: !row.is_active }">{{ row.name }}</span>
                  <el-tag v-if="!row.is_active" type="danger" size="small" effect="plain">停用</el-tag>
                </div>
                <div class="perm-code type-code">{{ row.code }}</div>
              </template>
            </el-table-column>
            <el-table-column label="项数" width="60" align="center">
              <template #default="{ row }">
                <span class="muted">{{ row.item_count }}</span>
              </template>
            </el-table-column>
            <el-table-column v-if="canManage" label="操作" width="110" align="right">
              <template #default="{ row }">
                <el-button size="small" type="warning" link @click.stop="toggleType(row)">
                  {{ row.is_active ? '停用' : '启用' }}
                </el-button>
                <el-button size="small" type="danger" link @click.stop="removeType(row)">
                  删除
                </el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>

      <!-- 字典项 -->
      <el-col :xs="24" :lg="15">
        <el-card shadow="never">
          <template #header>
            <div class="item-header">
              <span class="card-title">
                字典项
                <template v-if="currentType">
                  · {{ currentType.name }}
                  <code class="perm-code">{{ currentType.code }}</code>
                </template>
              </span>
              <el-button
                v-if="canManage && currentType"
                type="primary"
                size="small"
                :icon="Plus"
                @click="openCreateItem"
              >
                新增字典项
              </el-button>
            </div>
          </template>

          <el-alert v-if="currentType" type="info" :closable="false" class="mb">
            <template #title>{{ currentType.description }}</template>
          </el-alert>

          <el-table v-loading="itemLoading" :data="items" stripe>
            <el-table-column prop="sort" label="排序" width="70" align="center" />
            <el-table-column prop="label" label="标签" width="150" />
            <el-table-column label="值" width="130">
              <template #default="{ row }">
                <span class="perm-code">{{ row.value }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="remark" label="说明" min-width="180" show-overflow-tooltip />
            <el-table-column label="状态" width="90">
              <template #default="{ row }">
                <el-tag :type="row.is_active ? 'success' : 'danger'" size="small" effect="plain">
                  {{ row.is_active ? '启用' : '停用' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column v-if="canManage" label="操作" width="110" fixed="right">
              <template #default="{ row }">
                <el-button size="small" type="primary" link @click="openEditItem(row)">
                  编辑
                </el-button>
                <el-button size="small" type="danger" link @click="removeItem(row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
          <el-empty v-if="!itemLoading && !items.length" description="该字典类型下暂无字典项" />
        </el-card>
      </el-col>
    </el-row>

    <!-- 新建字典类型 -->
    <el-dialog v-model="typeDialogVisible" title="新建字典类型" width="480px">
      <el-form ref="typeFormRef" :model="typeForm" :rules="typeRules" label-width="90px">
        <el-form-item label="类型编码" prop="code">
          <el-input v-model="typeForm.code" placeholder="例如 delivery_area" />
        </el-form-item>
        <el-form-item label="名称" prop="name">
          <el-input v-model="typeForm.name" placeholder="例如 配送区域" />
        </el-form-item>
        <el-form-item label="说明">
          <el-input v-model="typeForm.description" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="typeDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="typeSubmitting" @click="submitType">保存</el-button>
      </template>
    </el-dialog>

    <!-- 新建 / 编辑字典项 -->
    <el-dialog
      v-model="itemDialogVisible"
      :title="editingItemId ? '编辑字典项' : '新增字典项'"
      width="480px"
    >
      <el-form ref="itemFormRef" :model="itemForm" :rules="itemRules" label-width="90px">
        <el-form-item label="所属类型">
          <el-input :model-value="currentType?.code" disabled />
        </el-form-item>
        <el-form-item label="标签" prop="label">
          <el-input v-model="itemForm.label" placeholder="例如 四米二" />
        </el-form-item>
        <el-form-item label="值" prop="value">
          <el-input v-model="itemForm.value" placeholder="例如 4.2m" />
        </el-form-item>
        <el-form-item label="排序">
          <el-input-number v-model="itemForm.sort" :min="1" :max="999" />
        </el-form-item>
        <el-form-item label="说明">
          <el-input v-model="itemForm.remark" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="itemDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="itemSubmitting" @click="submitItem">保存</el-button>
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

.card-title {
  font-weight: 600;
}

.item-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.type-card {
  margin-bottom: 16px;
}

.type-name {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
}

.type-code {
  color: #909399;
}

.disabled {
  text-decoration: line-through;
  color: #c0c4cc;
}

.mb {
  margin-bottom: 12px;
}
</style>
