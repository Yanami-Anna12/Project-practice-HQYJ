<script setup>
/**
 * 订单管理：只读页面，需要 orders:read。
 * 管理员、运营、只读可访问；供应商会看到 403（且菜单里也没有这一项）。
 */
import { onMounted, ref } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import * as api from '@/api'

const loading = ref(false)
const orders = ref([])

const statusMap = {
  pending: { text: '待付款', type: 'warning' },
  paid: { text: '已付款', type: 'success' },
  shipped: { text: '已发货', type: 'primary' },
  done: { text: '已完成', type: 'info' },
}

async function load() {
  loading.value = true
  try {
    orders.value = await api.fetchOrders()
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
        <h2 class="page-title">订单管理</h2>
        <p class="page-desc">
          需要权限 <code class="perm-code">orders:read</code>。本页为只读，
          需求文档的权限矩阵中订单只有读权限，没有对应的写权限点。
        </p>
      </div>
      <el-button :icon="Refresh" @click="load">刷新</el-button>
    </div>

    <el-card shadow="never">
      <el-table v-loading="loading" :data="orders" stripe>
        <el-table-column prop="id" label="ID" width="70" />
        <el-table-column prop="order_no" label="订单号" width="150">
          <template #default="{ row }">
            <span class="perm-code">{{ row.order_no }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="customer" label="客户" min-width="160" />
        <el-table-column prop="amount" label="金额" width="120">
          <template #default="{ row }">¥{{ Number(row.amount).toFixed(2) }}</template>
        </el-table-column>
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tag :type="statusMap[row.status]?.type || 'info'" size="small">
              {{ statusMap[row.status]?.text || row.status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" width="180" />
      </el-table>
    </el-card>
  </div>
</template>

<style scoped>
code {
  background: #f4f4f5;
  padding: 1px 5px;
  border-radius: 3px;
}
</style>
