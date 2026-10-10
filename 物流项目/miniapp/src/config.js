/**
 * 运行时配置 —— 换后端地址只改这一个文件。
 *
 * ★ 优先级从高到低：
 *   1. 改本文件的 DEV_HOST / API_BASE（最直接，演示时常用，**两端都稳**）
 *   2. H5 构建时注入环境变量 VITE_API_BASE（H5 端由 Vite 静态替换）
 *
 * ★ 实测提醒：微信小程序端构建**不会**静态替换 VITE_API_BASE，
 *   所以小程序换后端地址请直接改下面的 DEV_HOST，然后重新构建。
 *
 * ★ 各端的默认值不一样，原因：
 *   · H5 开发：走 vite.config.js 的 /api 代理，用相对路径最省事，天然没有跨域；
 *   · 微信小程序：没有浏览器同源策略，必须写后端绝对地址（真机调试时
 *     要把 127.0.0.1 换成电脑的局域网 IP，并勾选「不校验合法域名」）；
 *   · App / 其他小程序：同样按绝对地址处理。
 */

// 后端服务地址（默认按 backend/.runtime_port 的默认端口 8000）
//
// ★★ 真机测试/真机调试必须改成**电脑的局域网 IP**，不能是 127.0.0.1：
//    手机上的 `127.0.0.1` 指的是手机自己，请求会直接失败（表现为登录转圈/网络错误）。
//    查本机 IP：`ipconfig`，找「以太网」那一栏的 IPv4 地址。
//    当前这台机器：以太网 192.168.50.209（网关 192.168.50.1）→ 手机连同一个 WiFi 即可。
//    ★ 换了网络（IP 变了）只需要改这一行 + 重新 `npm run build:mp-weixin`。
//    ★ 开发者工具里必须勾「详情 → 本地设置 → 不校验合法域名」，
//      否则微信会拦掉 http:// 的请求（真机预览同样是这个开关）。
const DEV_HOST = 'http://192.168.50.209:8000'

// 构建期环境变量。
// ★★ 绝对不要直接写 process.env.xxx ★★
//   微信小程序运行时不提供 Node 的 process 全局对象。直写会让产物里留下
//   `process.env.VITE_API_BASE` 这样的运行时表达式，小程序一加载就抛
//   ReferenceError: process is not defined —— 后果是 app.js 直接崩、
//   所有页面都注册不上，在开发者工具里表现为「页面未找到」
//   （<body is="wx://not-found">），而不是一条看得懂的错误。
//   H5 端因为 Vite 会静态替换掉这段，完全看不出问题，所以极易漏测。
//   这里统一用 typeof 保护：H5 下仍被静态替换成字面量，小程序下短路不报错。
const ENV_BASE =
  (typeof process !== 'undefined' && process.env && process.env.VITE_API_BASE) || ''

// 当前编译平台：用 uni-app 的条件编译在编译期裁剪，不依赖任何运行时全局对象。
// ★ 原实现用 process.env.UNI_PLATFORM，小程序端会因取不到值而退回 'h5'，
//   进而把接口地址错判成相对路径 —— 即使不崩，小程序也连不上后端。
let PLATFORM = 'mp-weixin'
// #ifdef H5
PLATFORM = 'h5'
// #endif

/** 是否使用相对路径：只有 H5 可以（走 Vite 代理或同源反向代理），小程序端必须绝对地址 */
const USE_PROXY = PLATFORM === 'h5'

/** 接口根地址（不含 /api 后缀，统一在 api/index.js 里拼） */
export const API_BASE = ENV_BASE || (USE_PROXY ? '' : DEV_HOST)

/** 上传后的照片地址前缀（后端把 backend/uploads 挂成了 /uploads 静态目录） */
export const UPLOAD_BASE = ENV_BASE || (USE_PROXY ? '' : DEV_HOST)

/**
 * WebSocket 地址前缀（实时推送用）。
 *
 * ★ 由 API_BASE 推导，不另开一个环境变量：接口和推送永远指向同一台后端，
 *   分成两个变量配，迟早有人只改一个，表现成「接口通、推送连不上」。
 *   推导规则就是 http → ws、https → wss。
 */
export const WS_BASE = (ENV_BASE || (USE_PROXY ? '' : DEV_HOST)).replace(/^http/i, 'ws')

/**
 * 拼一条 WebSocket 的完整地址。
 *
 * ★ 三端取址规则（对应上面的注释）：
 *   · 配了 VITE_API_BASE（绝对地址）→ 直接换成 ws/wss，两端都稳；
 *   · H5 开发（相对路径）→ 用当前页面的 host，走 vite.config.js 的 /api 代理
 *     （代理必须开 `ws: true`，否则 WebSocket 升级请求会被 Vite 当普通请求 404 掉）；
 *   · 微信小程序 → 没有 location，只能用 DEV_HOST 拼绝对地址
 *     （真机调试时把 DEV_HOST 改成电脑的局域网 IP，并在开发者工具里
 *      勾选「不校验合法域名」；正式发布必须换成 wss:// 且域名已备案）。
 */
export function wsUrl(path) {
  if (WS_BASE) return `${WS_BASE}${path}`
  if (PLATFORM === 'h5') {
    const loc = typeof location === 'undefined' ? null : location
    const proto = loc && loc.protocol === 'https:' ? 'wss:' : 'ws:'
    return `${proto}//${loc ? loc.host : '127.0.0.1:5173'}${path}`
  }
  return `${DEV_HOST.replace(/^http/i, 'ws')}${path}`
}

/** 请求超时（毫秒）。弱网下司机端要能等到，不能太快放弃 */
export const REQUEST_TIMEOUT = 20000

/**
 * 登录页的演示账号，一键填入用。
 *
 * ★ 三个角色都要有，否则现场演示「按角色分流」时要手打账号：
 *   · driver1 ~ driver8   司机     → 进「我的趟次」（确认接单 / 打卡）
 *     （seed 给**每个**司机档案都开了账号：D001→driver1 … D008→driver8）
 *   · dispatcher 调度员             → 进「今日看板」（只读，任务 + 异常）
 *   · admin 管理员                  → 也进「今日看板」（权限是 `*`，看板上的数字一样）
 *   · viewer 只读观察者             → 也进「今日看板」（有 scheduling:read，但没有写权限）
 *   admin 的密码来自 backend/.env 的 ADMIN_INIT_PASSWORD（默认 admin123）。
 *
 * ★ 列表顺序 = 登录页显示顺序：司机在前（现场主要演示司机端），
 *   管理端账号排最后。
 */
export const DEMO_ACCOUNTS = [
  { username: 'driver1', password: '123456', label: '司机一' },
  { username: 'driver2', password: '123456', label: '司机二' },
  { username: 'driver3', password: '123456', label: '司机三' },
  { username: 'driver4', password: '123456', label: '司机四' },
  { username: 'driver5', password: '123456', label: '司机五' },
  { username: 'driver6', password: '123456', label: '司机六' },
  { username: 'driver7', password: '123456', label: '司机七' },
  { username: 'driver8', password: '123456', label: '司机八' },
  { username: 'dispatcher', password: '123456', label: '调度员' },
  { username: 'admin', password: 'admin123', label: '管理员' },
  { username: 'viewer', password: '123456', label: '只读观察者' },
]

export default {
  API_BASE,
  UPLOAD_BASE,
  WS_BASE,
  wsUrl,
  REQUEST_TIMEOUT,
  DEMO_ACCOUNTS,
}
