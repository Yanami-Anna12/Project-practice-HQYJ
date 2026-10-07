<template>
  <div class="nf-wrap">
    <a-result status="404" title="404" sub-title="抱歉，你访问的页面不存在。">
      <template #extra>
        <a-button type="primary" @click="router.push('/dashboard')">返回首页</a-button>
      </template>
    </a-result>
  </div>
</template>

<script setup>
import { useRouter } from 'vue-router'

const router = useRouter()
</script>

<style scoped>
.nf-wrap {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #f0f2f5;
}
</style>
