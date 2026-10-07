<script setup>
/**
 * 附件管理。
 *
 * ★ 首版不做真实文件上传：点击「上传附件」选择本地文件后，只把文件的
 *   名称/类型/大小登记成一条记录。接真实后端时应改为
 *   POST /api/attachments（multipart/form-data），本页其余逻辑不用改。
 *
 * ★ 这里刻意把这一点在界面上写明，避免误以为文件真的存到了服务端。
 */
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh, UploadFilled, Download, Delete } from '@element-plus/icons-vue'
import * as api from '@/api'
import { withError, tryAction } from '@/utils/error'
import { formatTime, formatSize } from '@/utils/table'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const canManage = computed(() => auth.has('attachments:manage'))

const loading = ref(false)
const rows = ref([])
const keyword = ref('')
const bizType = ref('')

const bizTypes = computed(() => [...new Set(rows.value.map((r) => r.biz_type))])

async function load() {
  loading.value = true
  try {
    rows.value =
      (await withError(() =>
        api.fetchAttachments({ keyword: keyword.value, biz_type: bizType.value }),
      )) || []
  } finally {
    loading.value = false
  }
}

/* ---------------- 登记上传 ---------------- */
const fileInput = ref(null)

function pickFile() {
  fileInput.value?.click()
}

async function onFileChange(event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  if (!file) return

  const { ok } = await tryAction(
    () => api.registerAttachment({ name: file.name, biz_type: '未分类', size: file.size }),
    `已登记附件「${file.name}」（演示模式，未真正上传）`,
  )
  if (ok) await load()
}

async function remove(row) {
  try {
    await ElMessageBox.confirm(`确定删除附件记录「${row.name}」？`, '删除确认', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  const { ok } = await tryAction(() => api.deleteAttachment(row.id))
  if (ok) await load()
}

function download(row) {
  ElMessage.info(`演示模式不提供真实下载：${row.name}`)
}

/** 按业务类型着色 */
function typeTag(t) {
  const map = {
    技术方案: 'primary',
    需求资料: 'success',
    导入模板: 'warning',
    导出结果: 'info',
    调度报告: 'danger',
  }
  return map[t] || ''
}

onMounted(load)
</script>

<template>
  <div class="page-container">
    <div class="page-header">
      <div>
        <h2 class="page-title">附件管理</h2>
        <p class="page-desc">
          管理技术方案、需求资料、导入模板、调度报告等附件。
          <strong>首版为演示模式</strong>：只登记文件的名称与大小，不会真正上传到服务器。
        </p>
      </div>
      <div class="actions">
        <el-input
          v-model="keyword"
          placeholder="搜索文件名"
          clearable
          style="width: 180px"
          @keyup.enter="load"
          @clear="load"
        />
        <el-select v-model="bizType" placeholder="全部类型" clearable style="width: 140px" @change="load">
          <el-option v-for="t in bizTypes" :key="t" :label="t" :value="t" />
        </el-select>
        <el-button :icon="Refresh" @click="load">刷新</el-button>
        <el-button v-if="canManage" type="primary" :icon="UploadFilled" @click="pickFile">
          上传附件
        </el-button>
        <!-- 隐藏的文件选择器：演示模式下只读取文件元信息 -->
        <input ref="fileInput" type="file" class="hidden-input" @change="onFileChange" />
      </div>
    </div>

    <el-card shadow="never">
      <el-table v-loading="loading" :data="rows" stripe>
        <el-table-column prop="id" label="ID" width="60" />
        <el-table-column label="文件名" min-width="280">
          <template #default="{ row }">
            <div class="file-name">
              <el-icon color="#409eff"><Download /></el-icon>
              <span>{{ row.name }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="业务类型" width="120">
          <template #default="{ row }">
            <el-tag :type="typeTag(row.biz_type)" size="small" effect="plain">
              {{ row.biz_type }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="大小" width="110">
          <template #default="{ row }">{{ formatSize(row.size) }}</template>
        </el-table-column>
        <el-table-column prop="uploader" label="上传者" width="120">
          <template #default="{ row }">
            <span class="perm-code">{{ row.uploader }}</span>
          </template>
        </el-table-column>
        <el-table-column label="上传时间" width="170">
          <template #default="{ row }">{{ formatTime(row.uploaded_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="150" fixed="right">
          <template #default="{ row }">
            <el-button size="small" type="primary" link @click="download(row)">下载</el-button>
            <el-button
              v-if="canManage"
              size="small"
              type="danger"
              link
              :icon="Delete"
              @click="remove(row)"
            >
              删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!loading && !rows.length" description="没有匹配的附件" />
    </el-card>

    <el-alert type="info" :closable="false" class="mt">
      <template #title>
        上传会写入审计日志，所以上传后到「日志管理」页刷新，能看到
        <code class="perm-code">attachment.upload</code> 记录。
      </template>
    </el-alert>
  </div>
</template>

<style scoped>
.actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  align-items: center;
}

.file-name {
  display: flex;
  align-items: center;
  gap: 6px;
}

.hidden-input {
  display: none;
}
</style>
