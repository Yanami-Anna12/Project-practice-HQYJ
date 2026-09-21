<script setup>
/**
 * 工作台：登录后即可访问（不要求任何权限点）。
 *
 * 页面展示当前账号的「权限画像」——角色、权限点、可见菜单，
 * 这是理解 RBAC 最直观的一屏：换一个账号登录，这里的内容就完全不同。
 */
import { computed } from 'vue'
import { Select } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()

/** 需求文档第 2 节的权限矩阵，用于在工作台上直接对照 */
const matrix = [
  { code: 'products:read', name: '查看商品', roles: ['admin', 'operator', 'supplier', 'readonly'] },
  { code: 'products:edit', name: '编辑商品', roles: ['admin', 'operator'] },
  { code: 'orders:read', name: '查看订单', roles: ['admin', 'operator', 'readonly'] },
  { code: 'reports:view', name: '查看报表', roles: ['admin', 'operator', 'readonly'] },
  { code: 'users:manage', name: '用户与权限管理', roles: ['admin'] },
  { code: 'settings:edit', name: '系统设置', roles: ['admin'] },
]

const roleNames = {
  admin: '管理员',
  operator: '运营',
  supplier: '供应商',
  readonly: '只读',
}

const myRoles = computed(() => new Set(auth.roles))
const menuCount = computed(() => {
  const count = (nodes) =>
    nodes.reduce((sum, n) => sum + 1 + (n.children ? count(n.children) : 0), 0)
  return count(auth.menus)
})
</script>

<template>
  <div class="page-container">
    <div class="page-header">
      <div>
        <h2 class="page-title">工作台</h2>
        <p class="page-desc">
          当前账号 <strong>{{ auth.username }}</strong>，角色
          <strong>{{ auth.roles.map((r) => roleNames[r] || r).join(' + ') || '无' }}</strong>，
          共 {{ auth.permissions.length }} 个权限点、{{ menuCount }} 个可见菜单。
        </p>
      </div>
    </div>

    <!-- 权限概览 -->
    <el-row :gutter="16">
      <el-col :xs="24" :sm="12" :md="6">
        <el-card shadow="never">
          <div class="stat">
            <div class="stat-value">{{ auth.roles.length }}</div>
            <div class="stat-label">绑定角色数</div>
          </div>
        </el-card>
      </el-col>
      <el-col :xs="24" :sm="12" :md="6">
        <el-card shadow="never">
          <div class="stat">
            <div class="stat-value">{{ auth.permissions.length }}</div>
            <div class="stat-label">有效权限点</div>
          </div>
        </el-card>
      </el-col>
      <el-col :xs="24" :sm="12" :md="6">
        <el-card shadow="never">
          <div class="stat">
            <div class="stat-value">{{ menuCount }}</div>
            <div class="stat-label">可见菜单</div>
          </div>
        </el-card>
      </el-col>
      <el-col :xs="24" :sm="12" :md="6">
        <el-card shadow="never">
          <div class="stat">
            <div class="stat-value">{{ auth.roles.length > 1 ? '并集' : '单角色' }}</div>
            <div class="stat-label">权限计算方式</div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 我的权限 -->
    <el-card shadow="never" class="mt">
      <template #header>
        <span class="card-title">我的有效权限</span>
        <span class="card-sub">多角色时各角色权限取并集，不是取最严</span>
      </template>
      <el-empty v-if="!auth.permissions.length" description="当前账号没有任何权限（后端会拒绝所有受保护接口）" />
      <div v-else class="perm-tags">
        <el-tag v-for="code in auth.permissions" :key="code" class="perm-code" type="success">
          {{ code }}
        </el-tag>
      </div>
    </el-card>

    <!-- 权限矩阵对照 -->
    <el-card shadow="never" class="mt">
      <template #header>
        <span class="card-title">权限矩阵（需求文档第 2 节）</span>
        <span class="card-sub">高亮行 = 当前账号拥有的权限</span>
      </template>
      <el-table :data="matrix" size="small" stripe>
        <el-table-column prop="code" label="权限点" width="180">
          <template #default="{ row }">
            <span class="perm-code">{{ row.code }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="name" label="名称" width="150" />
        <el-table-column
          v-for="role in ['admin', 'operator', 'supplier', 'readonly']"
          :key="role"
          :label="roleNames[role]"
          align="center"
          width="100"
        >
          <template #default="{ row }">
            <el-icon v-if="row.roles.includes(role)" color="#67c23a"><Select /></el-icon>
            <span v-else class="dash">—</span>
          </template>
        </el-table-column>
        <el-table-column label="当前账号" align="center" width="110">
          <template #default="{ row }">
            <el-tag
              :type="auth.permissions.includes(row.code) ? 'success' : 'info'"
              size="small"
              effect="plain"
            >
              {{ auth.permissions.includes(row.code) ? '有' : '无' }}
            </el-tag>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 说明 -->
    <el-alert type="warning" :closable="false" class="mt">
      <template #title>关于「前端权限」的定位</template>
      <template #default>
        本页的角色与权限清单来自登录响应，保存在浏览器里，可以在控制台随意篡改。
        改完之后菜单和按钮确实会变化，但<strong>接口依然会被后端拒绝（403）</strong>——
        因为后端每次请求都会重新查库计算权限。前端的显隐只是体验优化，后端才是最终防线。
      </template>
    </el-alert>
  </div>
</template>

<style scoped>
.mt {
  margin-top: 16px;
}

.stat {
  text-align: center;
  padding: 4px 0;
}

.stat-value {
  font-size: 24px;
  font-weight: 600;
  color: #409eff;
}

.stat-label {
  margin-top: 4px;
  font-size: 13px;
  color: #909399;
}

.card-title {
  font-weight: 600;
}

.card-sub {
  margin-left: 10px;
  font-size: 12px;
  color: #909399;
}

.perm-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.perm-tags :deep(.el-tag) {
  font-family: 'Cascadia Mono', Consolas, monospace;
}

.dash {
  color: #dcdfe6;
}
</style>
