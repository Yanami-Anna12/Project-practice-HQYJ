<script setup>
/**
 * 门店线路映射（多对多）。
 *
 * ★ 本页是「交界门店」的产生地：一个门店挂到 >=2 条线路后，
 *   后端会把它标记为 is_intersection（交界门店），
 *   调度时需要按「交界门店归属策略」决定派给哪条线路，否则容易出现
 *   两个方案都以为对方会送、结果没人送的情况。
 *
 * ★ priority 就是「多线路门店分配优先级」：数字越小越优先派给该线路。
 */
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Plus, Refresh } from '@element-plus/icons-vue'
import * as api from '@/api'
import { withError, tryAction } from '@/utils/error'

const loading = ref(false)
const rows = ref([])
const stores = ref([])
const routes = ref([])

const dialogVisible = ref(false)
const submitting = ref(false)
const formRef = ref()
const form = ref({ store_id: null, route_id: null, priority: 100, is_primary: false })

const rules = {
  store_id: [{ required: true, message: '请选择门店', trigger: 'change' }],
  route_id: [{ required: true, message: '请选择线路', trigger: 'change' }],
}

/** 按门店分组统计，用来直观展示交界门店 */
const intersectionStores = computed(() => {
  const map = {}
  for (const m of rows.value) {
    if (!map[m.store_id]) {
      map[m.store_id] = { code: m.store_code, name: m.store_name, routes: [] }
    }
    map[m.store_id].routes.push(m.route_code)
  }
  return Object.values(map)
    .filter((s) => s.routes.length >= 2)
    .sort((a, b) => b.routes.length - a.routes.length)
})

async function load() {
  loading.value = true
  try {
    const [mappings, storeList, routeList] = await Promise.all([
      withError(() => api.fetchMappings()),
      withError(() => api.fetchStores()),
      withError(() => api.fetchRoutes()),
    ])
    rows.value = mappings || []
    stores.value = storeList || []
    routes.value = routeList || []
  } finally {
    loading.value = false
  }
}

function openCreate() {
  form.value = { store_id: null, route_id: null, priority: 100, is_primary: false }
  dialogVisible.value = true
}

/** 已选门店当前已挂的线路，用于提示与主线路选择 */
const selectedStoreRoutes = computed(() => {
  if (!form.value.store_id) return []
  return rows.value.filter((m) => m.store_id === form.value.store_id)
})

async function submit() {
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return

  submitting.value = true
  const { ok } = await tryAction(
    () => api.createMapping({ ...form.value }),
    '映射已创建',
  )
  submitting.value = false
  if (!ok) return
  dialogVisible.value = false
  await load()
}

async function removeMapping(row) {
  const { ok } = await tryAction(
    () => api.deleteMapping(row.id),
    `已解除 ${row.store_code} 与 ${row.route_code} 的映射`,
  )
  if (!ok) return
  await load()
  if (row.is_primary) {
    ElMessage.warning('删除的是主线路，请检查该线路是否还有其他门店')
  }
}

onMounted(load)
</script>

