<script setup>
/**
 * 未开发模块的占位页。
 *
 * 首版只实现了「系统管理」7 个页面，其余模块在菜单里可见但指向本页，
 * 这样能直观看到系统的完整菜单结构，也标明每个模块规划了哪些页面。
 *
 * ★ 这里刻意不假装有数据 —— 明确写「待开发」比放一堆假数字更有用。
 */
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { Tools } from '@element-plus/icons-vue'
import { PERMISSION_MODULES } from '@/api/meta'

const route = useRoute()

const title = computed(() => route.meta.title || '未命名页面')
const moduleKey = computed(() => route.path.split('/')[1])

/** 本页所属模块在需求文档里的规划 */
const moduleInfo = computed(() => {
  const key = moduleKey.value
  const found = Object.entries(PERMISSION_MODULES).find(([, v]) => v.match === key)
  return found ? { key: found[0], ...found[1] } : null
})
</script>

<template>
  <div class="page-container">
    <div class="page-header">
      <div>
        <h2 class="page-title">{{ title }}</h2>
        <p class="page-desc">
          本页属于「{{ moduleInfo?.title || moduleKey }}」模块，
          <strong>首版尚未实现</strong>。当前版本的实现范围见下方说明。
        </p>
      </div>
    </div>

    <el-card shadow="never">
      <el-empty :image-size="120" description="该页面待开发">
        <template #description>
          <div class="empty-title">该页面待开发</div>
          <div class="empty-sub">
            路由与权限点已就位（<code class="perm-code">{{ route.meta.permission || '无' }}</code>），
            接上真实后端与页面实现即可启用。
          </div>
        </template>
      </el-empty>

      <el-divider content-position="left">首版实现范围</el-divider>
      <div class="scope">
        <div class="scope-item done">
          <el-icon><Tools /></el-icon>
          <div>
            <div class="scope-title">已完成：系统管理</div>
            <div class="scope-desc">
              用户、角色、权限、字典、参数、附件、日志 7 个页面，含权限驱动的菜单与按钮显隐。
            </div>
          </div>
        </div>
        <div class="scope-item todo">
          <el-icon><Tools /></el-icon>
          <div>
            <div class="scope-title">待开发：其余业务模块</div>
            <div class="scope-desc">
              业务基础数据、调度规则配置、车辆分配管理、智能调度 Agent、报表与看板、集成与监控。
              需求与数据结构见《需求文档.md》第二至六章。
            </div>
          </div>
        </div>
      </div>
    </el-card>
  </div>
</template>

<style scoped>
.empty-title {
  font-size: 15px;
  color: #303133;
  margin-bottom: 6px;
}

.empty-sub {
  font-size: 12px;
  color: #909399;
  line-height: 1.7;
}

.scope {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.scope-item {
  display: flex;
  gap: 10px;
  padding: 12px 14px;
  border-radius: 6px;
  border: 1px solid #e4e7ed;
}

.scope-item.done {
  background: #f0f9eb;
  border-color: #c2e7b0;
}

.scope-item.todo {
  background: #fdf6ec;
  border-color: #f5dab1;
}

.scope-title {
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 2px;
}

.scope-desc {
  font-size: 12px;
  color: #606266;
  line-height: 1.7;
}
</style>
