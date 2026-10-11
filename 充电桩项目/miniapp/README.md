# 充电桩运维 · 移动作业端（小程序）

> 充电桩运维管理 AI Agent 平台的手机端：**运维人员现场作业** + **管理者掌上看板**。
> 技术栈与物流项目小程序一致：uni-app + Vue 3 + Vite，编译到 **H5** 与 **微信小程序**。

---

## 1. 这个端解决什么真实场景

网页端（`../frontend`）是坐在办公室用的，信息密度大、字段全；但充电桩运维的活
**发生在桩旁边**：站在充电站里掏手机拍两张照片就得把故障报上去，蹲在桩前逐项打勾做巡检。
所以这个小程序不是把网页端缩小，而是按现场动作重排了一遍：

| 现场动作 | 小程序里的入口 | 走的接口 |
|---|---|---|
| 「我今天要去哪几个站？」 | 工作台 → 待办作业任务 | `GET /work-orders/subtasks/mine` |
| 「到了，开始干活」 | 任务详情 → 开始巡检（状态推到「巡检中」） | `PUT /work-orders/subtasks/{id}` |
| 「一项一项检查」 | 巡检情况录入（分类勾选 + 异常备注 + 多图 + 定位打卡） | `GET /work-orders/inspections/template`、`POST /work-orders/inspections` |
| 「这个桩坏了，赶紧报」 | 扫码查桩报修 / 故障上报（AI 先看一眼） | `GET /faults/piles/options`、`POST /ai/fault/diagnose`、`POST /faults` |
| 「我报的有没有人管？」 | 工作台 → 我上报的故障 | `GET /faults?mine=true` |
| 「站长核查一下」 | 故障详情 → 故障核查 | `POST /faults/{id}/verify` |
| 「今天整体什么情况？」 | 掌上看板（管理端首页） | `GET /statistics/dashboard`、`GET /admin/piles/status-summary` |
| 「工单派下去了没人接」 | 工单管理 → 接受 / 退回 | `POST /work-orders/{id}/accept`、`/reject` |

★ **没有为小程序新增任何后端接口** —— 上面每一个都是网页端已在用的接口。
这样手机端和网页端永远是同一套业务口径，不会出现「两边看到的数字不一样」。

---

## 2. 两类角色、两套入口

登录后按**数据权限**（`data_scope`）自动分流，底部导航的条目也完全不同：

| 数据权限 | 典型账号 | 落地页 | 底部导航 |
|---|---|---|---|
| 个人数据 | `inspector` 运维人员 | 运维工作台 | 工作台 / 任务 / 故障 / 消息 / 我的 |
| 站点数据 | `station_admin` 站点管理员 | 掌上看板 | 看板 / 工单 / 故障 / 消息 / 我的 |
| 项目数据 | `project_admin` 项目管理员 | 掌上看板 | 同上 |
| 平台数据 | `admin` 平台管理员 | 掌上看板 | 同上 |

★ 为什么用数据权限而不是角色码分流：角色是后台可配置的（能新建角色、改权限），
写死 `inspector` 这种角色码，一旦有人新建了「外委运维」角色就会漏判。
数据权限是后端做数据过滤的最终依据（`app/core/deps.py` 的 `apply_data_scope`），
前端按同一依据分流，才不会出现「前端放你进去、后端只返回空列表」的页面。

★ 底部导航是**自绘组件**（`components/BottomNav.vue`），不是 `pages.json` 的 tabBar：
小程序 tabBar 是静态配置，条目数量与 `pagePath` 编译期就定死，运行时改不了，
两类角色硬塞进同一组位置必然多出没权限的入口。

---

## 3. 怎么跑

```bash
# 1) 先起后端（端口 8010）
cd ../backend && python run.py

# 2) 装依赖（★ 本机一律用 npm，pnpm 装出来的 node_modules 会缺包）
npm install --registry=https://registry.npmmirror.com

# 3) H5 调试（推荐，浏览器里直接看）
npm run dev:h5
#   → 首选端口 5190，被占或被 Windows 保留段挡住时自动顺延，
#     实际端口写在本目录的 .runtime_port
#   → 打开 http://127.0.0.1:5190

# 4) 微信小程序
npm run build:mp-weixin
#   → 开发者工具导入 dist/build/mp-weixin
#   → 必须勾「详情 → 本地设置 → 不校验合法域名」
```

真机测试（三件套，缺一不可）：

1. `src/config.js` 的 `DEV_HOST` 改成**电脑的局域网 IP**（本机是 `192.168.1.4:8010`），
   改完要重新 `npm run build:mp-weixin`；
