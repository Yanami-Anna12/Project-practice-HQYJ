/**
 * 展示格式化：时间、状态标签配色、进度、定位。
 *
 * ★ 状态色一律走这里，页面里不许再写 if/else 判色 ——
 *   同一个「待完成」在任务卡、任务详情、工作台上必须是同一个颜色，
 *   散落三处迟早会出现同一状态两种颜色。
 */

/* ------------------------------------------------------------------ *
 * 时间
 * ------------------------------------------------------------------ */

/** 补齐两位 */
function pad(n) {
  return String(n).padStart(2, '0')
}

/** 把后端返回的时间（ISO 字符串 / 时间戳）格式化成 YYYY-MM-DD HH:mm */
export function formatDateTime(value, withSeconds = false) {
  if (!value) return '—'
  const text = String(value).replace('T', ' ')
  // 后端是 ISO 格式（2026-10-11T09:00:00），截断比 new Date() 更稳
  // （iOS 对 'YYYY-MM-DD HH:mm:ss' 的解析历史上不一致，不要依赖它）
  return withSeconds ? text.slice(0, 19) : text.slice(0, 16)
}

/** 只保留日期部分 YYYY-MM-DD */
export function formatDate(value) {
  if (!value) return '—'
  return String(value).replace('T', ' ').slice(0, 10)
}

/** 只保留时间部分 HH:mm */
export function formatTime(value) {
  if (!value) return '—'
  const text = String(value).replace('T', ' ')
  return text.slice(11, 16) || '—'
}

