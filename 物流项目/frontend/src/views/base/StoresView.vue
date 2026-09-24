<script setup>
/**
 * 门店管理。
 *
 * ★ 门店是整个调度业务的输入源，三个属性直接决定方案的可行性：
 *   - terrain_type    地形限制（普通/中控/严控）→ 约束「哪类车能进」
 *   - delivery_window 配送时段（上午送/下午送） → 约束「只能排上午趟或下午趟」
 *   - 线路映射（多对多）                        → 约束「哪条线路的车能跑」
 *   前两个在本页维护，第三个在「门店线路映射」页维护。
 */
import { computed, onMounted, ref } from 'vue'
import { Plus, Refresh, InfoFilled } from '@element-plus/icons-vue'
import * as api from '@/api'
import { useCrud } from '@/utils/crud'
import { terrainType, timeWindow, TERRAIN_TYPE_OPTIONS, TIME_WINDOW_OPTIONS } from '@/utils/enums'

// 模板 ref 必须声明在页面里，再交给 useCrud
const formRef = ref()

// ★ 顶层解构：Vue 只对顶层绑定做 ref 自动解包（见 utils/crud.js 的说明）
const {
  loading,
  rows,
  submitting,
  dialogVisible,
  form,
  isEditing,
  dialogTitle,
  load,
  openCreate,
  openEdit,
  submit,
  confirmRemove,
} = useCrud(
  {
    list: api.fetchStores,
    create: api.createStore,
    update: api.updateStore,
    remove: api.deleteStore,
  },
  {
    formRef,
    label: '门店',
    blank: () => ({
      code: '',
      name: '',
      terrain_type: 'normal',
      delivery_window: 'AM',
      priority: 100,
      area: '',
      address: '',
      contact: '',
      phone: '',
    }),
    toForm: (row) => ({
      // ★ code 在编辑时是禁用（只读）的，但校验规则要求它必填，
      //   所以必须回填 —— 否则保存时会被"请输入门店编码"拦住，
      //   而输入框又是灰的改不了，形成死循环。
      //   提交时后端会忽略它（StoreUpdate 里没有这个字段）。
      code: row.code,
      name: row.name,
      terrain_type: row.terrain_type,
      delivery_window: row.delivery_window,
      priority: row.priority,
      area: row.area,
      address: row.address,
      contact: row.contact,
      phone: row.phone,
    }),
    nameOf: (row) => `${row.code} ${row.name}`,
  },
)

const rules = {
  code: [
    { required: true, message: '请输入门店编码', trigger: 'blur' },
    { pattern: /^[A-Za-z0-9_-]+$/, message: '只能用字母、数字、下划线、连字符', trigger: 'blur' },
  ],
  name: [{ required: true, message: '请输入门店名称', trigger: 'blur' }],
}

/** 交界门店数量，用于页头概览 */
const intersectionCount = computed(() => rows.value.filter((s) => s.is_intersection).length)

onMounted(load)
</script>

