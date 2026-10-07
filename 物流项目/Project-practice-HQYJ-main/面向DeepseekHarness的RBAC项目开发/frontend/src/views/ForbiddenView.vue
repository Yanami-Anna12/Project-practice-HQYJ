<script setup>
/**
 * 无权限提示页。
 *
 * 路由守卫在 meta.permission 校验失败时会跳到这里。
 * 这属于"体验优化"——它让用户明白发生了什么，而不是看到一个空白页；
 * 但它不是安全边界，真正的拦截在后端。
 */
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
</script>

<template>
  <div class="page-container">
    <el-result icon="warning" title="没有权限" :sub-title="`访问 ${route.query.from || '该页面'} 需要权限：${route.query.need || '未知'}`">
      <template #extra>
        <div class="inline-tags">
          <span class="label">当前账号持有：</span>
          <el-tag v-for="code in auth.permissions" :key="code" size="small" class="perm-code">
            {{ code }}
          </el-tag>
          <span v-if="!auth.permissions.length" class="label">（无）</span>
        </div>
        <div class="btns">
          <el-button type="primary" @click="router.push('/dashboard')">回到工作台</el-button>
          <el-button @click="router.back()">返回上一页</el-button>
        </div>
      </template>
    </el-result>

    <el-alert type="info" :closable="false" class="tip">
      <template #title>
        这个页面是路由守卫拦下来的，属于前端体验优化。即使有人绕过守卫，
        后端接口依然会独立校验权限并返回 403 —— 后端才是最终防线。
      </template>
    </el-alert>
  </div>
</template>

<style scoped>
.inline-tags {
  display: flex;
  align-items: center;
  justify-content: center;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 16px;
}

.label {
  font-size: 13px;
  color: #909399;
}

.btns {
  display: flex;
  justify-content: center;
  gap: 8px;
}

.tip {
  max-width: 720px;
  margin: 0 auto;
}

.tip :deep(.el-alert__title) {
  font-size: 12px;
  line-height: 1.6;
}
</style>
