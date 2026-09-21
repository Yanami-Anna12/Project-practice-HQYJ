<script setup>
/**
 * 权限点管理（需要 users:manage，仅管理员）。
 *
 * ★ 本页是 R4「权限变更实时生效」的验证入口，也是整个系统最值得演示的一屏。
 *
 *   「实时验证」面板会做三件事：
 *     1. 用**当前登录账号自己的 Token** 请求一次受保护接口，记录状态码；
 *     2. 停用该接口所需权限点（不动 Token、不重新登录）；
 *     3. 用同一个 Token 再请求一次 —— 状态码立刻从 200 变成 403。
 *
 *   这直接证明了「鉴权时实时查库、无会话级缓存」，也就是 R4。
 *   如果实现里把权限缓存到会话或写进 Token，这一步会失败。
 */
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Refresh } from '@element-plus/icons-vue'
import * as api from '@/api'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()

const loading = ref(false)
const permissions = ref([])

const dialogVisible = ref(false)
const submitting = ref(false)
const formRef = ref()
const form = ref({ code: '', name: '', module: '' })

const rules = {
  code: [{ required: true, message: '请输入权限码', trigger: 'blur' }],
  name: [{ required: true, message: '请输入中文名', trigger: 'blur' }],
  module: [{ required: true, message: '请输入所属模块', trigger: 'blur' }],
}

// ---- R4 实时验证面板的状态 ----
const probeCode = ref('products:read')
const probePath = ref('/api/products')
const probeLog = ref([])
const probing = ref(false)

async function load() {
  loading.value = true
  try {
    permissions.value = await api.fetchPermissions()
  } finally {
    loading.value = false
  }
}

async function toggle(row) {
  const next = !row.is_active
  const actionText = next ? '启用' : '停用'
  try {
    await ElMessageBox.confirm(
      next
        ? `启用「${row.code}」后，所有持有该权限的用户下次请求即可访问。`
        : `停用「${row.code}」后，所有持有该权限的用户的**下一次请求**就会立即被拒绝（403），` +
          `无需重新登录、无需重启服务。当前有 ${row.role_count} 个角色引用它。确定停用吗？`,
      `${actionText}权限点确认`,
      { type: next ? 'info' : 'warning', confirmButtonText: actionText, cancelButtonText: '取消' },
    )
  } catch {
    return
  }

  await api.togglePermission(row.id, next)
  ElMessage.success(`已${actionText}「${row.code}」，变更即时生效`)
  await load()
  // 权限变了，刷新菜单（可能影响侧边栏可见项）
  await auth.refreshPermissions()
}

async function createPermission() {
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return
  submitting.value = true
  try {
    await api.createPermission({ ...form.value })
    ElMessage.success('权限点已创建')
    dialogVisible.value = false
    form.value = { code: '', name: '', module: '' }
    await load()
  } finally {
    submitting.value = false
  }
}

/**
 * R4 实测：用当前账号的同一个 Token，在停用权限点前后各请求一次。
 * 全程不重新登录、不刷新页面 Token。
 */
