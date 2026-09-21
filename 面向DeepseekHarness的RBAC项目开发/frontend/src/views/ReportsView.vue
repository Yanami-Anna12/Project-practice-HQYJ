<script setup>
/**
 * 数据报表：需要 reports:view。
 * 只读角色也有这个权限，因此只读账号能看到本页 —— 这正是权限矩阵里
 * 「只读 = products:read + orders:read + reports:view」的体现。
 */
import { onMounted, ref } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import * as api from '@/api'

const loading = ref(false)
const summary = ref(null)

async function load() {
  loading.value = true
  try {
    summary.value = await api.fetchReportSummary()
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="page-container">
    <div class="page-header">
      <div>
        <h2 class="page-title">数据报表</h2>
        <p class="page-desc">
          需要权限 <code class="perm-code">reports:view</code>。
          报表由后端聚合查询生成，响应里的 <code>generated_by</code>
          可证明鉴权通过后身份被透传到了业务层。
        </p>
      </div>
      <el-button :icon="Refresh" @click="load">刷新</el-button>
    </div>

    <el-row v-if="summary" :gutter="16">
      <el-col :xs="24" :sm="8">
        <el-card shadow="never">
          <div class="stat">
            <div class="stat-value">{{ summary.product_count }}</div>
            <div class="stat-label">商品总数</div>
          </div>
        </el-card>
      </el-col>
      <el-col :xs="24" :sm="8">
        <el-card shadow="never">
          <div class="stat">
            <div class="stat-value">{{ summary.order_count }}</div>
            <div class="stat-label">订单总数</div>
          </div>
        </el-card>
      </el-col>
      <el-col :xs="24" :sm="8">
        <el-card shadow="never">
          <div class="stat">
            <div class="stat-value">¥{{ Number(summary.total_amount).toFixed(2) }}</div>
            <div class="stat-label">订单总金额</div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <el-card v-if="summary" shadow="never" class="mt">
      <template #header>
        <span>订单状态分布</span>
      </template>
      <el-table :data="Object.entries(summary.order_status_breakdown).map(([k, v]) => ({ status: k, count: v }))" size="small">
        <el-table-column prop="status" label="状态" />
        <el-table-column prop="count" label="数量" width="120" />
      </el-table>

      <el-descriptions :column="2" border class="mt-sm">
        <el-descriptions-item label="生成时间">{{ summary.generated_at }}</el-descriptions-item>
        <el-descriptions-item label="生成人（鉴权身份透传）">
          <el-tag size="small" type="success">{{ summary.generated_by }}</el-tag>
        </el-descriptions-item>
      </el-descriptions>
    </el-card>

    <el-skeleton v-else :rows="4" animated />
  </div>
</template>

<style scoped>
.mt {
  margin-top: 16px;
}

.mt-sm {
  margin-top: 12px;
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

code {
  background: #f4f4f5;
  padding: 1px 5px;
  border-radius: 3px;
}
</style>
