<script setup>
/**
 * 调度看板（登录后的落地页）。
 *
 * ★ 本页首版只做「能看出系统形态」的程度：
 *   车辆规模与趟次规则直接取自《需求文档》一.三「现有条件」，
 *   其余业务指标标注为「待接入」，不编造数值 —— 假数据比空着更容易误导。
 */
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { Van, Box, TakeawayBox, MagicStick } from '@element-plus/icons-vue'

const auth = useAuthStore()
const router = useRouter()

/** 现有条件（来源：需求文档 一.3） */
const fleet = [
  { type: '四米二', count: 28, min: 630, max: 800, trips: 2, split: '上午1 + 下午1', icon: Van, color: '#409eff' },
  { type: '大包', count: 3, min: 300, max: 420, trips: 2, split: '上午1 + 下午1', icon: Box, color: '#e6a23c' },
  { type: '小包', count: 9, min: 1, max: 300, trips: 4, split: '上午2 + 下午2', icon: TakeawayBox, color: '#67c23a' },
]

const totalVehicles = computed(() => fleet.reduce((s, f) => s + f.count, 0))
/** 理论日趟次上限：Σ(车辆数 × 每日趟次) */
const maxTrips = computed(() => fleet.reduce((s, f) => s + f.count * f.trips, 0))

/** 核心业务约束（来源：需求文档 一.4） */
const constraints = [
  { label: '发车规则', value: '达到最低装载量才发车' },
  { label: '时段规则', value: '上午门店上午送，下午门店下午送' },
  { label: '地形规则', value: '普通 / 中控 / 严控 × 全能去 / 大小包能去 / 小包能去' },
  { label: '线路规则', value: '门店与线路多对多，部分门店处于多线路交界' },
  { label: '货量不足', value: '优先保障大包、小包日出车次数' },
  { label: '车型优先', value: '多种派车方案优先用四米二' },
  { label: '动态调节', value: '不保障每天 28 / 3 / 9 台满勤' },
]

/** 规划中的看板（来源：需求文档 二.5） */
const plannedBoards = [
  '车辆出勤看板',
  '趟次达成看板',
  '装载率看板',
  '门店配送达成',
  '线路覆盖',
  '车型使用',
  '成本分析',
  '方案对比',
  '大包/小包保障达成',
  '四米二使用率',
  '动态车辆调节分析',
]

/** 智能调度 Agent 工作流（来源：需求文档 四.1） */
const workflow = [
  'load_task 加载任务',
  'data_perception 数据感知',
  'constraint_parse 约束解析',
  'rule_validation 规则校验',
  'plan_generation 生成多方案',
  'plan_scoring 方案评分',
  'plan_explanation 方案解释',
  'human_confirmation 人工确认',
  'dispatch_execution 下发执行',
  'report_generation 生成报告',
]

const quickLinks = [
  { title: '用户管理', path: '/system/users', permission: 'users:read' },
  { title: '角色管理', path: '/system/roles', permission: 'roles:read' },
  { title: '权限管理', path: '/system/permissions', permission: 'permissions:read' },
  { title: '字典管理', path: '/system/dicts', permission: 'dicts:read' },
  { title: '参数管理', path: '/system/params', permission: 'params:read' },
  { title: '日志管理', path: '/system/logs', permission: 'logs:read' },
]
</script>

