<script setup>
/**
 * 接口集成配置（需求 二.7「接口集成与数据交换」）。
 *
 * ★ 本页如实呈现每项集成的状态。所有外部系统目前都**未真实连通**，
 *   页面不会伪装成"已就绪"：
 *     · not_connected  未对接
 *     · partial        本项目内已落地一部分（例如 TMS 的下发记录、
 *                      OMS 的货量入口），但对外调用尚未接入
 *
 *   对每项还标注了「本地证据」，说明系统内已经有多少相关数据，
 *   便于判断接线后能立刻产生什么效果。
 */
import { computed, onMounted, ref } from 'vue'
import { Refresh, Link, Connection } from '@element-plus/icons-vue'
import * as api from '@/api'
import { withError } from '@/utils/error'

const loading = ref(false)
const integrations = ref([])
const dataPlatform = ref(null)

async function load() {
  loading.value = true
  try {
    const [i, d] = await Promise.all([
      withError(() => api.fetchIntegrations()),
      withError(() => api.fetchDataPlatform()),
    ])
    integrations.value = i || []
    dataPlatform.value = d
  } finally {
    loading.value = false
  }
}

const stats = computed(() => {
  const s = { partial: 0, not_connected: 0 }
  for (const i of integrations.value) s[i.status] = (s[i.status] || 0) + 1
  return s
})

const statusMeta = (s) =>
  s === 'partial'
    ? { text: '部分落地', type: 'warning', desc: '系统内已实现相关数据链路，对外接口尚未接入' }
    : { text: '未对接', type: 'info', desc: '本期未实现' }

const implemented = computed(() => dataPlatform.value?.implemented || [])
const planned = computed(() => dataPlatform.value?.planned || [])
const scale = computed(() => dataPlatform.value?.data_scale || {})

onMounted(load)
</script>

