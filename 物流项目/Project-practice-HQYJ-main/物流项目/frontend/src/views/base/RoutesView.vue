<script setup>
/**
 * 线路管理。
 *
 * ★ 线路是「车辆可跑范围」的载体：需求里门店与线路是多对多，
 *   一个线路上的门店由线路本身的地形覆盖范围（terrain_scope）限定。
 *   is_restricted 表示该线路当前禁限行（例如开发区部分时段限行）。
 */
import { onMounted, ref } from 'vue'
import { Plus, Refresh } from '@element-plus/icons-vue'
import * as api from '@/api'
import { useCrud } from '@/utils/crud'
import { TERRAIN_TYPE_OPTIONS } from '@/utils/enums'

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
    list: api.fetchRoutes,
    create: api.createRoute,
    update: api.updateRoute,
    remove: api.deleteRoute,
  },
  {
    formRef,
    label: '线路',
    blank: () => ({
      code: '',
      name: '',
      terrain_scope: [],
      area: '',
      is_restricted: false,
      remark: '',
    }),
    // 后端用逗号分隔的字符串存地形范围，表单里用多选数组，两边做转换
    toForm: (row) => ({
      // ★ code 编辑时只读但校验必填，必须回填（详见 StoresView 的说明）
      code: row.code,
      name: row.name,
      terrain_scope: row.terrain_scope ? row.terrain_scope.split(',') : [],
      area: row.area,
      is_restricted: row.is_restricted,
      remark: row.remark,
    }),
    nameOf: (row) => `${row.code} ${row.name}`,
  },
)

const rules = {
  code: [
    { required: true, message: '请输入线路编码', trigger: 'blur' },
    { pattern: /^[A-Za-z0-9_-]+$/, message: '只能用字母、数字、下划线、连字符', trigger: 'blur' },
  ],
  name: [{ required: true, message: '请输入线路名称', trigger: 'blur' }],
}

/** 提交前把数组还原成后端要的逗号分隔字符串 */
function handleSubmit() {
  submit({
    terrain_scope: Array.isArray(form.value.terrain_scope)
      ? form.value.terrain_scope.join(',')
      : form.value.terrain_scope,
  })
}

onMounted(load)
</script>

<template>
  <div class="page-container">
    <div class="page-header">
      <div>
        <h2 class="page-title">线路管理</h2>
        <p class="page-desc">
          配送线路是车辆可跑范围的载体。删除仍关联门店的线路会被后端拒绝（409），
          需先到「门店线路映射」解除映射。
        </p>
      </div>
      <div class="actions">
        <el-button :icon="Refresh" @click="load">刷新</el-button>
        <el-button
          v-permission="'routes:manage'"
          type="primary"
          :icon="Plus"
          @click="openCreate"
        >
          新建线路
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
        <el-table-column prop="name" label="线路名称" width="140" />
        <el-table-column label="地形覆盖范围" min-width="200">
          <template #default="{ row }">
            <template v-if="row.terrain_scope">
              <el-tag
                v-for="t in row.terrain_scope.split(',')"
                :key="t"
                size="small"
                effect="plain"
                class="mr"
              >
                {{ (TERRAIN_TYPE_OPTIONS.find((o) => o.value === t) || {}).label || t }}
              </el-tag>
            </template>
            <span v-else class="muted">不限制</span>
          </template>
        </el-table-column>
        <el-table-column prop="area" label="区域" width="120" />
        <el-table-column label="关联门店" width="100" align="center">
          <template #default="{ row }">
            <el-tag size="small" effect="plain">{{ row.store_count }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="禁限行" width="90">
          <template #default="{ row }">
            <el-tag :type="row.is_restricted ? 'danger' : 'success'" size="small" effect="plain">
              {{ row.is_restricted ? '受限' : '正常' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="remark" label="备注" min-width="150" show-overflow-tooltip />
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
              v-permission="'routes:manage'"
              size="small"
              type="primary"
              link
              @click="openEdit(row)"
            >
              编辑
            </el-button>
            <el-button
              v-permission="'routes:manage'"
              size="small"
              type="danger"
              link
              @click="confirmRemove(row, '若该线路仍关联门店，删除会被拒绝。')"
            >
              删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!loading && !rows.length" description="暂无线路" />
    </el-card>

    <el-dialog v-model="dialogVisible" :title="dialogTitle" width="540px">
      <el-form ref="formRef" :model="form" :rules="rules" label-width="100px">
        <el-form-item label="线路编码" prop="code">
          <el-input v-model="form.code" :disabled="isEditing" placeholder="例如 R06" />
        </el-form-item>
        <el-form-item label="线路名称" prop="name">
          <el-input v-model="form.name" placeholder="例如 开发区二线" />
        </el-form-item>
        <el-form-item label="地形覆盖">
          <el-select
            v-model="form.terrain_scope"
            multiple
            placeholder="不选表示不限制"
            style="width: 100%"
          >
            <el-option
              v-for="o in TERRAIN_TYPE_OPTIONS"
              :key="o.value"
              :label="o.label"
              :value="o.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="区域">
          <el-input v-model="form.area" />
        </el-form-item>
        <el-form-item label="禁限行">
          <el-switch v-model="form.is_restricted" />
          <span class="field-note">开启后该线路在调度中会被标记为受限</span>
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.remark" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="handleSubmit">保存</el-button>
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

.field-note {
  margin-left: 8px;
  font-size: 12px;
  color: #909399;
}
</style>
