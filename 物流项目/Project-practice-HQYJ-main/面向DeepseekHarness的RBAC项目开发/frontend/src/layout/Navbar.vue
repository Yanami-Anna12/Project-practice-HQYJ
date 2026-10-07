<script setup>
/**
 * 顶部栏：显示当前用户、角色与退出登录。
 *
 * 这里也演示了 v-permission 指令的 .disable 模式：
 * 「刷新权限」按钮所有人都能用，但「进入系统设置」这类入口
 * 用 disabled 方式提示，而不是直接消失 —— 两种体验各有用处。
 */
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
// 图标在本项目里是全局注册的组件，但在 <script setup> 中直接作为
// 组件属性值（:icon="Refresh"）使用时必须显式导入变量。
import { Refresh } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const router = useRouter()

const roleText = computed(() => (auth.roles.length ? auth.roles.join(' + ') : '无角色'))

async function handleRefresh() {
  try {
    await auth.refreshPermissions()
    ElMessage.success('已从后端重新拉取权限与菜单')
  } catch {
    /* 错误已由 axios 拦截器提示 */
  }
}

async function handleLogout() {
  try {
    await ElMessageBox.confirm('确定要退出登录吗？', '提示', {
      confirmButtonText: '退出',
      cancelButtonText: '取消',
      type: 'warning',
    })
  } catch {
    return // 用户取消
  }
  auth.logout()
  ElMessage.success('已退出登录')
  router.push('/login')
}
</script>

<template>
  <header class="navbar">
    <div class="left">
      <el-tag type="primary" effect="plain" size="small">
        角色：{{ roleText }}
      </el-tag>
      <el-tag v-if="!auth.roles.length" type="danger" effect="plain" size="small">
        无角色 → 所有受保护接口都会返回 403
      </el-tag>
    </div>

    <div class="right">
      <el-button size="small" :icon="Refresh" @click="handleRefresh">
        重新拉取权限
      </el-button>

      <el-dropdown trigger="click">
        <span class="user">
          <el-avatar :size="28" class="avatar">{{ auth.avatarText }}</el-avatar>
          <span class="uname">{{ auth.nickname }}</span>
          <el-icon><ArrowDown /></el-icon>
        </span>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item disabled>账号：{{ auth.username }}</el-dropdown-item>
            <el-dropdown-item divided @click="handleLogout">退出登录</el-dropdown-item>
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
  background: #fff;
  border-bottom: 1px solid #e4e7ed;
  flex-shrink: 0;
}

.left,
.right {
  display: flex;
  align-items: center;
  gap: 10px;
}

.user {
  display: flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  outline: none;
}

.avatar {
  background-color: #409eff;
  color: #fff;
  font-size: 13px;
}

.uname {
  font-size: 14px;
  color: #303133;
}
</style>
