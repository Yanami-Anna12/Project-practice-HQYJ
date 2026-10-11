/**
 * 运行时配置 —— 换后端地址只改这一个文件。
 *
 * ★ 各端默认值不一样，原因：
 *   · H5 开发：走 vite.config.js 的 /api、/static 代理，用相对路径最省事，天然没有跨域；
 *   · 微信小程序：没有浏览器同源策略，必须写后端绝对地址（真机调试要把 127.0.0.1
 *     换成电脑的局域网 IP，并在开发者工具里勾「不校验合法域名」）。
 */

// 后端服务地址（默认对应 backend/.runtime_port 的默认端口 8010）
//
// ★★ 真机测试/真机调试必须改成**电脑的局域网 IP**，不能是 127.0.0.1：
//    手机上的 `127.0.0.1` 指的是手机自己，请求会直接失败（表现为登录转圈/网络错误）。
//    查本机 IP：`ipconfig`，找「以太网」那一栏的 IPv4 地址。
//    当前这台机器：以太网 192.168.1.4
//    ★ 本机还有 VMware/VirtualBox/Hyper-V 的虚拟网卡（192.168.80.1 / 192.168.6.1 /
//      192.168.56.1 / 172.27.0.1），**不要用那些地址**，手机连不上；认「以太网」那块。
//    ★ 后端要绑 0.0.0.0 手机才连得上：`python run.py --host 0.0.0.0`
const DEV_HOST = 'http://192.168.1.4:8010'

// 构建期环境变量。
// ★★ 绝对不要直接写 process.env.xxx ★★
//   微信小程序运行时不提供 Node 的 process 全局对象。直写会让产物里留下
//   `process.env.VITE_API_BASE` 这样的运行时表达式，小程序一加载就抛
//   ReferenceError: process is not defined —— 后果是 app.js 直接崩、
//   所有页面都注册不上，在开发者工具里表现为「页面未找到」而不是一条看得懂的错误。
//   H5 端因为 Vite 会静态替换掉这段，完全看不出问题，所以极易漏测。
const ENV_BASE =
  (typeof process !== 'undefined' && process.env && process.env.VITE_API_BASE) || ''

// 当前编译平台：用 uni-app 的条件编译在编译期裁剪，不依赖任何运行时全局对象。
let PLATFORM = 'mp-weixin'
// #ifdef H5
PLATFORM = 'h5'
// #endif

/** 是否使用相对路径：只有 H5 可以（走 Vite 代理），小程序端必须绝对地址 */
const USE_PROXY = PLATFORM === 'h5'

/** 接口根地址（不含 /api/v1 后缀，统一在 api/index.js 里拼） */
export const API_BASE = ENV_BASE || (USE_PROXY ? '' : DEV_HOST)

/**
 * 上传照片 / 静态资源的地址前缀。
 * ★ 后端把 backend/data 挂在了 /static/data 上，上传接口返回的 url 形如
 *   `/static/data/uploads/202610/xxx.jpg`，这是**相对路径**：
 *   小程序里 <image src> 必须是绝对地址，相对路径显示不出来，所以要拼前缀。
 */
export const STATIC_BASE = ENV_BASE || (USE_PROXY ? '' : DEV_HOST)

/**
 * WebSocket 地址前缀（消息中心未读推送）。
 * ★ 由 API_BASE 推导，不另开一个环境变量：接口和推送永远指向同一台后端，
 *   分成两个变量配，迟早有人只改一个，表现成「接口通、推送连不上」。
 */
export const WS_BASE = (ENV_BASE || (USE_PROXY ? '' : DEV_HOST)).replace(/^http/i, 'ws')

/**
 * 拼一条 WebSocket 的完整地址。
 *   · 配了 VITE_API_BASE（绝对地址）→ 直接换成 ws/wss，两端都稳；
 *   · H5 开发（相对路径）→ 用当前页面的 host，走 vite.config.js 的 /api 代理
 *     （代理必须开 `ws: true`，否则升级请求会被 Vite 当普通请求 404 掉）；
 *   · 微信小程序 → 没有 location，只能用 DEV_HOST 拼绝对地址。
 */
export function wsUrl(path) {
  if (WS_BASE) return `${WS_BASE}${path}`
  if (PLATFORM === 'h5') {
    const loc = typeof location === 'undefined' ? null : location
    const proto = loc && loc.protocol === 'https:' ? 'wss:' : 'ws:'
    return `${proto}//${loc ? loc.host : '127.0.0.1:5190'}${path}`
  }
  return `${DEV_HOST.replace(/^http/i, 'ws')}${path}`
}

/** 当前编译平台（页面里判断 H5/小程序 用，不要读 process.env.UNI_PLATFORM） */
export const PLATFORM_NAME = PLATFORM

/** 请求超时（毫秒）。弱网下现场人员要能等到，不能太快放弃 */
export const REQUEST_TIMEOUT = 20000

/**
 * 登录页的演示账号，一键填入用。
 *
 * ★ 四个内置角色各一个，覆盖「现场作业端」与「管理端」两种落地形态：
 *   · inspector      运维人员   个人数据 —— 接单、巡检录入、故障上报（现场主力）
 *   · station_admin  站点管理员 站点数据 —— 本站点工单与故障、故障核查
 *   · project_admin  项目管理员 项目数据 —— 全项目视图
 *   · admin          平台管理员 平台数据 —— 全部数据与系统管理
 *   （密码来自 seed.py / backend/.env，admin 默认 admin123，其余 123456）
 */
export const DEMO_ACCOUNTS = [
  { username: 'inspector', password: '123456', label: '运维人员', scope: '个人数据' },
  { username: 'station_admin', password: '123456', label: '站点管理员', scope: '站点数据' },
  { username: 'project_admin', password: '123456', label: '项目管理员', scope: '项目数据' },
  { username: 'admin', password: 'admin123', label: '平台管理员', scope: '平台数据' },
]

export default {
  API_BASE,
  STATIC_BASE,
  WS_BASE,
  wsUrl,
  PLATFORM_NAME,
  REQUEST_TIMEOUT,
  DEMO_ACCOUNTS,
}
