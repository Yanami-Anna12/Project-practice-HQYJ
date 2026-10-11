<template>
  <div class="uploader">
    <a-upload
      v-model:file-list="fileList"
      list-type="picture-card"
      :multiple="true"
      :max-count="maxCount"
      :before-upload="beforeUpload"
      :custom-request="doUpload"
      accept="image/*"
      @remove="onRemove"
      @preview="onPreview"
    >
      <div v-if="fileList.length < maxCount">
        <PlusOutlined />
        <div style="margin-top: 4px; font-size: 12px">上传照片</div>
      </div>
    </a-upload>

    <div class="uploader-tip">
      支持 jpg/png/webp，单张不超过 {{ info.max_image_mb || 10 }}MB，最多 {{ maxCount }} 张
      <span v-if="uploading" class="text-muted">　上传中 {{ uploadingCount }} 张…</span>
    </div>

    <!-- 点击缩略图放大预览（原先挂了一个 v-if="false" 的 a-image，点了没反应） -->
    <a-modal
      v-model:open="previewVisible"
      :footer="null"
      :title="previewName"
      width="720px"
      centered
    >
      <img v-if="previewSrc" :src="previewSrc" alt="现场照片" class="uploader-preview-img" />
    </a-modal>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { message } from 'ant-design-vue'
import { PlusOutlined } from '@ant-design/icons-vue'
import { uploadApi } from '@/api'

const props = defineProps({
  /** v-model:value —— 已上传图片的 URL 数组 */
  value: { type: Array, default: () => [] },
  bizType: { type: String, default: 'inspection' },
  bizId: { type: String, default: undefined },
  maxCount: { type: Number, default: 12 },
})
const emit = defineEmits(['update:value'])

const fileList = ref([])
const uploadingCount = ref(0)
const previewVisible = ref(false)
const previewSrc = ref('')
const previewName = ref('')
const info = ref({ max_image_mb: 10, max_files_per_request: 12 })

const uploading = computed(() => uploadingCount.value > 0)

/* ------------------------------------------------------------------ *
 * 列表项 ↔ URL 的换算（本组件唯一真相来源）
 * ------------------------------------------------------------------ *
 * ★ 为什么不能只看 item.url（这里踩过一个把「上传图片」整个功能打死的坑）：
 *   a-upload 在 customRequest 成功后会执行一次内部的 onSuccess，它用
 *   `file2Obj(file)` 造一个**新对象**替换掉列表里原来那一项
 *   （见 ant-design-vue es/upload/Upload.js 的 onSuccess → updateFileList）。
 *   新对象只带 uid/name/size/type/status/percent/response/originFileObj，
 *   **我们事先挂在旧对象上的 url / thumbUrl 会被丢掉**。
 *   于是：卡片变成没有缩略图的空壳 → 紧接着 syncValue() 过滤掉没 url 的项
 *   发出 `[]` → props.value 变化的 watch 又拿 `[undefined]` 和 `[]` 一比不相等，
 *   直接把整个列表清空 —— 表现为「选了照片、转了一圈、照片没了」，
 *   而后端其实已经收到文件（POST 返回 200），所以极易被误判成接口问题。
 *
 *   结论：URL 一律通过 urlOf() 取，它同时认「我们补的 url」和
 *   「a-upload 自己写入的 response.urls」两条路，谁在都行。
 */
function urlOf(item) {
  if (!item) return ''
  if (item.url) return item.url
  const resp = item.response
  if (resp && Array.isArray(resp.urls) && resp.urls[0]) return resp.urls[0]
  return ''
}

function findItem(uid) {
  return fileList.value.find((f) => f.uid === uid)
}

/** 把当前列表里「已完成的图片地址」按顺序同步给 v-model */
function syncValue() {
  emit('update:value', fileList.value.map(urlOf).filter(Boolean))
}

/** 把外部传入的 URL 数组同步成图片卡片（避免重复添加） */
watch(
  () => props.value,
  (urls) => {
    const list = (urls || []).filter(Boolean)
    const current = fileList.value
      .filter((f) => f.status === 'done')
      .map(urlOf)
      .filter(Boolean)
    // 两边口径必须完全一致（都过滤空值），否则一次「多一个 undefined」的误判
    // 就会把用户刚选好、正在上传的卡片整批清掉。
    if (list.length === current.length && list.every((u, i) => u === current[i])) return

    fileList.value = list.map((url, i) => ({
      uid: `remote-${i}-${url}`,
      name: url.split('/').pop() || `photo-${i + 1}.jpg`,
      status: 'done',
      url,
      thumbUrl: url,
    }))
  },
  { immediate: true },
)

function beforeUpload(file) {
  const isImage = file.type?.startsWith('image/')
  if (!isImage) {
    message.error('只能上传图片文件')
    return false
  }
  const limitMb = info.value.max_image_mb || 10
  if (file.size / 1024 / 1024 > limitMb) {
    message.error(`图片「${file.name}」超过 ${limitMb}MB`)
    return false
  }
  return true
}

/**
 * 自定义上传：逐张调用 /uploads/images，拿到真实 URL。
 *
 * ★ 顺序是刻意安排的，不要调换（调换就是上面 urlOf 注释里描述的那个 bug）：
 *   1. 先调 onSuccess，让 a-upload 用它自己的新对象把列表项替换掉；
 *   2. 再按 uid 找回「替换后」的那一项，把 url / thumbUrl 补上去；
 *   3. 最后同步给父组件。
 *   本机实测：修改前上传成功但卡片消失、表单里 URL 为空；
 *   修改后卡片保留、缩略图正常、表单拿到 /static/data/uploads/... 地址。
 */
async function doUpload({ file, onSuccess, onError }) {
  uploadingCount.value += 1
  try {
    const res = await uploadApi.uploadImages([file], {
      bizType: props.bizType,
      bizId: props.bizId,
    })
    const url = res.data?.urls?.[0]
    if (!url) throw new Error('上传未返回地址')

    onSuccess?.(res.data)

    const target = findItem(file.uid)
    if (target) {
      target.status = 'done'
      target.url = url
      target.thumbUrl = url
    } else {
      // 兜底：万一 a-upload 没有回传替换后的列表（版本差异），
      // 就直接按远端卡片补一条，保证 URL 不丢。
      fileList.value = [
        ...fileList.value.filter((f) => f.uid !== file.uid),
        {
          uid: file.uid,
          name: file.name || url.split('/').pop(),
          status: 'done',
          url,
          thumbUrl: url,
        },
      ]
    }
    await nextTick()
    syncValue()
  } catch (e) {
    const target = findItem(file.uid)
    if (target) target.status = 'error'
    onError?.(e)
    message.error(`「${file.name}」上传失败：${e.message || '未知错误'}`)
  } finally {
    uploadingCount.value -= 1
  }
}

function onRemove() {
  // a-upload 在 onRemove 里是 Promise.then 之后才更新列表，等一拍再同步
  nextTick(() => syncValue())
}

function onPreview(file) {
  previewSrc.value = urlOf(file) || file.thumbUrl || ''
  previewName.value = file.name || '现场照片'
  previewVisible.value = true
}

onMounted(async () => {
  try {
    const res = await uploadApi.info()
    info.value = res.data || info.value
  } catch {
    /* 使用默认限制 */
  }
})
</script>

<style scoped>
.uploader-tip {
  font-size: 12px;
  color: #8c8c8c;
  margin-top: 4px;
  line-height: 1.7;
}
.uploader-preview-img {
  width: 100%;
  display: block;
}
</style>