<template>
  <div class="page-container">
    <div class="page-header">
      <div>
        <h2 class="page-title">门店管理</h2>
        <p class="page-desc">
          门店的地形与配送时段是调度的硬约束：严控地形只允许「全能去」的车辆进入，
          上午门店只能排上午趟。写操作需要 <code class="perm-code">stores:manage</code>。
        </p>
      </div>
      <div class="actions">
        <el-button :icon="Refresh" @click="load">刷新</el-button>
        <el-button
          v-permission="'stores:manage'"
          type="primary"
          :icon="Plus"
          @click="openCreate"
        >
          新建门店
        </el-button>
      </div>
    </div>

    <el-card shadow="never">
      <el-table v-loading="loading" :data="rows" stripe>
        <el-table-column prop="code" label="编码" width="90">
          <template #default="{ row }">
            <span class="perm-code">{{ row.code }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="name" label="门店名称" min-width="150">
          <template #default="{ row }">
            <span>{{ row.name }}</span>
            <el-tooltip
              v-if="row.is_intersection"
              content="该门店挂在多条线路上，属于交界门店，需要按其归属策略决定派给哪条线路"
            >
              <el-tag size="small" type="warning" effect="plain" class="ml">交界</el-tag>
            </el-tooltip>
          </template>
        </el-table-column>
        <el-table-column label="地形限制" width="100">
          <template #default="{ row }">
            <el-tag :type="terrainType(row.terrain_type).type" size="small">
              {{ terrainType(row.terrain_type).text }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="配送时段" width="100">
          <template #default="{ row }">
            <el-tag :type="timeWindow(row.delivery_window).type" size="small" effect="plain">
              {{ timeWindow(row.delivery_window).text }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="所属线路" min-width="170">
          <template #default="{ row }">
            <template v-if="row.route_codes.length">
              <el-tag
                v-for="code in row.route_codes"
                :key="code"
                size="small"
                effect="plain"
                class="mr perm-code"
              >
                {{ code }}
              </el-tag>
            </template>
            <span v-else class="muted">未映射线路</span>
          </template>
        </el-table-column>
        <el-table-column prop="area" label="配送区域" width="110" />
        <el-table-column prop="contact" label="联系人" width="90" />
        <el-table-column prop="phone" label="电话" width="120" />
        <el-table-column label="优先级" width="80" align="center">
          <template #default="{ row }">
            <span class="muted">{{ row.priority }}</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="80">
          <template #default="{ row }">
            <el-tag :type="row.is_active ? 'success' : 'info'" size="small" effect="plain">
              {{ row.is_active ? '启用' : '停用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="120" fixed="right">
          <template #default="{ row }">
            <el-button
              v-permission="'stores:manage'"
              size="small"
              type="primary"
              link
              @click="openEdit(row)"
            >
              编辑
            </el-button>
            <el-button
              v-permission="'stores:manage'"
              size="small"
              type="danger"
              link
              @click="confirmRemove(row, '若该门店仍被线路映射引用，删除会被拒绝。')"
            >
              删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!loading && !rows.length" description="暂无门店" />
    </el-card>

    <el-alert type="info" :closable="false" class="mt">
      <template #title>
        当前共 {{ rows.length }} 个门店，其中
        <strong>{{ intersectionCount }}</strong>
        个是交界门店（挂多条线路）。删除仍被线路映射引用的门店会被后端拒绝（409）。
      </template>
    </el-alert>

    <el-dialog v-model="dialogVisible" :title="dialogTitle" width="600px">
      <el-form ref="formRef" :model="form" :rules="rules" label-width="90px">
        <el-row :gutter="12">
          <el-col :span="12">
            <el-form-item label="门店编码" prop="code">
              <el-input v-model="form.code" :disabled="isEditing" placeholder="例如 S017" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="门店名称" prop="name">
              <el-input v-model="form.name" placeholder="例如 城东旗舰店" />
            </el-form-item>
          </el-col>
        </el-row>

        <el-row :gutter="12">
          <el-col :span="12">
            <el-form-item label="地形限制">
              <el-select v-model="form.terrain_type" style="width: 100%">
                <el-option
                  v-for="o in TERRAIN_TYPE_OPTIONS"
                  :key="o.value"
                  :label="o.label"
                  :value="o.value"
                />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="配送时段">
              <el-select v-model="form.delivery_window" style="width: 100%">
                <el-option
                  v-for="o in TIME_WINDOW_OPTIONS"
                  :key="o.value"
                  :label="o.label"
                  :value="o.value"
                />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>

        <el-row :gutter="12">
          <el-col :span="12">
            <el-form-item label="配送区域">
              <el-input v-model="form.area" placeholder="例如 城东片区" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="优先级">
              <el-input-number v-model="form.priority" :min="1" :max="999" />
              <span class="field-note">数字越小越优先</span>
            </el-form-item>
          </el-col>
        </el-row>

        <el-form-item label="地址">
          <el-input v-model="form.address" />
        </el-form-item>

        <el-row :gutter="12">
          <el-col :span="12">
            <el-form-item label="联系人">
              <el-input v-model="form.contact" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="电话">
              <el-input v-model="form.phone" />
            </el-form-item>
          </el-col>
        </el-row>

        <el-alert type="warning" :closable="false">
          <template #title>
            <el-icon><InfoFilled /></el-icon>
            地形与时段改动会影响后续调度方案。严控地形若没有「全能去」的车辆，
            该门店将无法被任何方案覆盖。
          </template>
        </el-alert>
      </el-form>

      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submit()">保存</el-button>
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

.ml {
  margin-left: 6px;
}

.field-note {
  margin-left: 8px;
  font-size: 12px;
  color: #909399;
}
</style>
