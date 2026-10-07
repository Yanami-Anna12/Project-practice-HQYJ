<script setup>
/**
 * 登录页。
 *
 * 演示账号（由 backend/seed.py 写入 MySQL，密码见 backend/.env）：
 *   admin / admin123        系统管理员 —— 全部 29 个权限，含系统管理
 *   dispatcher / 123456     调度员     —— 无系统管理权限，看不到「系统管理」分组
 *   dataadmin / 123456      基础数据管理员
 *   viewer / 123456         只读观察者
 *   multi / 123456          多角色（调度员 + 只读）—— 权限取并集
 *   disabled / 123456       已停用账号 —— 登录会被拒绝
 */
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Lock, User, Van } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'
import { tryAction } from '@/utils/error'

const auth = useAuthStore()
const router = useRouter()
const route = useRoute()

const formRef = ref()
const loading = ref(false)
const form = ref({ username: '', password: '' })

const rules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}

const demoAccounts = [
  { username: 'admin', password: 'admin123', label: '系统管理员', note: '全部 29 个权限' },
  { username: 'dispatcher', password: '123456', label: '调度员', note: '看不到系统管理' },
  { username: 'dataadmin', password: '123456', label: '数据管理员', note: '基础数据维护' },
  { username: 'viewer', password: '123456', label: '只读观察者', note: '只能查看' },
  { username: 'multi', password: '123456', label: '多角色用户', note: '权限取并集' },
  { username: 'disabled', password: '123456', label: '已停用账号', note: '登录被拒绝' },
]

function fill(account) {
  form.value.username = account.username
  form.value.password = account.password
}

async function submit() {
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return

  loading.value = true
  const { ok, result } = await tryAction(() => auth.login({ ...form.value }))
  loading.value = false

  if (!ok) return
  ElMessage.success(`欢迎，${result.nickname}（${result.role_names.join(' + ') || '无角色'}）`)
  router.push(route.query.redirect || '/dashboard')
}
</script>

<template>
  <div class="login-page">
    <div class="login-card">
      <div class="head">
        <el-icon :size="30" color="#409eff"><Van /></el-icon>
        <h1 class="title">车辆智能调度 Agent</h1>
        <p class="subtitle">门店配送车辆与趟次智能分配系统</p>
      </div>

      <el-form ref="formRef" :model="form" :rules="rules" size="large" @keyup.enter="submit">
        <el-form-item prop="username">
          <el-input v-model="form.username" placeholder="用户名" :prefix-icon="User" clearable />
        </el-form-item>
        <el-form-item prop="password">
          <el-input
            v-model="form.password"
            type="password"
            placeholder="密码"
            :prefix-icon="Lock"
            show-password
          />
        </el-form-item>
        <el-button type="primary" class="submit" size="large" :loading="loading" @click="submit">
          登 录
        </el-button>
      </el-form>

      <el-divider content-position="left">演示账号（点击填入）</el-divider>
      <div class="accounts">
        <div v-for="a in demoAccounts" :key="a.username" class="account" @click="fill(a)">
          <div class="account-main">
            <span class="account-name">{{ a.label }}</span>
            <span class="account-user perm-code">{{ a.username }}</span>
          </div>
          <span class="account-note">{{ a.note }}</span>
        </div>
      </div>

      <el-alert type="warning" :closable="false" class="tip">
        <template #title>
          账号与数据来自本机 <strong>MySQL（logistics_db）</strong>，
          鉴权由后端 JWT 校验。页面上的权限裁剪只是界面优化，后端接口会独立复核。
        </template>
      </el-alert>
    </div>
  </div>
</template>

<style scoped>
.login-page {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  padding: 24px;
  background: linear-gradient(135deg, #1f2d3d 0%, #2c3e50 55%, #409eff 140%);
}

.login-card {
  width: 460px;
  max-width: 100%;
  padding: 28px 32px 24px;
  background: #fff;
  border-radius: 10px;
  box-shadow: 0 12px 40px rgba(0, 0, 0, 0.25);
}

.head {
  text-align: center;
  margin-bottom: 20px;
}

.title {
  margin: 8px 0 4px;
  font-size: 20px;
  font-weight: 600;
}

.subtitle {
  margin: 0;
  font-size: 13px;
  color: #909399;
}

.submit {
  width: 100%;
}

.accounts {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}

.account {
  padding: 8px 10px;
  border: 1px solid #e4e7ed;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s;
}

.account:hover {
  border-color: #409eff;
  background: #ecf5ff;
}

.account-main {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
}

.account-name {
  font-size: 13px;
  font-weight: 600;
}

.account-user {
  color: #909399;
}

.account-note {
  display: block;
  margin-top: 2px;
  font-size: 11px;
  color: #909399;
}

.tip {
  margin-top: 16px;
}
</style>