/** 今天 YYYY-MM-DD */
export function today() {
  const d = new Date()
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

/**
 * 当前（或指定）时间的 HH:mm，**按本地时区**。
 *
 * ★ 这个函数存在的唯一理由是一个实测踩到的坑：
 *   签到打卡写成了 `formatTime(new Date().toISOString())`。
 *   `toISOString()` 返回的是 **UTC**，东八区下 09:21 签到会显示成「已签到 01:21」——
 *   现场看到的是「时间不对」，会怀疑系统没记录成功。
 *   凡是要显示「现在几点」的地方都用这个，不要自己拼 toISOString()。
 */
export function nowClock(date) {
  const d = date || new Date()
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`
}

/** 当前（或指定）时间的 YYYY-MM-DD HH:mm:ss，**按本地时区**（提交给后端的时间戳用） */
export function nowDateTime(date) {
  const d = date || new Date()
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(
    d.getHours(),
  )}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

/** 相对时间：刚刚 / N 分钟前 / N 小时前 / N 天前 / 具体日期 */
export function fromNow(value) {
  if (!value) return '—'
  const target = new Date(String(value).replace(' ', 'T').slice(0, 19))
  if (Number.isNaN(target.getTime())) return formatDateTime(value)
  const diff = Date.now() - target.getTime()
  if (diff < 0) return formatDateTime(value)
  const minute = 60 * 1000
  const hour = 60 * minute
  const day = 24 * hour
  if (diff < minute) return '刚刚'
  if (diff < hour) return `${Math.floor(diff / minute)} 分钟前`
  if (diff < day) return `${Math.floor(diff / hour)} 小时前`
  if (diff < 7 * day) return `${Math.floor(diff / day)} 天前`
  return formatDate(value)
}

/**
 * 计划日期是否为今天 / 是否已过期。
 * ★ 现场人员最关心的是「今天要跑的」和「已经拖过期的」，
 *   所以这两个判断单独给出来，不要在页面里各写一遍字符串比较。
 */
export function isToday(value) {
  return formatDate(value) === today()
}

export function isPastDate(value) {
  const d = formatDate(value)
  if (d === '—') return false
  return d < today()
}

/* ------------------------------------------------------------------ *
 * 工单 / 子任务状态
 * ------------------------------------------------------------------ */

/** 子任务（作业任务）状态标签配色 */
export function taskStatusClass(status) {
  return (
    {
      待完成: 'tag-pending',
      巡检中: 'tag-running',
      已完成: 'tag-done',
      已取消: 'tag-planned',
    }[status] || 'tag-planned'
  )
}

/** 工单状态标签配色 */
export function orderStatusClass(status) {
  return (
    {
      待接单: 'tag-pending',
      待完成: 'tag-running',
      已完成: 'tag-done',
      已取消: 'tag-planned',
      已退回: 'tag-danger',
    }[status] || 'tag-planned'
  )
}

/** 工单时效标签配色（正常 / 紧急 / 逾期） */
export function timeStatusClass(timeStatus) {
  return (
    {
      正常: 'tag-planned',
      紧急: 'tag-warn',
      逾期: 'tag-danger',
    }[timeStatus] || 'tag-planned'
  )
}

/** 工单类型标签配色：巡视/特巡是计划内（蓝灰），消缺是故障衍生（橙），设备检查（蓝） */
export function orderTypeClass(orderType) {
  return (
    {
      巡视: 'tag-planned',
      特巡: 'tag-running',
      消缺: 'tag-warn',
      设备检查: 'tag-done',
      其他: 'tag-planned',
    }[orderType] || 'tag-planned'
  )
}

/* ------------------------------------------------------------------ *
 * 故障状态 / 等级
 * ------------------------------------------------------------------ */

/** 故障状态标签配色 */
export function faultStatusClass(status) {
  return (
    {
      待上报: 'tag-planned',
      待核查: 'tag-pending',
      核查通过: 'tag-done',
      核查驳回: 'tag-danger',
    }[status] || 'tag-planned'
  )
}

/**
 * 故障等级标签配色。
 * ★ 与后端 /faults/levels 给的 level_color 同一套语义：
 *   一般=绿、严重=橙、危急=红。等级是现场判断优先级的第一依据，必须醒目。
 */
export function faultLevelClass(level) {
  return (
    {
      一般: 'tag-done',
      严重: 'tag-warn',
      危急: 'tag-danger',
    }[level] || 'tag-planned'
  )
}

/** 等级对应的小圆点颜色（列表左侧色条用） */
export function faultLevelColor(level) {
  return (
    {
      一般: '#18a058',
      严重: '#d97706',
      危急: '#d03050',
    }[level] || '#8a9099'
  )
}

/**
 * SLA 是否已超期。
 * ★ 后端已经在卡片里算好 sla_overdue / sla_deadline，这里优先用后端的结论，
 *   只在没有该字段时（例如列表接口）才自己比时间，避免两端口径不一致。
 */
export function isSlaOverdue(item) {
  if (!item) return false
  if (typeof item.sla_overdue === 'boolean') return item.sla_overdue
  if (!item.sla_deadline) return false
  return new Date(String(item.sla_deadline).replace(' ', 'T')).getTime() < Date.now()
}

/* ------------------------------------------------------------------ *
 * 充电桩 / 站点
 * ------------------------------------------------------------------ */

/** 充电桩状态标签配色 */
export function pileStatusClass(status) {
  return (
    {
      运行: 'tag-done',
      故障: 'tag-danger',
      停用: 'tag-planned',
      离线: 'tag-warn',
    }[status] || 'tag-planned'
  )
}

/* ------------------------------------------------------------------ *
 * 数值
 * ------------------------------------------------------------------ */

/** 百分比（后端已算好两位小数时直接返回，避免再除一次） */
export function percentText(value) {
  if (value === null || value === undefined || value === '') return '0%'
  const n = Number(value)
  if (Number.isNaN(n)) return '0%'
  return `${Math.round(n * 10) / 10}%`
}

/** 进度百分比（分子/分母），分母为 0 时返回 0 */
export function progressPercent(done, total) {
  const t = Number(total) || 0
  const d = Number(done) || 0
  if (!t) return 0
  return Math.max(0, Math.min(100, Math.round((d / t) * 100)))
}

/** 图片地址补全：后端给的是 /static/... 相对路径，小程序里必须绝对地址 */
export function pickImages(list) {
  return Array.isArray(list) ? list.filter(Boolean) : []
}

/* ------------------------------------------------------------------ *
 * 定位
 * ------------------------------------------------------------------ */

/**
 * 取当前定位（巡检到店打卡、故障发生位置用）。
 *
 * ★ 失败必须能降级：现场经常在地下室/信号差的位置，
 *   定位拿不到不能把整个提交卡死 —— 返回 null，调用方照常提交，
 *   只是不带上经纬度，服务端这两个字段本来就是可选的。
 *
 * ★★ 必须自带兜底定时器（这是「整页按钮点不动」的根因）：
 *   `uni.getLocation` 的 `timeout` 参数**不是所有平台都实现**
 *   （微信小程序底层的 wx.getLocation 就没有这个参数），
 *   一旦 success / fail 都没被回调，这个 Promise 就**永不 settle** ——
 *   而调用方是 `uni.showLoading({ mask: true })` + `await`，
 *   表现就是**遮罩永远盖在页面上，页面里所有按钮全部点不动**，
 *   而且看起来完全不像是定位的问题。
 *   所以这里自己保证：最多等 timeoutMs，无论如何都 resolve 一次。
 */
export function getLocationSafe(timeoutMs = 6000) {
  return new Promise((resolve) => {
    if (typeof uni.getLocation !== 'function') {
      resolve(null)
      return
    }

    let settled = false
    const finish = (value) => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      resolve(value)
    }

    const timer = setTimeout(() => {
      console.warn('[location] 定位超时，按无定位继续（避免遮罩卡死页面）')
      finish(null)
    }, timeoutMs)

    try {
      uni.getLocation({
        type: 'gcj02',
        geocode: true,
        success: (res) => {
          finish({
            latitude: res.latitude,
            longitude: res.longitude,
            address: res.address || '',
          })
        },
        fail: (err) => {
          console.warn('[location] 定位失败，按无定位提交', err)
          finish(null)
        },
      })
    } catch (err) {
      // 某些平台/权限下 getLocation 会直接抛异常，同样不能让它把流程带走
      console.warn('[location] 调用 getLocation 异常', err)
      finish(null)
    }
  })
}

/** 把定位拼成一句人话（没有定位时返回空串） */
export function locationText(location) {
  if (!location) return ''
  const parts = []
  if (location.address) parts.push(location.address)
  if (location.latitude && location.longitude) {
    parts.push(`${Number(location.latitude).toFixed(5)}, ${Number(location.longitude).toFixed(5)}`)
  }
  return parts.join(' ')
}

/* ------------------------------------------------------------------ *
 * 页面参数解码
 * ------------------------------------------------------------------ */

/**
 * 安全地解码路由参数。
 *
 * ★ 为什么不能直接 `decodeURIComponent(options.x)`：
 *   拼 URL 时值被 encodeURIComponent 编过一次，而 uni-app 的 H5 路由
 *   会把整个 hash 再编一次（实测 URL 里是 `orderType=%25E5%25B7%25A1...`），
 *   小程序端则只编一次 —— 两端到达页面时的形态不同，没人能保证永远解一次就对。
 *   更危险的是：值里只要出现一个**单独的 %**（例如站名写成「1#桩 100%」），
 *   `decodeURIComponent` 就会抛 `URIError: URI malformed`；
 *   它是写在 onLoad 里的，一抛整个页面的数据加载就断了（页面看着在、什么都不能点）。
 *   所以统一走这里：解不出来就把原值返回，绝不让它抛。
 */
export function safeDecode(value) {
  if (value === undefined || value === null) return ''
  let text = String(value)
  // 最多解 3 轮，解到不再变化为止：各平台对 query 的解码次数并不一致 ——
  // 实测 H5 的路由会把整个 hash 再编一次（URL 里是 `orderType=%25E5%25B7%25A1...`），
  // 到达页面时要多解一次；小程序端只编过一次，解一次就够。
  // 与其猜平台，不如「解到不动为止」。中途解不出来（值里带孤立 %）就停在上一步。
  for (let i = 0; i < 3; i += 1) {
    if (!/%[0-9a-fA-F]{2}/.test(text)) break
    try {
      const next = decodeURIComponent(text)
      if (next === text) break
      text = next
    } catch (err) {
      break
    }
  }
  return text
}
