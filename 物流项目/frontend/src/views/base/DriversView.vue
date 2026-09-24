<script setup>
/**
 * 司机管理。
 *
 * ★ 司机的班次（上午班/下午班/全天）与车辆绑定后，
 *   会限制该车当天能跑的趟次时段：上午班司机开不了下午趟。
 *   status 为 leave（请假）时，该司机绑定的车辆当天视为不可出勤。
 */
import { computed, onMounted, ref } from 'vue'
import { Plus, Refresh } from '@element-plus/icons-vue'
import * as api from '@/api'
import { useCrud } from '@/utils/crud'
import {
  driverShift,
  driverStatus,
  DRIVER_SHIFT_OPTIONS,
  DRIVER_STATUS_OPTIONS,
} from '@/utils/enums'

const formRef = ref()

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
    list: api.fetchDrivers,
    create: api.createDriver,
    update: api.updateDriver,
    remove: api.deleteDriver,
  },
  {
    formRef,
    label: '司机',
    blank: () => ({
      code: '',
      name: '',
      phone: '',
      shift: 'FULL',
      status: 'available',
      remark: '',
    }),
    toForm: (row) => ({
      // ★ code 编辑时只读但校验必填，必须回填（详见 StoresView 的说明）
      code: row.code,
      name: row.name,
      phone: row.phone,
      shift: row.shift,
      status: row.status,
      remark: row.remark,
    }),
    nameOf: (row) => `${row.code} ${row.name}`,
  },
)

const rules = {
  code: [
    { required: true, message: '请输入工号', trigger: 'blur' },
    { pattern: /^[A-Za-z0-9_-]+$/, message: '只能用字母、数字、下划线、连字符', trigger: 'blur' },
  ],
  name: [{ required: true, message: '请输入姓名', trigger: 'blur' }],
}

/** 可出勤统计 */
const stats = computed(() => {
  const base = { available: 0, leave: 0, offline: 0 }
  for (const d of rows.value) {
    if (base[d.status] !== undefined) base[d.status] += 1
  }
  return base
})

const filterStatus = ref('')
const filtered = computed(() =>
  rows.value.filter((d) => (filterStatus.value ? d.status === filterStatus.value : true)),
)

onMounted(load)
</script>

<template>
  <div class="page-container">
    <div class="page-header">
      <div>
        <h2 class="page-title">司机管理</h2>
        <p class="page-desc">
          司机的班次决定其绑定车辆能跑的时段（上午班司机开不了下午趟）；
          请假状态下该车当天视为不可出勤。写操作需要
          <code class="perm-code">drivers:manage</code>。
        </p>
      </div>
      <div class="actions">
        <el-select v-model="filterStatus" placeholder="全部状态" clearable style="width: 130px">
          <el-option
            v-for="o in DRIVER_STATUS_OPTIONS"
            :key="o.value"
            :label="o.label"
            :value="o.value"
          />
        </el-select>
        <el-button :icon="Refresh" @click="load">刷新</el-button>
        <el-button
          v-permission="'drivers:manage'"
          type="primary"
          :icon="Plus"
          @click="openCreate"
        >
          新建司机
        </el-button>
      </div>
    </div>

    <el-row :gutter="16" class="mb">
      <el-col :xs="8" :sm="8">
        <el-card shadow="never" class="stat">
          <div class="stat-label">可出勤</div>
          <div class="stat-value ok">{{ stats.available }}</div>
        </el-card>
      </el-col>
      <el-col :xs="8" :sm="8">
        <el-card shadow="never" class="stat">
          <div class="stat-label">请假</div>
          <div class="stat-value warn">{{ stats.leave }}</div>
        </el-card>
      </el-col>
      <el-col :xs="8" :sm="8">
        <el-card shadow="never" class="stat">
          <div class="stat-label">停用</div>
          <div class="stat-value muted-value">{{ stats.offline }}</div>
        </el-card>
      </el-col>
    </el-row>

    <el-card shadow="never">
      <el-table v-loading="loading" :data="filtered" stripe>
        <el-table-column prop="code" label="工号" width="100">
          <template #default="{ row }">
            <span class="perm-code">{{ row.code }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="name" label="姓名" width="120" />
        <el-table-column prop="phone" label="电话" width="140" />
        <el-table-column label="班次" width="110">
          <template #default="{ row }">
            <el-tag :type="driverShift(row.shift).type" size="small" effect="plain">
              {{ driverShift(row.shift).text }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tag :type="driverStatus(row.status).type" size="small">
              {{ driverStatus(row.status).text }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="remark" label="备注" min-width="180" show-overflow-tooltip />
        <el-table-column label="操作" width="120" fixed="right">
          <template #default="{ row }">
            <el-button
              v-permission="'drivers:manage'"
              size="small"
              type="primary"
              link
              @click="openEdit(row)"
            >
              编辑
            </el-button>
            <el-button
              v-permission="'drivers:manage'"
              size="small"
              type="danger"
              link
              @click="confirmRemove(row, '若该司机仍绑定车辆，删除会被拒绝。')"
            >
              删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!loading && !filtered.length" description="没有匹配的司机" />
    </el-card>

    <el-dialog v-model="dialogVisible" :title="dialogTitle" width="500px">
      <el-form ref="formRef" :model="form" :rules="rules" label-width="90px">
        <el-form-item label="工号" prop="code">
          <el-input v-model="form.code" :disabled="isEditing" placeholder="例如 D009" />
        </el-form-item>
        <el-form-item label="姓名" prop="name">
          <el-input v-model="form.name" />
        </el-form-item>
        <el-form-item label="电话">
          <el-input v-model="form.phone" />
        </el-form-item>
        <el-form-item label="班次">
          <el-select v-model="form.shift" style="width: 100%">
            <el-option
              v-for="o in DRIVER_SHIFT_OPTIONS"
              :key="o.value"
              :label="o.label"
              :value="o.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="form.status" style="width: 100%">
            <el-option
              v-for="o in DRIVER_STATUS_OPTIONS"
              :key="o.value"
              :label="o.label"
              :value="o.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.remark" type="textarea" :rows="2" />
        </el-form-item>
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

.mb {
  margin-bottom: 16px;
}

.stat {
  text-align: center;
}

.stat-label {
  font-size: 13px;
  color: #909399;
}

.stat-value {
  font-size: 24px;
  font-weight: 600;
}

.stat-value.ok {
  color: #67c23a;
}

.stat-value.warn {
  color: #e6a23c;
}

.stat-value.muted-value {
  color: #909399;
}
</style>
