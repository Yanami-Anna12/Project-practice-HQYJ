<script setup>
/**
 * 404 页：命中未定义路由时给出明确提示，而不是白屏。
 */
import { useRouter } from 'vue-router'
import { Back } from '@element-plus/icons-vue'

const router = useRouter()
</script>

<template>
  <div class="page-container">
    <el-result icon="info" title="404" sub-title="页面不存在">
      <template #extra>
        <el-button type="primary" :icon="Back" @click="router.push('/dashboard')">
          返回调度看板
        </el-button>
      </template>
    </el-result>
  </div>
</template>
