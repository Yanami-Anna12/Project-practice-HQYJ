<script setup>
/**
 * 主布局：左侧边栏 + 右上顶栏 + 内容区。
 * 登录页不使用本布局（见 router/index.js 的配置）。
 */
import Sidebar from './Sidebar.vue'
import Navbar from './Navbar.vue'
</script>

<template>
  <div class="layout">
    <Sidebar />
    <div class="main">
      <Navbar />
      <el-scrollbar class="content">
        <router-view v-slot="{ Component }">
          <!-- 用 key 强制切换路由时重建组件，避免上一页的数据残留 -->
          <component :is="Component" :key="$route.fullPath" />
        </router-view>
      </el-scrollbar>
    </div>
  </div>
</template>

<style scoped>
.layout {
  display: flex;
  height: 100vh;
  overflow: hidden;
}

.main {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-width: 0;
}

.content {
  flex: 1;
  min-height: 0;
  background-color: #f5f7fa;
}
</style>