<template>
  <div class="page-container">
    <div class="page-header">
      <div>
        <h2 class="page-title">门店线路映射</h2>
        <p class="page-desc">
          门店与线路是<strong>多对多</strong>关系。一个门店挂到 2 条及以上线路时会被标记为
          <el-tag size="small" type="warning" effect="plain">交界</el-tag>，
          调度时需按归属策略决定派给哪条线路。
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
          新建映射
        </el-button>
      </div>
    </div>

    <!-- 交界门店概览 -->
    <el-card v-if="intersectionStores.length" shadow="never" class="mb">
      <template #header>
        <span class="card-title">
          交界门店（{{ intersectionStores.length }} 个）—— 归属策略需要人工确认
        </span>
      </template>
      <div class="intersections">
        <div v-for="s in intersectionStores" :key="s.code" class="intersection-item">
          <div class="is-name">
            <span class="perm-code">{{ s.code }}</span>
            {{ s.name }}
          </div>
          <div class="is-routes">
            <el-tag v-for="r in s.routes" :key="r" size="small" effect="plain" class="mr perm-code">
              {{ r }}
            </el-tag>
          </div>
        </div>
      </div>
    </el-card>

    <el-card shadow="never">
      <el-table v-loading="loading" :data="rows" stripe>
        <el-table-column prop="id" label="ID" width="70" />
        <el-table-column label="门店" min-width="180">
          <template #default="{ row }">
            <span class="perm-code">{{ row.store_code }}</span>
            <span class="ml">{{ row.store_name }}</span>
          </template>
        </el-table-column>
        <el-table-column label="线路" min-width="150">
          <template #default="{ row }">
            <span class="perm-code">{{ row.route_code }}</span>
            <span class="ml">{{ row.route_name }}</span>
          </template>
        </el-table-column>
        <el-table-column label="分配优先级" width="110" align="center">
          <template #default="{ row }">
            <el-tag size="small" effect="plain">{{ row.priority }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="主线路" width="90">
          <template #default="{ row }">
            <el-tag v-if="row.is_primary" type="success" size="small">主线</el-tag>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="100" fixed="right">
          <template #default="{ row }">
            <el-button
              v-permission="'routes:manage'"
              size="small"
              type="danger"
              link
              @click="removeMapping(row)"
            >
              解除映射
            </el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!loading && !rows.length" description="暂无映射" />
    </el-card>

    <el-alert type="info" :closable="false" class="mt">
      <template #title>
        共 {{ rows.length }} 条映射，覆盖
        {{ new Set(rows.map((r) => r.store_id)).size }} 个门店。
        优先级数字<strong>越小越优先</strong>派给该线路；主线路用于交界门店的默认归属。
      </template>
    </el-alert>

    <el-dialog v-model="dialogVisible" title="新建门店线路映射" width="520px">
      <el-form ref="formRef" :model="form" :rules="rules" label-width="100px">
        <el-form-item label="门店" prop="store_id">
          <el-select v-model="form.store_id" filterable placeholder="选择门店" style="width: 100%">
            <el-option
              v-for="s in stores"
              :key="s.id"
              :label="`${s.code} ${s.name}`"
              :value="s.id"
            />
          </el-select>
        </el-form-item>

        <el-alert
          v-if="selectedStoreRoutes.length"
          type="warning"
          :closable="false"
          class="mb"
        >
          <template #title>
            该门店已挂 {{ selectedStoreRoutes.length }} 条线路（{{
              selectedStoreRoutes.map((m) => m.route_code).join('、')
            }}），再新增一条后会成为<strong>交界门店</strong>。
          </template>
        </el-alert>

        <el-form-item label="线路" prop="route_id">
          <el-select v-model="form.route_id" filterable placeholder="选择线路" style="width: 100%">
            <el-option
              v-for="r in routes"
              :key="r.id"
              :label="`${r.code} ${r.name}`"
              :value="r.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="分配优先级">
          <el-input-number v-model="form.priority" :min="1" :max="999" />
          <span class="field-note">数字越小越优先</span>
        </el-form-item>
        <el-form-item label="设为主线路">
          <el-switch v-model="form.is_primary" />
          <span class="field-note">交界门店默认归属该线路</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submit">保存</el-button>
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

.mb {
  margin-bottom: 16px;
}

.ml {
  margin-left: 6px;
}

.intersections {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 10px;
}

.intersection-item {
  padding: 8px 12px;
  border: 1px solid #f5dab1;
  background: #fdf6ec;
  border-radius: 6px;
}

.is-name {
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 6px;
}

.is-routes {
  display: flex;
  flex-wrap: wrap;
}

.field-note {
  margin-left: 8px;
  font-size: 12px;
  color: #909399;
}
</style>
