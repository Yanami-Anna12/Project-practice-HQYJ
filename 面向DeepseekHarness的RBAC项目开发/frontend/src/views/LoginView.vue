<script setup>
/**
 * 登录页。
 *
 * 页面下半部分列出了演示账号，并提供一键填充 —— 目的是让验收时能快速
 * 切换四种角色，直观看到「同一套界面因权限不同而呈现不同菜单」。
 */
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
// 图标虽然全局注册过，但作为 prop 值（:prefix-icon="User"）传入时必须先导入变量
import { Lock, User } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const router = useRouter()
const route = useRoute()

const formRef = ref()
const loading = ref(false)

const form = reactive({
  username: 'admin',
  password: 'admin123',
})

const rules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}

/** 演示账号清单：直接对应需求文档第 2 节的四个内置角色 + 一个多角色样本 */
const demoAccounts = [
  { username: 'admin', password: 'admin123', label: '管理员', note: '全部 6 个权限点' },
  { username: 'operator', password: '123456', label: '运营', note: '4 个权限，可编辑商品' },
  { username: 'supplier', password: '123456', label: '供应商', note: '仅 products:read' },
  { username: 'readonly', password: '123456', label: '只读', note: '3 个只读权限' },
  {
    username: 'multi',
    password: '123456',
    label: '多角色',
    note: '运营 + 只读 → 权限取并集',
    highlight: true,
  },
]

function fill(account) {
  form.username = account.username
  form.password = account.password
}

async function handleLogin() {
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return

  loading.value = true
  try {
    const data = await auth.login(form.username, form.password)
    ElMessage.success(
      `登录成功，角色 ${data.roles.join(' + ') || '无'}，共 ${data.permissions.length} 个权限点`,
    )
    router.push(route.query.redirect || '/dashboard')
  } catch {
    // 错误提示已由 axios 拦截器统一处理（401 → "未登录"）
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-page">
    <el-card class="login-card" shadow="always">
      <div class="header">
        <el-icon :size="32" color="#409eff"><Lock /></el-icon>
        <h1>RBAC 权限管理系统</h1>
        <p>基于角色的访问控制 · 多角色权限取并集 · 后端实时鉴权</p>
      </div>

      <el-form
        ref="formRef"
        :model="form"
        :rules="rules"
        size="large"
        label-position="top"
        @keyup.enter="handleLogin"
      >
        <el-form-item label="用户名" prop="username">
          <el-input v-model="form.username" placeholder="请输入用户名" :prefix-icon="User" />
        </el-form-item>
        <el-form-item label="密码" prop="password">
          <el-input
            v-model="form.password"
            type="password"
            placeholder="请输入密码"
            show-password
            :prefix-icon="Lock"
          />
        </el-form-item>
        <el-button type="primary" class="submit" :loading="loading" @click="handleLogin">
          登 录
        </el-button>
      </el-form>

      <el-divider>演示账号（点击一键填充）</el-divider>

      <div class="demo-list">
        <div
          v-for="acc in demoAccounts"
          :key="acc.username"
          class="demo-item"
          :class="{ highlight: acc.highlight }"
          @click="fill(acc)"
        >
          <div class="demo-left">
            <el-tag size="small" :type="acc.highlight ? 'warning' : 'info'" effect="plain">
              {{ acc.label }}
            </el-tag>
            <span class="demo-user">{{ acc.username }}</span>
          </div>
          <span class="demo-note">{{ acc.note }}</span>
        </div>
      </div>

      <el-alert type="info" :closable="false" class="tip">
        <template #title>
          登录响应里的权限清单<strong>仅用于渲染界面</strong>。后端每个接口都会实时查库重新计算权限，
          因此伪造前端权限不会获得任何实际访问能力。
        </template>
      </el-alert>
    </el-card>
  </div>
</template>

<style scoped>
.login-page {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  padding: 24px;
  background: linear-gradient(135deg, #1f2d3d 0%, #34495e 55%, #409eff 140%);
}

.login-card {
  width: 480px;
  max-width: 100%;
  border-radius: 10px;
}

.header {
  text-align: center;
  margin-bottom: 20px;
}

.header h1 {
  margin: 10px 0 6px;
  font-size: 21px;
  font-weight: 600;
}

.header p {
  margin: 0;
  font-size: 13px;
  color: #909399;
}

.submit {
  width: 100%;
  margin-top: 4px;
}

.demo-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.demo-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 8px 10px;
  border: 1px solid #e4e7ed;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.15s;
}

.demo-item:hover {
  border-color: #409eff;
  background-color: #ecf5ff;
}

.demo-item.highlight {
  border-color: #e6a23c;
  background-color: #fdf6ec;
}

.demo-left {
  display: flex;
  align-items: center;
  gap: 8px;
}

.demo-user {
  font-family: 'Cascadia Mono', Consolas, monospace;
  font-size: 13px;
}

.demo-note {
  font-size: 12px;
  color: #909399;
}

.tip {
  margin-top: 16px;
}

.tip :deep(.el-alert__title) {
  font-size: 12px;
  line-height: 1.6;
}
</style>
