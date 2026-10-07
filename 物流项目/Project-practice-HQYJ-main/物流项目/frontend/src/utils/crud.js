/**
 * 列表页 CRUD 的通用逻辑。
 *
 * 7 个基础数据页面（门店/线路/映射/车辆类型/车辆/司机/地形）的
 * 「加载列表 + 新建/编辑弹窗 + 删除确认」逻辑几乎一样，抽到这里，
 * 页面只负责列的渲染与表单字段。
 *
 * ★★ 使用方式必须是**顶层解构**：
 *
 *     const formRef = ref()
 *     const { rows, loading, load, openCreate, ... } = useCrud(...)
 *
 *     <el-table :data="rows" />
 *
 *   不要把返回值挂在 `const crud = useCrud(...)` 再写 `crud.rows` ——
 *   Vue 模板只对**顶层 setup 绑定**做 ref 自动解包，嵌套在普通对象里的
 *   ref 会原样传出去，`el-table` 收到 RefImpl 就会报 "rows is not iterable"。
 *   （这个坑踩过一次，写在这里免得再犯。）
 */

import { computed, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { withError, tryAction } from '@/utils/error'

/**
 * @param {object} endpoints
 *   list    () => Promise<Array>
 *   create  (payload) => Promise
 *   update  (id, payload) => Promise
 *   remove  (id) => Promise
 * @param {object} options
 *   formRef   Ref            ★ 必须由页面传入：模板 ref 只能绑定到页面自己声明的 ref
 *   blank     () => object        新建时的空表单
 *   toForm    (row) => object     把行数据转成表单数据
 *   nameOf    (row) => string     删除确认里显示的名字
 *   label     string              实体名，用于提示文案（如「门店」）
 */
export function useCrud(endpoints, options = {}) {
  const { list, create, update, remove } = endpoints
  const {
    formRef,
    blank = () => ({}),
    toForm = (row) => ({ ...row }),
    nameOf = (row) => row.name || row.code || row.id,
    label = '记录',
  } = options

  if (!formRef) {
    // 早失败好过静默失效：没有 formRef 时表单校验会被跳过
    throw new Error('useCrud 需要传入 formRef（页面里 const formRef = ref()）')
  }

  const loading = ref(false)
  const rows = ref([])
  const submitting = ref(false)
  const dialogVisible = ref(false)
  const editingId = ref(null)
  const form = ref(blank())

  const isEditing = computed(() => editingId.value !== null)
  const dialogTitle = computed(() =>
    isEditing.value ? `编辑${label}` : `新建${label}`,
  )

  async function load() {
    loading.value = true
    try {
      rows.value = (await withError(() => list())) || []
    } finally {
      loading.value = false
    }
  }

  function openCreate() {
    editingId.value = null
    form.value = blank()
    dialogVisible.value = true
  }

  function openEdit(row) {
    editingId.value = row.id
    form.value = toForm(row)
    dialogVisible.value = true
  }

  /** @returns {Promise<boolean>} 是否保存成功 */
  async function submit(extra = {}) {
    const valid = await formRef.value.validate().catch(() => false)
    if (!valid) return false

    submitting.value = true
    const payload = { ...form.value, ...extra }
    const { ok } = await tryAction(
      () =>
        isEditing.value
          ? update(editingId.value, payload)
          : create(payload),
      `${label}已${isEditing.value ? '更新' : '创建'}`,
    )
    submitting.value = false

    if (!ok) return false
    dialogVisible.value = false
    await load()
    return true
  }

  /** 删除前确认；返回是否真的删掉了 */
  async function confirmRemove(row, extraMessage = '') {
    try {
      await ElMessageBox.confirm(
        `确定删除${label}「${nameOf(row)}」？${extraMessage}`,
        '删除确认',
        { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
      )
    } catch {
      return false
    }

    const { ok } = await tryAction(() => remove(row.id))
    if (!ok) return false
    ElMessage.success(`${label}「${nameOf(row)}」已删除`)
    await load()
    return true
  }

  return {
    // 扁平返回，供页面顶层解构（见文件头的 ★★ 说明）
    loading,
    rows,
    submitting,
    dialogVisible,
    editingId,
    form,
    isEditing,
    dialogTitle,
    load,
    openCreate,
    openEdit,
    submit,
    confirmRemove,
  }
}
