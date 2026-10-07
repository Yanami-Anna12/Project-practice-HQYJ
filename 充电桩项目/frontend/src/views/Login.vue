<template>
  <div class="login-wrap">
    <div class="login-panel">
      <div class="brand">
        <div class="brand-logo">⚡</div>
        <h1>充电桩运维管理 AI Agent 平台</h1>
        <p class="brand-sub">
          工单 · 故障 · 巡检 · 台账 · 报告 全流程闭环，硬约束代码化 + LLM 辅助决策
        </p>
      </div>

      <a-form :model="form" layout="vertical" @finish="onSubmit">
        <a-form-item
          label="用户名"
          name="username"
          :rules="[{ required: true, message: '请输入用户名' }]"
        >
          <a-input
            v-model:value="form.username"
            size="large"
            placeholder="请输入用户名"
            allow-clear
          >
            <template #prefix><UserOutlined /></template>
          </a-input>
        </a-form-item>

        <a-form-item
          label="密码"
          name="password"
          :rules="[{ required: true, message: '请输入密码' }]"
        >
          <a-input-password
            v-model:value="form.password"
            size="large"
            placeholder="请输入密码"
          >
            <template #prefix><LockOutlined /></template>
          </a-input-password>
        </a-form-item>

        <a-button
          type="primary"
          html-type="submit"
          size="large"
          block
          :loading="loading"
        >
          登录
        </a-button>
      </a-form>

      <a-divider style="margin: 22px 0 14px">
        <span class="text-muted" style="font-size: 12px">演示账号（点击自动填入）</span>
      </a-divider>

      <div class="demo-accounts">
        <div
          v-for="item in accounts"
          :key="item.username"
          class="demo-card"
          @click="fill(item)"
        >
          <div class="demo-name">{{ item.real_name }}</div>
          <div class="demo-user mono">{{ item.username }}</div>
          <a-tag :color="item.color" style="margin-top: 6px">{{ item.scope }}</a-tag>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import { UserOutlined, LockOutlined } from '@ant-design/icons-vue'
import { useUserStore } from '@/stores/user'

const router = useRouter()
const route = useRoute()
const store = useUserStore()

const loading = ref(false)
const form = reactive({ username: 'admin', password: 'admin123' })

const accounts = [
  { username: 'admin', password: 'admin123', real_name: '平台管理员', scope: '平台数据', color: 'red' },
  { username: 'project_admin', password: '123456', real_name: '项目管理员', scope: '项目数据', color: 'orange' },
  { username: 'station_admin', password: '123456', real_name: '站点管理员', scope: '站点数据', color: 'blue' },
  { username: 'inspector', password: '123456', real_name: '运维人员', scope: '个人数据', color: 'green' },
]

function fill(item) {
  form.username = item.username
  form.password = item.password
}

async function onSubmit() {
  loading.value = true
  try {
    const user = await store.login({ ...form })
    message.success(`欢迎回来，${user.real_name}`)
    const redirect = route.query.redirect
    router.replace(typeof redirect === 'string' ? redirect : '/dashboard')
  } catch {
    /* 拦截器已提示 */
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-wrap {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #1f4e79 0%, #2f6fb5 55%, #4a90d9 100%);
  padding: 24px;
}

.login-panel {
  width: 100%;
  max-width: 430px;
  background: #fff;
  border-radius: 14px;
  padding: 34px 34px 26px;
  box-shadow: 0 18px 50px rgba(0, 0, 0, 0.25);
}

.brand {
  text-align: center;
  margin-bottom: 22px;
}

.brand-logo {
  font-size: 40px;
  line-height: 1;
  margin-bottom: 10px;
}

.brand h1 {
  font-size: 19px;
  color: #1f4e79;
  margin: 0 0 8px;
  font-weight: 600;
}

.brand-sub {
  font-size: 12px;
  color: #8c8c8c;
  margin: 0;
  line-height: 1.7;
}

.demo-accounts {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}

.demo-card {
  border: 1px solid #e8e8e8;
  border-radius: 8px;
  padding: 10px 12px;
  cursor: pointer;
  transition: all 0.2s;
  text-align: center;
}

.demo-card:hover {
  border-color: #2f6fb5;
  background: #f6f9ff;
  transform: translateY(-1px);
}

.demo-name {
  font-size: 13px;
  font-weight: 600;
  color: #1f2329;
}

.demo-user {
  font-size: 11px;
  color: #8c8c8c;
  margin-top: 2px;
}
</style>