<template>
  <div class="page-container">
    <div class="page-header">
      <div>
        <h2 class="page-title">调度看板</h2>
        <p class="page-desc">
          欢迎，{{ auth.user?.nickname }}。当前账号角色：
          <el-tag v-for="n in auth.roleNames" :key="n" size="small" effect="plain" class="mr">{{ n }}</el-tag>
        </p>
      </div>
    </div>

    <!-- 车辆规模 -->
    <el-row :gutter="16">
      <el-col v-for="f in fleet" :key="f.type" :xs="24" :sm="8">
        <el-card shadow="never" class="stat-card">
          <div class="stat-main">
            <el-icon :size="34" :color="f.color"><component :is="f.icon" /></el-icon>
            <div>
              <div class="stat-label">{{ f.type }}</div>
              <div class="stat-value">
                {{ f.count }}<span class="unit">台</span>
              </div>
            </div>
          </div>
          <div class="stat-meta">
            <div>装载量 {{ f.min }} – {{ f.max }}</div>
            <div>日 {{ f.trips }} 趟（{{ f.split }}）</div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 汇总 -->
    <el-row :gutter="16" class="mt">
      <el-col :xs="24" :sm="8">
        <el-card shadow="never" class="sum-card">
          <div class="sum-label">车辆总数</div>
          <div class="sum-value">{{ totalVehicles }}<span class="unit">台</span></div>
          <div class="sum-note">四米二 28 + 大包 3 + 小包 9</div>
        </el-card>
      </el-col>
      <el-col :xs="24" :sm="8">
        <el-card shadow="never" class="sum-card">
          <div class="sum-label">理论日趟次上限</div>
          <div class="sum-value">{{ maxTrips }}<span class="unit">趟</span></div>
          <div class="sum-note">28×2 + 3×2 + 9×4，实际按动态车辆调节</div>
        </el-card>
      </el-col>
      <el-col :xs="24" :sm="8">
        <el-card shadow="never" class="sum-card">
          <div class="sum-label">今日调度任务</div>
          <div class="sum-value pending">待接入</div>
          <div class="sum-note">需接入后端与求解器后展示</div>
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="16" class="mt">
      <!-- 核心业务约束 -->
      <el-col :xs="24" :lg="12">
        <el-card shadow="never">
          <template #header>
            <span class="card-title">核心业务约束</span>
          </template>
          <el-descriptions :column="1" border size="small">
            <el-descriptions-item v-for="c in constraints" :key="c.label" :label="c.label">
              {{ c.value }}
            </el-descriptions-item>
          </el-descriptions>
          <div class="source-note">来源：需求文档 一.4</div>
        </el-card>
      </el-col>

      <!-- 规划看板 -->
      <el-col :xs="24" :lg="12">
        <el-card shadow="never">
          <template #header>
            <span class="card-title">报表与看板（规划中）</span>
          </template>
          <div class="board-tags">
            <el-tag v-for="b in plannedBoards" :key="b" size="small" effect="plain" class="mr">
              {{ b }}
            </el-tag>
          </div>
          <el-alert type="info" :closable="false" class="mt">
            <template #title>
              这些看板需要调度任务与执行回传数据，属于后续模块。
              当前可在「智能调度 Agent → 调度任务」查看规划的页面入口。
            </template>
          </el-alert>
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="16" class="mt">
      <!-- 工作流 -->
      <el-col :xs="24" :lg="14">
        <el-card shadow="never">
          <template #header>
            <span class="card-title">
              <el-icon><MagicStick /></el-icon>
              智能调度 Agent 工作流
            </span>
          </template>
          <div class="flow">
            <div v-for="(step, i) in workflow" :key="step" class="flow-step">
              <span class="flow-index">{{ i + 1 }}</span>
              <span class="flow-text">{{ step }}</span>
            </div>
          </div>
          <div class="source-note">来源：需求文档 四.1（LangGraph 节点）</div>
        </el-card>
      </el-col>

      <!-- 快捷入口 -->
      <el-col :xs="24" :lg="10">
        <el-card shadow="never">
          <template #header>
            <span class="card-title">系统管理快捷入口</span>
          </template>
          <div class="quick-links">
            <el-button
              v-for="l in quickLinks"
              :key="l.path"
              v-permission="l.permission"
              class="quick-btn"
              @click="router.push(l.path)"
            >
              {{ l.title }}
            </el-button>
          </div>
          <el-alert v-if="!auth.has('users:read')" type="warning" :closable="false" class="mt">
            <template #title>
              当前账号没有系统管理权限，所以侧边栏不会出现「系统管理」分组。
              这是权限驱动的菜单裁剪，不是页面出错。
            </template>
          </el-alert>
          <div v-else class="source-note">
            按钮受 <code class="perm-code">v-permission</code> 指令控制，无权限时直接不渲染。
          </div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<style scoped>
.stat-card {
  margin-bottom: 16px;
}

.stat-main {
  display: flex;
  align-items: center;
  gap: 14px;
}

.stat-label {
  font-size: 13px;
  color: #909399;
}

.stat-value {
  font-size: 26px;
  font-weight: 600;
  line-height: 1.2;
}

.unit {
  font-size: 13px;
  font-weight: 400;
  color: #909399;
  margin-left: 3px;
}

.stat-meta {
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px dashed #e4e7ed;
  font-size: 12px;
  color: #606266;
  line-height: 1.9;
}

.sum-card {
  margin-bottom: 16px;
  text-align: center;
}

.sum-label {
  font-size: 13px;
  color: #909399;
}

.sum-value {
  font-size: 28px;
  font-weight: 600;
  margin: 4px 0;
}

.sum-value.pending {
  font-size: 18px;
  color: #e6a23c;
}

.sum-note {
  font-size: 12px;
  color: #909399;
  line-height: 1.6;
}

.card-title {
  font-weight: 600;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.board-tags {
  display: flex;
  flex-wrap: wrap;
}

.source-note {
  margin-top: 10px;
  font-size: 11px;
  color: #c0c4cc;
}

.flow {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.flow-step {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  background: #f5f7fa;
  border-radius: 4px;
  font-size: 13px;
}

.flow-index {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: #409eff;
  color: #fff;
  font-size: 11px;
  flex-shrink: 0;
}

.flow-text {
  font-family: 'Cascadia Mono', Consolas, monospace;
  font-size: 12px;
  color: #303133;
}

.quick-links {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.quick-btn {
  margin-left: 0;
}
</style>