async function runProbe() {
  probing.value = true
  probeLog.value = []
  const perm = permissions.value.find((p) => p.code === probeCode.value)
  if (!perm) {
    ElMessage.error('请选择要验证的权限点')
    probing.value = false
    return
  }

  const log = (text, status, tone) => probeLog.value.push({ text, status, tone })

  try {
    // 步骤 1：停用前的基线
    let result = await api.probe(probePath.value)
    log(`① 停用前请求 ${probePath.value}`, result, result === 200 ? 'success' : 'warning')

    // 步骤 2：停用权限点
    await api.togglePermission(perm.id, false)
    log(`② 停用权限点 ${perm.code}（未重新登录、未更换 Token）`, null, 'info')

    // 步骤 3：同一个 Token 再请求
    result = await api.probe(probePath.value)
    log(`③ 停用后请求 ${probePath.value}`, result, result === 403 ? 'success' : 'danger')
    log(
      result === 403 ? '✔ 立即被拒绝 —— R4 无缓存延迟，验证通过' : '✘ 仍可访问 —— 存在权限缓存，违反 R4',
      null,
      result === 403 ? 'success' : 'danger',
    )

    // 步骤 4：恢复现场
    await api.togglePermission(perm.id, true)
    result = await api.probe(probePath.value)
    log(`④ 恢复启用后请求 ${probePath.value}`, result, result === 200 ? 'success' : 'warning')

    await load()
    await auth.refreshPermissions()
  } finally {
    probing.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="page-container">
    <div class="page-header">
      <div>
        <h2 class="page-title">权限点管理</h2>
        <p class="page-desc">
          权限点是授权的最小粒度。停用某个权限点后，所有持有它的用户
          <strong>下一次请求立即被拒绝</strong>，无需重启、无需等待 Token 过期。
        </p>
      </div>
      <div class="actions">
        <el-button :icon="Refresh" @click="load">刷新</el-button>
        <el-button type="primary" :icon="Plus" @click="dialogVisible = true">新建权限点</el-button>
      </div>
    </div>

    <!-- ★ R4 实时验证面板 -->
    <el-card shadow="never" class="probe-card">
      <template #header>
        <span class="card-title">实时验证（R4：权限变更无缓存延迟）</span>
        <span class="card-sub">用当前账号同一个 Token 请求两次，中间停用一次权限点</span>
      </template>

      <div class="probe-form">
        <el-select v-model="probeCode" style="width: 220px">
          <el-option
            v-for="p in permissions"
            :key="p.code"
            :label="p.code"
            :value="p.code"
          />
        </el-select>
        <el-select v-model="probePath" style="width: 220px">
          <el-option label="/api/products（products:read）" value="/api/products" />
          <el-option label="/api/orders（orders:read）" value="/api/orders" />
          <el-option label="/api/reports/summary（reports:view）" value="/api/reports/summary" />
          <el-option label="/api/roles（users:manage）" value="/api/roles" />
        </el-select>
        <el-button type="primary" :loading="probing" @click="runProbe">开始验证</el-button>
      </div>

      <div v-if="probeLog.length" class="probe-log">
        <div v-for="(item, i) in probeLog" :key="i" class="log-line">
          <el-tag
            v-if="item.status !== null"
            :type="item.status === 200 ? 'success' : item.status === 403 ? 'danger' : 'info'"
            size="small"
            class="status-tag"
          >
            {{ item.status }}
          </el-tag>
          <span v-else class="status-tag placeholder">—</span>
          <span :class="['log-text', item.tone]">{{ item.text }}</span>
        </div>
      </div>
      <div v-else class="empty-tip">
        点击「开始验证」，将自动完成：请求 → 停用权限点 → 用同一 Token 再请求 → 恢复启用
      </div>
    </el-card>

    <!-- 权限点列表 -->
    <el-card shadow="never" class="mt">
      <el-table v-loading="loading" :data="permissions" stripe>
        <el-table-column prop="id" label="ID" width="70" />
        <el-table-column prop="code" label="权限码" width="170">
          <template #default="{ row }">
            <span class="perm-code">{{ row.code }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="name" label="名称" width="160" />
        <el-table-column prop="module" label="模块" width="120">
          <template #default="{ row }">
            <el-tag size="small" effect="plain">{{ row.module }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="被引用" width="110" align="center">
          <template #default="{ row }">
            <el-tag :type="row.role_count > 0 ? 'warning' : 'info'" size="small" effect="plain">
              {{ row.role_count }} 个角色
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="110" align="center">
          <template #default="{ row }">
            <el-tag :type="row.is_active ? 'success' : 'danger'" size="small">
              {{ row.is_active ? '启用' : '已停用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="120" fixed="right">
          <template #default="{ row }">
            <el-button
              size="small"
              :type="row.is_active ? 'danger' : 'success'"
              link
              @click="toggle(row)"
            >
              {{ row.is_active ? '停用' : '启用' }}
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 新建权限点 -->
    <el-dialog v-model="dialogVisible" title="新建权限点" width="440px">
      <el-form ref="formRef" :model="form" :rules="rules" label-width="80px">
        <el-form-item label="权限码" prop="code">
          <el-input v-model="form.code" placeholder="形如 模块:动作，例如 products:export" />
        </el-form-item>
        <el-form-item label="名称" prop="name">
          <el-input v-model="form.name" placeholder="中文名，如 导出商品" />
        </el-form-item>
        <el-form-item label="模块" prop="module">
          <el-input v-model="form.module" placeholder="如 products" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="createPermission">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.actions {
  display: flex;
  gap: 8px;
}

.probe-card {
  border-color: #409eff;
}

.card-title {
  font-weight: 600;
}

.card-sub {
  margin-left: 10px;
  font-size: 12px;
  color: #909399;
}

.probe-form {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.probe-log {
  margin-top: 14px;
  padding: 12px;
  background: #f5f7fa;
  border-radius: 6px;
  font-size: 13px;
}

.log-line {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 5px 0;
}

.status-tag {
  min-width: 48px;
  text-align: center;
  font-family: 'Cascadia Mono', Consolas, monospace;
}

.status-tag.placeholder {
  color: #c0c4cc;
}

.log-text.success {
  color: #67c23a;
  font-weight: 600;
}

.log-text.danger {
  color: #f56c6c;
  font-weight: 600;
}

.log-text.warning {
  color: #e6a23c;
}

.mt {
  margin-top: 16px;
}
</style>