<template>
  <div class="page-container">
    <div class="page-header">
      <div>
        <h2 class="page-title">接口集成配置</h2>
        <p class="page-desc">
          与 TMS / OMS / WMS / ERP / 地图服务等的对接清单。
          <strong>本页如实标注对接状态</strong>，未连通的不伪装成已就绪。需要
          <code class="perm-code">integrations:manage</code>。
        </p>
      </div>
      <el-button :icon="Refresh" @click="load">刷新</el-button>
    </div>

    <el-row :gutter="16" class="mb">
      <el-col :xs="12" :sm="6">
        <el-card shadow="never" class="stat">
          <div class="stat-label">集成项总数</div>
          <div class="stat-value">{{ integrations.length }}</div>
        </el-card>
      </el-col>
      <el-col :xs="12" :sm="6">
        <el-card shadow="never" class="stat">
          <div class="stat-label">部分落地</div>
          <div class="stat-value warn">{{ stats.partial }}</div>
        </el-card>
      </el-col>
      <el-col :xs="12" :sm="6">
        <el-card shadow="never" class="stat">
          <div class="stat-label">未对接</div>
          <div class="stat-value muted-value">{{ stats.not_connected }}</div>
        </el-card>
      </el-col>
      <el-col :xs="12" :sm="6">
        <el-card shadow="never" class="stat">
          <div class="stat-label">已实现能力</div>
          <div class="stat-value ok">{{ implemented.length }}</div>
          <div class="stat-note">见下方「数据与算法平台」</div>
        </el-card>
      </el-col>
    </el-row>

    <el-alert type="warning" :closable="false" class="mb">
      <template #title>
        <el-icon><Connection /></el-icon>
        当前<strong>没有任何外部系统真实连通</strong>。所有调度、下发、异常处理都在系统内部闭环；
        「下发」写入的是本地的 <code class="perm-code">dispatch_record</code> 表（幂等去重），
        并未真的调用 TMS。接真实系统时按每项的 endpoint 提示接入即可。
      </template>
    </el-alert>

    <el-card v-loading="loading" shadow="never" class="mb">
      <template #header>
        <span class="card-title">集成清单</span>
      </template>
      <el-table :data="integrations" stripe>
        <el-table-column label="系统" width="130">
          <template #default="{ row }">
            <div class="sys-name">
              <el-icon><Link /></el-icon>
              <span>{{ row.name }}</span>
            </div>
            <div class="sys-full">{{ row.full_name }}</div>
          </template>
        </el-table-column>
        <el-table-column label="方向" width="110">
          <template #default="{ row }">
            <el-tag size="small" effect="plain">{{ row.direction }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="content" label="集成内容" min-width="180" />
        <el-table-column label="接口" min-width="200">
          <template #default="{ row }">
            <span class="perm-code">{{ row.endpoint }}</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="120">
          <template #default="{ row }">
            <el-tag :type="statusMeta(row.status).type" size="small">
              {{ statusMeta(row.status).text }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="本地证据 / 说明" min-width="300">
          <template #default="{ row }">
            <div v-if="row.local_evidence" class="evidence">{{ row.local_evidence }}</div>
            <div class="note-text">{{ row.note }}</div>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 数据与算法平台 -->
    <el-row :gutter="16" class="mb">
      <el-col :xs="24" :lg="12">
        <el-card v-loading="loading" shadow="never" class="h-full">
          <template #header>
            <span class="card-title">数据与算法平台 · 已实现</span>
          </template>
          <div class="item-list">
            <div v-for="i in implemented" :key="i.name" class="item done">
              <div class="item-name">{{ i.name }}</div>
              <div class="item-detail">{{ i.detail }}</div>
            </div>
          </div>
        </el-card>
      </el-col>
      <el-col :xs="24" :lg="12">
        <el-card v-loading="loading" shadow="never" class="h-full">
          <template #header>
            <span class="card-title">数据与算法平台 · 规划中</span>
          </template>
          <div class="item-list">
            <div v-for="i in planned" :key="i.name" class="item todo">
              <div class="item-name">{{ i.name }}</div>
              <div class="item-detail">{{ i.detail }}</div>
              <div class="item-collector">拟用组件：{{ i.collector }}</div>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <el-card shadow="never">
      <template #header>
        <span class="card-title">当前数据规模</span>
      </template>
      <el-row :gutter="12">
        <el-col v-for="(v, k) in scale" :key="k" :xs="12" :sm="6" :lg="3">
          <div class="scale-item">
            <div class="scale-value">{{ v }}</div>
            <div class="scale-label">{{ k }}</div>
          </div>
        </el-col>
      </el-row>
      <div class="note">
        这些是系统内的真实行数，可作为接入外部系统前的基线。
      </div>
    </el-card>
  </div>
</template>

<style scoped>
.card-title {
  font-weight: 600;
}

.mb {
  margin-bottom: 16px;
}

.h-full {
  height: 100%;
}

.stat {
  text-align: center;
}

.stat-label {
  font-size: 13px;
  color: #909399;
}

.stat-value {
  font-size: 24px;
  font-weight: 600;
}

.stat-value.ok {
  color: #67c23a;
}

.stat-value.warn {
  color: #e6a23c;
}

.stat-value.muted-value {
  color: #909399;
}

.stat-note {
  font-size: 11px;
  color: #c0c4cc;
}

.sys-name {
  display: flex;
  align-items: center;
  gap: 5px;
  font-weight: 600;
  font-size: 13px;
}

.sys-full {
  font-size: 11px;
  color: #909399;
  margin-top: 2px;
}

.evidence {
  font-size: 12px;
  color: #67c23a;
  margin-bottom: 3px;
}

.note-text {
  font-size: 11px;
  color: #909399;
  line-height: 1.6;
}

.item-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.item {
  padding: 10px 12px;
  border-radius: 6px;
  border-left: 3px solid;
}

.item.done {
  background: #f0f9eb;
  border-color: #67c23a;
}

.item.todo {
  background: #fdf6ec;
  border-color: #e6a23c;
}

.item-name {
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 3px;
}

.item-detail {
  font-size: 12px;
  color: #606266;
  line-height: 1.7;
}

.item-collector {
  font-size: 11px;
  color: #909399;
  margin-top: 3px;
}

.scale-item {
  text-align: center;
  padding: 10px 4px;
  background: #f5f7fa;
  border-radius: 6px;
  margin-bottom: 10px;
}

.scale-value {
  font-size: 19px;
  font-weight: 600;
  font-family: 'Cascadia Mono', Consolas, monospace;
}

.scale-label {
  font-size: 11px;
  color: #909399;
  margin-top: 2px;
}

.note {
  font-size: 11px;
  color: #c0c4cc;
}
</style>