2. 后端绑 `0.0.0.0` 起：`python run.py --host 0.0.0.0`；
3. 开发者工具勾「不校验合法域名」，手机和电脑在同一个 WiFi/网段。

AppID 不进仓库：`src/manifest.json` 里是占位符 `touristappid`，
真实 AppID 放在本目录的 `.appid`（一行纯文本，已 gitignore），
构建前由 `scripts/inject-appid.mjs` 自动注入，构建后还原。

---

## 4. 目录结构

```
src/
├── config.js              后端地址、演示账号、平台判断（★ 换后端只改这里）
├── api/index.js           全部接口（页面只 import 这个，不直接碰 uni.request）
├── utils/
│   ├── request.js         uni.request / uni.uploadFile 封装（统一拆 {code,message,data}）
│   ├── storage.js         token / user / 权限画像
│   ├── socket.js          未读推送（★ H5 拿不到 SocketTask 时自动退化为定时刷新）
│   ├── ui.js              角色分流、底部导航条目、未读红点、错误文案
│   └── format.js          时间、状态配色、进度、定位
├── components/BottomNav.vue
└── pages/
    ├── login/login        登录（一键填入四个演示账号）
    ├── home/index         运维工作台（现场作业端首页）
    ├── tasks/index        我的作业任务
    ├── tasks/detail       作业任务详情（开始巡检 / 回看巡检记录）
    ├── inspect/form       巡检情况录入（分类勾选 + 异常备注 + 多图 + 定位打卡）
    ├── fault/index        故障管理（SLA 超期提醒）
    ├── fault/report       故障上报（级联选择 + AI 辅助诊断 + 多图 + 定位）
    ├── fault/detail       故障详情 + 核查
    ├── scan/scan          扫码查桩报修（H5 无摄像头时自动降级为手动输码）
    ├── board/index        掌上看板（管理端首页）
    ├── board/orders       工单管理（接受 / 退回 / 展开作业任务）
    ├── board/piles        充电桩状态（运行 / 故障 / 停用、过保提醒）
    ├── messages/index     消息中心（8 类筛选 + 未读红点 + 实时推送）
    └── messages/detail    消息详情 + 关联单据跳转
```

---

## 5. 踩过的坑（改这个端之前先看）

1. **绝对不能写裸 `process.env`**。微信小程序运行时没有 `process`，产物里留下
   `process.env.XXX` 会让 `app.js` 一加载就 `ReferenceError`，表现为
   「页面未找到」而不是一条看得懂的错误。要判断平台请用 `@/config` 的 `PLATFORM_NAME`。
   每次 `build:mp-weixin` 后自查一遍：
   `Select-String -Path "dist\build\mp-weixin\**\*.js" -Pattern "process\.env"`
2. **后端返回的图片地址是相对路径**（`/static/data/uploads/...`）。
   H5 端因为走了 Vite 代理看起来正常，**微信端不补绝对前缀就是一张空白图**，
   所以一律要用 `api.absoluteUrl()`。
3. **上传接口的字段名是 `files`（复数）**，不是 `file`；写错后端返回 422 参数校验失败。
4. **`uni.getLocation` 必须能失败**。地下室、弱信号下拿不到定位是常态，
   `getLocationSafe()` 拿不到就返回 `null`，提交照常进行（后端这两个字段本来就是可选的），
   绝不能因为定位失败把整个巡检提交卡死。
5. **H5 端 `uni.connectSocket` 不返回 SocketTask**，实时推送在浏览器里不可用。
   `utils/socket.js` 已经封好了：拿不到任务对象就退化成 30 秒轮询未读数，
   用户看到的效果一样（红点会亮）。**要现场演示「实时推送」，只能用微信开发者工具。**
6. **H5 端没有摄像头**，`uni.scanCode` 不可用。扫码页已按 `PLATFORM_NAME` 自动降级为手动输入资产码。
7. **不要用 `new Date('2026-10-11 09:00:00')`**：iOS 上这个格式解析结果不一致，
   时间处理一律走 `utils/format.js`（都是字符串切片，不依赖 Date 解析）。
8. **`uni.showModal` 的 `editable: true`** 在 H5 与微信端都能拿到输入内容
   （退回工单要填原因），但拿不到时要兜底提示，不能把空原因提交上去。

---

## 6. 演示账号

| 账号 | 密码 | 角色 | 数据权限 |
|---|---|---|---|
| `inspector` | `123456` | 运维人员 | 个人数据 |
| `station_admin` | `123456` | 站点管理员 | 站点数据 |
| `project_admin` | `123456` | 项目管理员 | 项目数据 |
| `admin` | `admin123` | 平台管理员 | 平台数据 |

登录页可以点击卡片一键填入。
