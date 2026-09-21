<script setup>
/** 404 页面。路由里用 catch-all 兜底，避免输入错误路径时白屏。 */
import { useRouter } from 'vue-router'

const router = useRouter()
</script>

<template>
  <div class="page-container">
    <el-result icon="info" title="页面不存在" sub-title="请检查地址是否正确，或从左侧菜单进入。" >
      <template #extra>
        <el-button type="primary" @click="router.push('/dashboard')">回到工作台</el-button>
      </template>
    </el-result>
  </div>
</template>
