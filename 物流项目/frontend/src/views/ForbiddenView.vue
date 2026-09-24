<script setup>
/**
 * 无权限页。
 * 由路由守卫在「已登录但缺少 meta.permission」时跳转到此。
 */
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Lock, Back } from '@element-plus/icons-vue'

const route = useRoute()
const router = useRouter()

const from = computed(() => route.query.from || '')
const need = computed(() => route.query.need || '')
</script>

<template>
  <div class="page-container">
    <el-result icon="warning" title="没有访问权限" :sub-title="from ? `目标页面：${from}` : ''">
      <template #extra>
        <div class="body">
          <p v-if="need" class="line">
            该页面需要权限点
            <code class="perm-code need">{{ need }}</code>
            ，当前账号没有该权限。
          </p>
          <p class="line muted">
            菜单与按钮由权限驱动，用有权限的账号登录（例如 <code class="perm-code">admin</code>）
            即可看到对应入口。
          </p>
          <div class="actions">
            <el-button type="primary" :icon="Back" @click="router.push('/dashboard')">
              返回调度看板
            </el-button>
            <el-button :icon="Lock" @click="router.push('/login')">切换账号</el-button>
          </div>
        </div>
      </template>
    </el-result>
  </div>
</template>

<style scoped>
.body {
  max-width: 520px;
  margin: 0 auto;
  text-align: left;
}

.line {
  font-size: 13px;
  line-height: 1.7;
  margin: 0 0 8px;
}

.need {
  color: #e6a23c;
  font-weight: 600;
}

.actions {
  margin-top: 16px;
  display: flex;
  justify-content: center;
  gap: 8px;
}
</style>
