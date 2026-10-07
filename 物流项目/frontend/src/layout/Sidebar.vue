<script setup>
/**
 * 侧边栏：完全由后端 GET /api/me/menus 返回的菜单树渲染。
 *
 * ★ 这里没有任何「某个角色能看到哪些菜单」的硬编码判断。
 *   用 viewer 账号登录后，「系统管理」分组根本不在数据里，也就无从渲染。
 *   菜单树的定义在 backend/app/menus.py，按权限裁剪后返回。
 */
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const route = useRoute()

/** 当前激活的菜单项 */
const activeMenu = computed(() => route.path)

/** 默认展开当前路径所属的分组 */
const openedMenus = computed(() => {
  const first = route.path.split('/')[1]
  return first ? [first] : []
})

/** 侧边栏底部的权限标签太多时只显示前若干个 */
const shownPermissions = computed(() => auth.permissions.slice(0, 12))
const hiddenCount = computed(() => Math.max(0, auth.permissions.length - 12))
</script>

<template>
  <aside class="sidebar">
    <div class="brand">
      <el-icon :size="20"><Van /></el-icon>
      <span class="brand-text">车辆智能调度</span>
    </div>

    <el-scrollbar class="menu-scroll">
      <el-menu
        :default-active="activeMenu"
        :default-openeds="openedMenus"
        router
        unique-opened
        background-color="#1f2d3d"
        text-color="#c0c4cc"
        active-text-color="#ffffff"
      >
        <template v-for="item in auth.menus" :key="item.key">
          <!-- 分组节点 -->
          <el-sub-menu v-if="item.children && item.children.length" :index="item.key">
            <template #title>
              <el-icon v-if="item.icon"><component :is="item.icon" /></el-icon>
              <span>{{ item.title }}</span>
            </template>
            <el-menu-item v-for="child in item.children" :key="child.key" :index="child.path">
              <el-icon v-if="child.icon"><component :is="child.icon" /></el-icon>
              <span>{{ child.title }}</span>
            </el-menu-item>
          </el-sub-menu>

          <!-- 叶子节点 -->
          <el-menu-item v-else :index="item.path">
            <el-icon v-if="item.icon"><component :is="item.icon" /></el-icon>
            <span>{{ item.title }}</span>
          </el-menu-item>
        </template>

        <div v-if="!auth.menus.length" class="menu-empty">当前账号没有任何可见菜单</div>
      </el-menu>
    </el-scrollbar>

    <div class="sidebar-footer">
      <div class="hint-title">当前权限（{{ auth.permissions.length }} 个）</div>
      <div class="perm-list">
        <el-tag v-for="code in shownPermissions" :key="code" size="small" type="info" effect="dark">
          {{ code }}
        </el-tag>
        <span v-if="hiddenCount" class="more">等 {{ hiddenCount }} 个</span>
        <span v-if="!auth.permissions.length" class="no-perm">无</span>
      </div>
      <div class="hint-note">菜单与按钮由权限驱动</div>
    </div>
  </aside>
</template>

<style scoped>
.sidebar {
  display: flex;
  flex-direction: column;
  width: 232px;
  height: 100%;
  background-color: #1f2d3d;
  color: #fff;
  flex-shrink: 0;
}

.brand {
  display: flex;
  align-items: center;
  gap: 8px;
  height: 56px;
  padding: 0 16px;
  font-size: 15px;
  font-weight: 600;
  color: #fff;
  border-bottom: 1px solid #2c3e50;
  flex-shrink: 0;
}

.brand-text {
  white-space: nowrap;
}

.menu-scroll {
  flex: 1;
  min-height: 0;
}

.sidebar :deep(.el-menu) {
  border-right: none;
}

.sidebar :deep(.el-menu-item.is-active) {
  background-color: #409eff !important;
}

.menu-empty {
  padding: 16px;
  font-size: 13px;
  color: #909399;
  text-align: center;
}

.sidebar-footer {
  padding: 12px 16px;
  border-top: 1px solid #2c3e50;
  flex-shrink: 0;
}

.hint-title {
  font-size: 12px;
  color: #909399;
  margin-bottom: 8px;
}

.perm-list {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  max-height: 108px;
  overflow-y: auto;
}

.perm-list :deep(.el-tag) {
  font-family: 'Cascadia Mono', Consolas, monospace;
  font-size: 11px;
  height: 20px;
  line-height: 20px;
  padding: 0 6px;
}

.no-perm,
.more {
  font-size: 12px;
  color: #909399;
}

.hint-note {
  margin-top: 8px;
  font-size: 11px;
  line-height: 1.5;
  color: #6b7280;
}
</style>
