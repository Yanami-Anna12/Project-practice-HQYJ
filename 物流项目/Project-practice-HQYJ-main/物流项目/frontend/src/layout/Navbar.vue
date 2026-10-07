<script setup>
/**
 * 顶栏：面包屑 + 当前角色 + 用户菜单。
 */
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowDown, SwitchButton, User } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()

const currentTitle = computed(() => route.meta.title || '')

async function handleLogout() {
  try {
    await ElMessageBox.confirm('确定退出登录？', '提示', {
      type: 'warning',
      confirmButtonText: '退出',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  await auth.logout()
  ElMessage.success('已退出登录')
  router.push('/login')
}

function handleCommand(command) {
  if (command === 'logout') handleLogout()
}
</script>

<template>
  <header class="navbar">
    <div class="left">
      <span class="app-name">车辆智能调度 Agent</span>
      <el-divider direction="vertical" />
      <span class="page-name">{{ currentTitle }}</span>
    </div>

    <div class="right">
      <el-tag v-for="name in auth.roleNames" :key="name" size="small" effect="plain" class="role-tag">
        {{ name }}
      </el-tag>

      <el-dropdown @command="handleCommand">
        <span class="user">
          <el-icon><User /></el-icon>
          <span class="username">{{ auth.user?.nickname || auth.user?.username }}</span>
          <el-icon><ArrowDown /></el-icon>
        </span>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item disabled>
              {{ auth.user?.username }} · {{ auth.user?.dept || '未设置部门' }}
            </el-dropdown-item>
            <el-dropdown-item divided command="logout">
              <el-icon><SwitchButton /></el-icon>
              退出登录
            </el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
    </div>
  </header>
</template>

<style scoped>
.navbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 56px;
  padding: 0 16px;
  background-color: #fff;
  border-bottom: 1px solid #e4e7ed;
  flex-shrink: 0;
}

.left {
  display: flex;
  align-items: center;
  gap: 8px;
}

.app-name {
  font-size: 14px;
  font-weight: 600;
  color: #303133;
}

.page-name {
  font-size: 14px;
  color: #909399;
}

.right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.role-tag {
  font-size: 12px;
}

.user {
  display: flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  color: #303133;
  outline: none;
}

.username {
  font-size: 13px;
}
</style>
