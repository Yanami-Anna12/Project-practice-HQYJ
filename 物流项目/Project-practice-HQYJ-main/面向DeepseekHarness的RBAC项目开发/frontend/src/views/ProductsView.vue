<script setup>
/**
 * 商品管理 —— 按钮级权限控制的演示页面。
 *
 * ★ 验收重点在这里：
 *   「新建商品」按钮用 v-permission="'products:edit'" 控制。
 *   以供应商或只读角色登录时，按钮会从 DOM 中消失；
 *   以管理员或运营登录时，按钮正常显示。
 *
 *   但请注意：按钮消失只是体验优化。真正拦住越权的是后端
 *   POST /api/products 上的 authorize("products:edit") ——
 *   附录里有一个"直接构造请求"的按钮，用来演示这一点。
 */
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Plus, Refresh } from '@element-plus/icons-vue'
import * as api from '@/api'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()

const loading = ref(false)
const products = ref([])
const dialogVisible = ref(false)
const submitting = ref(false)
const formRef = ref()

const form = reactive({
  name: '',
  sku: '',
  price: 0,
  stock: 0,
})

const rules = {
  name: [{ required: true, message: '请输入商品名称', trigger: 'blur' }],
  sku: [{ required: true, message: '请输入 SKU', trigger: 'blur' }],
}

async function load() {
  loading.value = true
  try {
    products.value = await api.fetchProducts()
  } finally {
    loading.value = false
  }
}

function openDialog() {
  Object.assign(form, { name: '', sku: '', price: 0, stock: 0 })
  dialogVisible.value = true
}

async function submit() {
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return

  submitting.value = true
  try {
    await api.createProduct({ ...form })
    ElMessage.success('新建成功')
    dialogVisible.value = false
    await load()
  } finally {
    submitting.value = false
  }
}

/**
 * 演示用：绕过界面按钮，直接向后端 POST。
 *
 * 用途是直观展示「前端隐藏 ≠ 安全控制」：
 * 即便按钮被 v-permission 移除了，构造请求仍会被后端 403 拦下。
 * 这个按钮本身不做权限判断，就是要让人能点到它。
 */
async function bypassAttempt() {
  try {
    await api.createProduct({
      name: '绕过界面直接提交',
      sku: `BYPASS-${Date.now()}`,
      price: 1,
      stock: 1,
    })
    ElMessage.success('创建成功 —— 说明当前账号确实有 products:edit 权限')
  } catch {
    // 403 的提示由 axios 拦截器给出，这里不用重复提示
  }
}

/** 模板里不能直接引用脚本作用域的导入变量，用方法包一层 */
function explainEdit() {
  ElMessage.info('本例只演示按钮权限，未实现编辑功能')
}

onMounted(load)
</script>

<template>
  <div class="page-container">
    <div class="page-header">
      <div>
        <h2 class="page-title">商品管理</h2>
        <p class="page-desc">
          GET /api/products 需要 <code class="perm-code">products:read</code>；
          POST /api/products 需要 <code class="perm-code">products:edit</code>。
        </p>
      </div>
      <div class="actions">
        <el-button :icon="Refresh" @click="load">刷新</el-button>

        <!--
          ★ 按钮级权限控制：
             无 products:edit 时该按钮被指令从 DOM 中移除（供应商/只读看不到）
        -->
        <el-button
          v-permission="'products:edit'"
          type="primary"
          :icon="Plus"
          @click="openDialog"
        >
          新建商品
        </el-button>

        <el-tooltip content="绕过界面按钮直接调用后端接口，用于验证后端才是最终防线">
          <el-button type="warning" plain @click="bypassAttempt">直接提交请求</el-button>
        </el-tooltip>
      </div>
    </div>

    <el-card shadow="never">
      <el-table v-loading="loading" :data="products" stripe>
        <el-table-column prop="id" label="ID" width="70" />
        <el-table-column prop="name" label="商品名称" min-width="160" />
        <el-table-column prop="sku" label="SKU" width="130">
          <template #default="{ row }">
            <span class="perm-code">{{ row.sku }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="price" label="单价" width="110">
          <template #default="{ row }">¥{{ Number(row.price).toFixed(2) }}</template>
        </el-table-column>
        <el-table-column prop="stock" label="库存" width="90" />
        <el-table-column prop="created_by" label="创建人 ID" width="100" />
        <el-table-column label="操作" width="120">
          <template #default>
            <!--
              .disable 模式：无权限时按钮保留但置灰，并在 title 里说明原因。
              与上面的"隐藏"模式对比，让两种体验差异一目了然。
            -->
            <el-button
              v-permission.disable="'products:edit'"
              size="small"
              type="primary"
              link
              @click="explainEdit"
            >
              编辑
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-alert type="info" :closable="false" class="mt">
      <template #title>
        当前账号角色 <strong>{{ auth.roles.join(' + ') || '无' }}</strong>，
        权限 {{ auth.permissions.length }} 个。
        <template v-if="!auth.has('products:edit')">
          「新建商品」按钮已被 v-permission 指令移除；但即使点上面的
          「直接提交请求」，后端仍会返回 403。
        </template>
        <template v-else>
          你有 products:edit 权限，因此「新建商品」按钮可见、点击可成功。
        </template>
      </template>
    </el-alert>

    <el-dialog v-model="dialogVisible" title="新建商品" width="440px">
      <el-form ref="formRef" :model="form" :rules="rules" label-width="80px">
        <el-form-item label="商品名称" prop="name">
          <el-input v-model="form.name" placeholder="请输入商品名称" />
        </el-form-item>
        <el-form-item label="SKU" prop="sku">
          <el-input v-model="form.sku" placeholder="唯一编号，如 KB-K8-002" />
        </el-form-item>
        <el-form-item label="单价">
          <el-input-number v-model="form.price" :min="0" :precision="2" />
        </el-form-item>
        <el-form-item label="库存">
          <el-input-number v-model="form.stock" :min="0" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submit">确定</el-button>
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

.mt {
  margin-top: 16px;
}

code {
  background: #f4f4f5;
  padding: 1px 5px;
  border-radius: 3px;
}
</style>
