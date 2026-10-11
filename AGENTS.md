# 项目实践 · 交接说明

> **新会话开场只要说一句：「先读 AGENTS.md，然后……」** 下面的背景不用再复述。

---

## 1. 仓库概况

单个 git 仓库，remote 名字叫 **`main`**（不是 `origin`）：
`https://github.com/Yanami-Anna12/Project-practice-HQYJ`

| 目录 | 是什么 | 技术栈 |
|---|---|---|
| `物流项目/` | 车辆智能调度 Agent | FastAPI + SQLAlchemy 2.0 + Vue3；MySQL（连不上自动回退 SQLite） |
| `物流项目/miniapp/` | 司机端 + 管理端**小程序** | uni-app + Vue3（编译到 H5 / 微信小程序） |
| `充电桩项目/` | 充电桩运维管理 AI Agent 平台 | FastAPI + Vue3；SQLite（零配置） |
| `充电桩项目/miniapp/` | 运维人员 + 管理员**小程序** | uni-app + Vue3（编译到 H5 / 微信小程序） |
| 各项目下的 `答辩PPT/` | 答辩 PPTD 源 + 答辩稿 | — |

---

## 2. 本机环境（已确认，不要再查）

| 项 | 值 |
|---|---|
| Python | `D:\miniconda3\envs\py312\python.exe`（依赖齐全，含 ortools/langgraph/pymysql/jose）★ **这台机器的 conda 在 D 盘**，`C:\Users\12966\...` 那套是上一台机器的，已不存在 |
| node / npm | `D:\nodejs\node.exe` v24.9 / `D:\nodejs\npm.cmd` 10.9（★ 已不是 `C:\nvm4w\...`） |
| pnpm | 存在且能跑（10.34.5），但**前端依赖一律用 npm 装**：pnpm 装出来的 `node_modules` 会缺包（vite 报缺 picomatch）；`pnpm run dev` 只是当脚本运行器用，可以 |
| MySQL | 8.0 已运行（127.0.0.1:3306），库 `logistics_db`，凭据在 `物流项目/backend/.env`（★ 本机 mysql.exe 在 `C:\Program Files\MySQL\MySQL Server 8.0\bin`） |
| Edge | `C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe`，可无头截图验证页面（playwright-core 传 `executablePath`） |
| 局域网 IP | **`192.168.1.4`**（网卡名「以太网 3」）—— 小程序模拟器/真机都认这个。★ 本机另有一堆虚拟网卡（`192.168.80.1`、`192.168.6.1` VMware，`192.168.56.1` VirtualBox，`172.27.0.1` Hyper-V，`10.126.126.1`），**手机连不上，别填**。`miniapp/src/config.js` 的 `DEV_HOST` 已改成本机 IP（原来写的是上一台机器的 `192.168.50.209`），改完必须重新 `npm run build:mp-weixin` |
| 端口 | **首选值与实际值可能不同**（本机 Windows 保留段 5041–5240 把 5173/5175/5185 全挡了，见坑 16）：物流 后端 8000 / web 5175→实际 **5250** / 小程序 H5 5173→实际 **5260**；充电桩 后端 8010 / web 5185（★ 2026-10-11 实测又能用了）/ 小程序 H5 首选 **5190**。实际值看窗口里的 Local 地址，或各前端目录下的 `.runtime_port` |
| 本机 ps1 坑 | DSH 的 `pwsh` 实际调的是 **Windows PowerShell 5.1**：无 BOM 的 UTF-8 `.ps1` 会被按 ANSI 解析，中文注释能把引号吃掉 → 带中文的 `.ps1` 一定要存成 **UTF-8 with BOM** |

**演示账号**：`driver1`~`driver8` / `123456`（司机）；`dispatcher`、`viewer` / `123456`；`admin` 密码见 `物流项目/backend/.env` 的 `ADMIN_INIT_PASSWORD`。充电桩：`admin`/`admin123`，另有 project_admin / station_admin / inspector（均 `123456`）。

---

## 3. 怎么起停

```
物流项目：双击 start.bat → 后端 8000 + web 5175（本机实际 **5250**）    stop.bat 停止
充电桩项目：双击 start.bat → 后端 8010 + web 5185（本机实际 **5270**）  stop.bat 停止
```
- 后端端口被占用会**自动顺延**，实际端口写在后端 `backend/.runtime_port`。
- ★ 前端端口现在是**启动前先探测再绑定**（见坑 16），实际端口写在该前端目录的 `.runtime_port`：`start.bat` 读它来设代理、打印地址、打开浏览器，`stop.bat` 读它来杀进程。**`http://127.0.0.1:5175` 在这台机器上永远打不开**（落在 Windows 保留段里），别对着它排查。
- 小程序 H5：`cd 物流项目/miniapp && npm run dev:h5` → 首选 5173，本机实际 **5260**（跑之前先 `npm install`：这台机器上 `miniapp/node_modules` 原本是缺的，已装好）。
- 充电桩小程序 H5：`cd 充电桩项目/miniapp && npm run dev:h5` → 首选 **5190**，实测就跑在 5190（依赖已装好）。★ 它**没有被 start.bat 托管**（和物流小程序一样是手动起），`.runtime_port` 记实际端口。
- 微信小程序：`npm run build:mp-weixin`，开发者工具导入 `dist/build/mp-weixin`，**必须勾「不校验合法域名」**，AppID 用测试号即可。

---

## 4. 已经做完的事

**仓库层面**
- 删除了重复目录 `物流项目/Project-practice-HQYJ-main/`；两个答辩目录并入各自项目。
- `.gitignore`：登记了本地专有文件（旧路径残留、`.env`、`__pycache__`、`node_modules`、PDF、`.runtime_port`）。
- `.gitattributes`：`*.bat text eol=crlf`。

**物流项目**
- `start.bat` / `stop.bat` 修好：Python 解释器自动探测、端口自适应、CRLF 行尾。
- 后端**执行层**（`app/routers/mobile.py`，11 个接口）：`profile` / `my-trips` / `trips/{trip_key}` / `trips/{trip_key}/accept` / `checkin` / `exceptions` / `files`（真上传）/ `notifications`(+unread-count, read) / `manager/overview`。
- **WebSocket 实时推送**：`/api/ws/notifications?token=`，管理员下发 → 司机端当场弹提示 + 红点。
- **司机确认接单**：落在 `dispatch_record.accepted_at/accepted_by`，幂等；确认后给调度角色发站内消息。
- **管理端只读页面** 4 个（看板/任务/任务详情/异常），登录后按角色分流。
- **底部导航自绘**（`components/BottomNav.vue`）：司机 3 项（趟次/消息/我的），管理者 4 项（看板/任务/消息/我的）。
- 物流项目**免 MySQL**：连不上自动回退 SQLite（`DB_FALLBACK_SQLITE=false` 可强制 MySQL）。
- **撤销下发**（`POST /api/scheduling/tasks/{id}/undo-dispatch`，权限同下发 `scheduling:confirm`）：管理员把发错的方案收回来 —— 删 `dispatch_record`、撤回司机站内消息（`biz_type=dispatch` 且 `biz_id`=本任务）、未执行明细 `dispatched→planned`、任务退回 `confirmed`，**任务/方案/明细/确认记录全部保留**，可立刻换方案重发。司机已打卡执行的趟次不收回（只统计在返回消息里）。前端入口：调度任务列表 + 人工确认页各一个「撤销下发」按钮。**没有做「删除任务」**。
- **「趟」的口径说清楚了**（用户原话：开发人员都看不懂第 1/2 趟是什么）：一趟 = 装一次货、跑一条线路，送完回仓库再装下一趟；`trip_no` 是**本车当天第几趟、按车牌各自编号**，不是全局序号。一个司机名下有多台车时列表里会出现**多个「第 1 趟」**（例：赵师傅 D001 名下有 沪A1001(4.2m) 和 沪C1002(小包)，10-10 那天前者 2 趟、后者 4 趟，共 6 张卡片）。所以：①后端 `MobileTripOut` 新增 `vehicle_trip_count`（同一天同车实际趟数）；②小程序卡片改成「**沪A1001 今天第 1 趟（本车共 2 趟） · 上午送**」并加了说明条，详情页同步；③趟次号是按**实际排班**数的，不是车型规则里的 `trips_per_day` 上限（后者只是上限，实际可能少排）。
- **小程序真机测试**：AppID **不进仓库** —— `src/manifest.json` 里是占位符 `touristappid`，真实 AppID 放在 `物流项目/miniapp/.appid`（一行纯文本，**已 gitignore**），`npm run build:mp-weixin` 前由 `scripts/inject-appid.mjs` 自动注入（也可用环境变量 `WX_APPID` 覆盖）。★ 为什么这么绕：AppID 不算密钥，但 **GitHub secret scanning 会把它识别成「腾讯微信 API 应用 ID」并每次推送告警**，硬编码进被跟踪文件就得改写历史才能清掉（这个坑真踩过）。真机三件套：①`src/config.js` 的 `DEV_HOST` 必须是**电脑局域网 IP**（`127.0.0.1` 在手机上是手机自己，必失败；换网络改这一行 + 重新构建）；②后端必须绑 `0.0.0.0`（默认只绑 127.0.0.1，手机连不上）——`python run.py --host 0.0.0.0`；③开发者工具「详情 → 本地设置 → 勾『不校验合法域名』」+「不校验……TLS」。手机与电脑要**同一个 WiFi/网段**。防火墙对 8000/5173 默认没有放行规则且**加规则需要管理员**，若手机连不上就让用户用管理员 PowerShell 跑 `New-NetFirewallRule -DisplayName "DSH-8000" -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow -Profile Any`（5173 同理）。
- **手机浏览器也能用（不用 AppID）**：`cd miniapp && npm run dev:h5 -- --host 0.0.0.0` → 手机打开 `http://<局域网IP>:5173`（已验证：390×844 移动视口下 driver1 登录、6 张趟次卡片、点进详情、接口全 200）。它走 Vite 代理的相对路径，所以**不用**注入绝对地址。
- **跑完的趟次不删、沉到列表最底下**（用户要求：「司机完成本单之后能不能保留记录，不要删掉了，把保留的记录放到最底下」）：根因是 `services/mobile.py` 的 `_dispatched_details_stmt` 原来**只筛 `status='dispatched'`**，而司机打「离店/完成」卡会把明细推进到 `done` —— 于是本单一完成就从「我的趟次」里消失了。现在筛 `dispatched/arrived/done` 三个状态；前端加了绿色小结条「今天 N 趟：待跑 X · 已完成 Y」；已跑完但没确认过的趟次不再显示「确认收到」按钮，改成灰字「已跑完，无需确认」。
- **管理端能看「执行完成情况」了**（用户问：「后台管理员没有办法查看这个趟次完成情况吗」—— 之前确实看不到，看板只有「接单率」，那是**响应**不是**进度**）。新增 `MobileCompletionStatOut`（`mobile/manager/overview` 的 `completion` 字段）：`trips_total / finished / running / not_started / stores_done / stores_total`。口径：**一趟完成 = 该趟所有门店都 done**；`running` = 有门店 arrived/done 但没全完；`not_started` = 门店全是 dispatched。**只统计真正下发过的趟次**（有 `dispatch_record` 的）—— 一次调度产出 A/B/C/D 多套方案共用同批车与趟次号，按全部方案统计会把活算成 4 倍（实测 83 趟 vs 实际 47 趟）。三处入口：①小程序看板新增「执行完成情况」卡（含门店完成度进度条）；②小程序任务详情每趟显示「完成情况」标签 + 门店 x/y；③网页端调度任务页的「方案明细」弹窗加执行进度区块 + 每趟「进度」列（已完成/进行中/未开始）。
- **网页端 `/dashboard` 也接上真实数据了**（用户反馈：「http://127.0.0.1:5175/dashboard 就这个，啥都没」—— 因为那个页面**从来只有《需求文档》的静态说明和「待接入」占位**，从没调过接口；我第一轮把趟次明细只加到了**小程序**看板，改错了地方）。现在 `frontend/src/views/DashboardView.vue` 顶部是：日期选择 + 刷新 →「今日趟次明细」表格（车牌/趟次/司机/门店进度/状态/接单/任务，任务号可点进调度任务页）→ 四张实时汇总卡（今日任务 / 已下发趟次 / 执行完成情况含门店完成度进度条 / 在途车辆与异常）→ 原有的车型规模与需求文档约束说明（保持静态，它们本来就是文档口径，不是实时指标）。数据走 `api.fetchManagerOverview()` → `GET /api/mobile/manager/overview`（**与小程序同一个接口**，准入是 `scheduling:read`，admin/dispatcher/viewer 可用、司机 403；再开一个 `/api/dashboard` 只会让两端口径跑偏）。
- **两端的「趟次明细」数据源是同一个 `trip_briefs`**：后端 `manager_overview` 里 `MobileTripBriefOut`（**一行 = 一趟活**，不是一家门店 —— 逐店列会把看板撑爆），每条含 车牌/趟次/时段/司机/门店 x/y/任务号/`state`。`state` 四档：`running`（有门店到店或完成但没全完）→ `accepted`（已接单、一个门店都没打卡）→ `pending`（没接单没打卡）→ `done`（全完），**后端已按这个顺序排好**（同档内按车牌+趟次号），前端只负责画。小程序看板首屏**每档只给 3 条**（49 趟全铺开有 4800px 高，「今日任务/完成情况」得滑半天才看到，就失去「一进来就看到」的意义）+ 一行分布小结 +「展开全部」按钮；网页端用表格 + `max-height: 420px` 滚动。
- **顺带修掉一个隐性不一致**：`utils/format.js` 的 `groupPlanTrips()`（管理端任务详情用）原来**不返回 `trip_status`**，导致管理端把「已跑完」的趟次显示成「待确认/已确认」，与司机端的绿色「已完成」对不上。现在按与后端 `_trip_status()` 相同的规则推导 `trip_status`（全 done→done，有 arrived/done→running，否则 planned）。
- **趟次卡片的「三色状态」+ 排序（`utils/format.js` 的 `tripState()` 是唯一口径）**：**红 = 未确认接单（排最上面）→ 黄 = 已接单但没跑完（中间）→ 绿 = 已完成（沉最下面）**。同一状态内部按「上午先于下午 → 趟次号小 → 车牌」；★ **日期仍是第一排序维度**（`_trip_sort_key`），否则前天那张没确认的红卡会永远压住今天整天的活 —— 要改成「跨日期把所有红卡全局置顶」就把 `state_rank` 和 `-toordinal()` 两项换位。三处必须同源：卡片色条（`tripCardClass`）、状态标签（`acceptStatusClass`）、列表排序（后端 `_trip_sort_key` 的 `state_rank` 0/1/2），所以前端不许在页面里另写 if/else 判色。卡上右侧动作也跟着状态走：红卡给「确认收到」按钮、黄卡显示「已接单，待出车」、绿卡显示「已跑完，无需确认」。★ 已跑完的趟次标签文案是**「已完成」而不是「待确认」**（早先 `done 且从没点过确认` 会显示「待确认」，绿卡上写待确认自相矛盾）；详情页的确认带同样三色（`accept-bar-pending/accepted/done`）。

**充电桩项目**
- 两个 `.bat` 修好（Python 路径去硬编码、CRLF、UTF-8）；补齐 `python-jose` / `reportlab` / `pytest-asyncio`。
- 前端依赖用 **npm** 装好（pnpm 装不全，vite 会缺 picomatch）。
- `充电桩项目/演示脚本.md`：8-10 分钟演示脚本，含话术、检查清单、14 条兜底。
- ★ **修掉了「后台无法上传图片」的 bug**（用户原话）。根因不在后端、也不在接口：curl 直连 `POST /api/v1/uploads/images` 返回 200 且文件真的落了盘（`backend/data/uploads/202610/...`），**bug 在 `frontend/src/components/ImageUploader.vue`**。
  ant-design-vue 的 `onSuccess` 内部执行 `file2Obj(file)` **造一个新对象**替换列表项（见 `node_modules/ant-design-vue/es/upload/Upload.js` 的 `onSuccess` → `updateFileList`），新对象只保留 `uid/name/size/type/status/percent/response/originFileObj` —— **我们事先挂在旧对象上的 `url`/`thumbUrl` 被丢掉**。于是：卡片变成没缩略图的空壳 → `syncValue()` 过滤掉没 url 的项发出 `[]` → `watch(props.value)` 拿 `[undefined]` 和 `[]` 一比不相等，**把整个列表清空**。用户看到的就是「选了照片、转一圈、照片没了」，而服务端其实已经收到文件，所以极易被误判成接口问题（我第一轮也先怀疑后端）。
  修法：①先调 `onSuccess` 让 a-upload 完成替换，**再按 uid 找回替换后的那一项补 url/thumbUrl**；②URL 统一走 `urlOf(item)`（同时认 `item.url` 与 `item.response.urls`）；③`watch` 两侧都 `.filter(Boolean)` 后再比对，杜绝「多一个 undefined 就清空」；④顺手把点了没反应的预览修好（原来挂了个 `v-if="false"` 的 `a-image`）。
  验证：浏览器实拍 2 张 → 卡片保留且缩略图正常 → 提交 → `GET /faults` 回来 `FT202610110907229184`，`images` 两条、图片 `200 image/jpeg`。
- ★ **充电桩小程序端（`充电桩项目/miniapp/`，15 个页面）**。定位不是「把网页端缩小」，是按**现场动作**重排：运维人员站在桩旁边就能把巡检、报修、核查做完；管理者在手机上看板 + 派单。
  两类角色按**数据权限**分流（不是角色码，角色可配置）：个人数据 → 工作台 / 任务 / 故障 / 消息 / 我的；站点·项目·平台数据 → 看板 / 工单 / 故障 / 消息 / 我的。落地页分别是「运维工作台」和「掌上看板」。
  **没有为小程序新增任何后端接口** —— 全部复用网页端已在用的 `/work-orders/subtasks/mine`、`/work-orders/inspections`、`/faults`、`/statistics/dashboard` 等，两端永远同一套口径。
  现场主线（实测闭环跑通）：`任务列表 → 详情「开始巡检」（状态推「巡检中」）→ 巡检录入（到场签到定位 + 分类勾选 + 异常备注 + 多图 + 备注）→ 「全部正常」一键 + 二次确认 → 提交并完成 → 自动返回详情`。后端核对：`inspection_record` 正常 17 项 / 异常 0 项 / `checkin_time=2026-10-11T09:25:25`（本地时间正确）。
  其他页面：故障列表（SLA 超期红标）、故障上报（项目→站点→桩三级联动 + AI 辅助诊断 + 定位）、故障详情（核查表单 + AI 诊断卡）、扫码查桩报修（H5 无摄像头自动降级为手动输码）、消息中心（8 类筛选 + 未读红点 + 实时推送订阅）、掌上看板（周期切换 + 工单/故障/巡检/桩状态 + 手画趋势柱）、工单管理（接受/退回/取消 + 展开作业任务）、充电桩状态（过保提醒）、我的（改密 + 资料 + 数据权限说明）。
  工程约定见 `充电桩项目/miniapp/README.md`（含 8 条踩坑）。`build:mp-weixin` 与 `build:h5` 均 `DONE Build complete`，产物 `process.env` 只出现在 `config.js` 的 `typeof` 守卫内。
- ★ **顺手修掉充电桩前端 3 个连带 bug**：①`ImageUploader` 的预览点了没反应；②`vite.config.js` 的端口探测在 **build 时也写 `.runtime_port`**，会用「构建那一刻恰好空着的端口」覆盖 dev 真实端口（实测构建把 5265 写进去了，而 dev 跑在 5190）—— 改成只有 `command === 'serve'` 才写；③`.footer-bar`（底部操作条）z-index 90 < `.bottom-nav` 100 且都 `bottom:0`，导致任务详情页「开始巡检」被导航整块拦截、**按钮点不动**（页面看起来完全正常）—— 现在 footer 提到 120，并确立约定：**tab 页挂导航、二级页只有操作条**。
- ★ **网页端「巡检录入」弹窗两个 bug（用户实测报 422 后修的）**，都在 `frontend/src/views/WorkOrderDetail.vue`：
  ①**字段名不匹配**（这是 422 的根因）：模板接口 `GET /work-orders/inspections/template` 返回的是 `{ group, name }`，而提交接口 `POST /work-orders/inspections` 要 `{ item_group, item_name }`。页面原来 `templateItems.value = res.data.template.map(t => ({...t, result:'正常'}))` 直接展开，于是 `item_name` 恒为 `undefined` —— 表现是**弹窗里 14 行巡检项的标题全是空白**（只有 正常/异常 按钮和备注框），提交时后端返回 `参数校验失败：items.0.item_name Field required`。现在在 `openInspection()` 里一次性对齐字段名（`item_name: t.name, item_group: t.group`）。
  ②**静态属性里的插值不会被解析**：`<a-descriptions-item label="站点（{{ (wo.station_names || []).length }}）">` 没写 `:` 前缀，属**静态属性**，Vue 不解析里面的 `{{ }}`，页面上原样显示成 `站点（{{ (wo.station_names || []).length }}）`。改成 `:label="'站点（' + (wo.station_names || []).length + '）'"`。
  验证：浏览器实测该 AI 工单（8 站点 / 128 子任务）→ 巡检项 **14 行、空标题 0 个**、站点显示「站点（8）+ 8 个站名」→ 点「提交并结单」返回 **200 code 0** 并生成巡检记录（原来是 422）。
- ★ **小程序「同一工单的其它作业任务」不再铺满屏**（用户问「怎么这么多」）：AI 智能工单调度生成的大工单会一次拆出上百个子任务 —— 实测 `WO202610110944021538`（8 站点 × 周期 × 频率）**共 128 条**，原来的 `v-for="sub in subtasks"` 会把 128 行全铺在详情页里，把「我这条排第几、还剩几条」这个真正有用的信息淹掉。现在 `pages/tasks/detail.vue`：默认只显示**当前任务附近的 5 条** + 一行分布小结（待完成/巡检中/已完成）+「展开全部 N 条 / 收起」。实测：默认 5 行 → 展开 128 行。
- ★ **「从巡检页面退出来那任务就不见了」的根因与修复**（用户第二次实测报的，是我上一轮引入的）：我把上面那个列表的每一行做成了可点 + `redirectTo`，但 **`GET /work-orders/{id}` 返回的是整张工单的全部 128 条子任务、不按执行人过滤**，而某个运维名下只有其中 22 条 —— 点到别人的任务时，详情页按 id 在自己的列表里定位不到 → 显示「任务不存在或不属于当前账号」；又因为用的是 `redirectTo`（会把原来那页关掉），**返回时直接掉回任务列表，用户原来那条任务就"不见了"**。
  实测复现（Playwright 逐步打印页面栈）：`[深2 tasks/index > tasks/detail]` → 点别人的行 → `[深2 同样两页，但内容变成"任务不存在"]` → 返回 → `[深1 tasks/index]`。
  修法（三条一起）：①`findTask()` 顺手把自己名下子任务 id 存进 `mySubtaskIdMap`；②新增 `ownSubtasks` —— **个人数据账号只列自己名下的**（管理端账号列全部，因为 `scope_all` 确实能查到），列表标题旁注明「只显示你名下的 22 条（本工单共 128 条）」；③`openSubtask(sub)` 先 `canJump()` 判断，不是自己的就 toast「这是李运维的作业任务，不在你名下」，绝不跳过去显示"任务不存在"；④每行补上**执行人**（同一站点有多条，不写分不清是谁的，截图里 `#7 张巡检 / #19 张巡检`）。
  验证：点第 0 行（#7）→ URL id 变成该任务的 id → 页面显示「本工单第 7 个子任务」、「任务不存在」= false。
- ★ **详情页补 `onShow` 重拉**：原来只有 `onLoad`，从巡检录入页返回时不会重新拉数据 —— 提交完成后回到详情还显示「巡检中」和「继续巡检」按钮，点进去会让人以为没提交成功。现在 `onShow` 补一次（用 `firstShowDone` 跳过紧随 `onLoad` 的首次触发，避免同一个请求发两遍）。

---

## 5. 踩过的坑（**最重要，别再犯**）

1. **`.bat` 必须 CRLF**。LF-only 会让 cmd 误解析 `call :label` / `if (...)`，报 `The syntax of the command is incorrect.` 或把行尾碎片当命令执行。
2. **uvicorn `reload` 默认必须关**。reload 模式下 netstat 把监听端口记在**已退出的父进程 PID** 上，停止脚本杀不掉、端口永不释放（表现为"已停止但端口仍占用"）。两个 `run.py` 都已 `default=False`，要热重载显式 `--reload`。
3. **停止脚本靠窗口标题杀整棵进程树**（`taskkill /F /T /FI "WINDOWTITLE eq 调度后端"`）。**不要改 start.bat 里的服务窗口标题**，否则 stop 失效。
4. **小程序端绝对不能写裸 `process.env`**。微信运行时没有 `process`，会让 `app.js` 崩、所有页面都注册不上，开发者工具里显示「页面未找到」(`<body is="wx://not-found">`)——**不是**路由问题。必须 `typeof process !== 'undefined'` 保护，平台判断用 `// #ifdef H5`。
   ⚠️ **构建通过 ≠ 小程序能跑。** 每次 `build:mp-weixin` 后必须执行：
   `Select-String -Path "miniapp\dist\build\mp-weixin\**\*.js" -Pattern "process\.env"`，确认每处都在 `typeof` 保护内。
5. **微信 tabBar 是静态的**：不能删条目、不能可靠改 `pagePath`。所以物流小程序**不用原生 tabBar**，是自绘的 —— 别改回去。
6. **pnpm 在本机卡死**，前端依赖一律用 npm（`--registry=https://registry.npmmirror.com`）。
7. **数据在 MySQL，不在 SQLite**。`物流项目/backend/data/logistics.db` 是"没有 MySQL 时"的回退库，查数据别读错库。
8. **早期沙箱限制（已解除）**：受限沙箱下 git 需要 `-c http.sslBackend=openssl`（schannel 拿不到凭据）、pip 装不进 site-packages、taskkill 被拒。现在文件策略是完全访问，不需要这些绕法了。
9. **沙箱限制会拦构建（策略变了就复测一次）**。受限沙箱（workspace-write）下 esbuild 起子进程会 `spawn EPERM`：`miniapp` 的 `build:mp-weixin` / `build:h5` 与 `frontend` 的 `vite build` 都会卡在 `failed to load config from vite.config.js → spawn EPERM`。**换成完全访问后两个都能跑**（实测 `build:mp-weixin` 与 `build:h5` 都 `DONE Build complete`），所以别急着下结论说构建坏了，先看当前文件策略。
10. **`frontend` 的 `vite build` 有个独立问题：`[vite:esbuild-transpile] remove %TEMP%\esbuild-xxx: Access is denied.`**。它出现在 `✓ 2346 modules transformed` 之后、只挂在「删 esbuild 临时文件」这一步，**线上 dev（5175 HMR）不受影响**（我在真实浏览器里验过页面与按钮，见下）。清 `%TEMP%\esbuild-*` 无效，未定位到根因。
11. **H5 端 `uni.connectSocket` 在本机不返回 SocketTask**，应用会打 `[socket] 当前平台未返回 SocketTask，实时推送不可用`（这是**既有行为**，不是新引入的）—— 于是 H5 里**收不到实时推送**，趟次/消息页只能靠「切页面/下拉刷新」更新。**微信小程序端不受影响**（走原生 socket，两端都是 `uni.connectSocket`，只有 H5 这个实现拿不到 SocketTask）。所以现场要演「管理员下发/撤销 → 司机当场收到」，必须用微信开发者工具。
12. **微信开发者工具的 CLI 自动化在本机不可用**：`cli auto --project ... --auto-port 9420` 报 `listen EACCES 127.0.0.1:3799`，因为 3799 落在 Windows 保留端口段（`netsh int ipv4 show excludedportrange protocol=tcp` 显示 3724–3823）。要自动化得先让用户以管理员调整保留段，**不要在这上面耗时间**。
13. **`realtime.publish_to_users()` 必须带超时**。它内部是 `asyncio.run_coroutine_threadsafe(...)`，返回的 future 一旦被 `result()` 等待、而事件循环里有「已断开但没摘除」的 WebSocket，业务线程会被无限期卡住 → **HTTP 请求永不返回，但数据库早就改完了**（真实踩到：撤销下发接口 120s 超时，库里状态其实已改）。现在函数内已加两道保护：没有在线连接直接返回 + `future.result(timeout=2.0)`。新增推送调用一律走它，**不要自己写 `future.result()`**。
14. **沙箱里杀不掉外面的进程**。受限沙箱下 `taskkill /F /PID` 报 `Access denied`，`Get-Process`/WMI 也看不见它 —— start.bat 起的后端 PID 就是这样。**换成完全访问后就能杀了**（实测：杀旧后端 → 重启 → `.runtime_port` 回到 8000、新端点立即在位）。策略受限时只能请用户双击 `stop.bat`/`start.bat`，别另起一个占着别的端口冒充（`.runtime_port` 会被写歪，前端代理只认 8000）。
15. **用浏览器做验证时踩过的三个坑（都可复用）**：①uni-app 的 H5 把 `<button>` 编译成 `<uni-button>`，`querySelectorAll('button')` 找不到；②`uni.setStorageSync` 在 H5 存的是带 `{type,data}` 信封的 JSON，测试脚本直接写裸字符串会让 `getStoredUser()` 解析不出 `roles`，账号被误判成「调度/管理角色」；③自建一次性静态代理必须**转发 `Authorization` 头**，否则登录后所有请求 401，会误判成应用 bug。
16. **前端起不来、报 `listen EACCES: permission denied 127.0.0.1:5175` = 端口落在 Windows 保留段里，不是代码问题**（本机实测：`netsh int ipv4 show excludedportrange protocol=tcp` 显示 **5041–5240 被整段保留**，5173/5174/5175/5176/5177/5185 **全部 EACCES**，5250 以上才 OK —— 项目原来的三个前端端口全在里面，所以「物流项目跑不起来」）。
    ★ **关键认知：vite 的 `strictPort: false` 只在 `EADDRINUSE`（被普通进程占用）时顺延，`EACCES` 是致命错误、进程直接退出**，所以靠「自动顺延」永远救不了，必须在**监听前**自己探。
    修法（已落地）：三个前端 `vite.config.js` 都用 `node:net` 逐个 bind 探测候选端口（首选值原样保留：物流 web 5175 / 小程序 H5 5173 / 充电桩 5185，探不通就依次试 5250/5260/5300…），选中的端口写进**该前端目录**的 `.runtime_port`，并令 `strictPort: true` 保证文件与实际一致；`VITE_PORT` 可强制指定。
    `start.bat` 改为：先 `del` 旧 `.runtime_port` → 等新文件出现（最多约 20 秒）→ 用它设 `/api` 代理目标、打印真实地址、打开浏览器；`stop.bat` 也读它（老版本只认 8000/5175，会漏掉真正在跑的 5250）。
    ★ 附带：`.bat` 里**别用 `timeout` 当等待** —— stdin 被重定向/没有控制台时它直接报 `ERROR: Input redirection is not supported` 就退出，等于没等；用 `ping -n N 127.0.0.1 >nul`（N≈秒数+1）。
17. **`uni.request` 在 GET 时把 `undefined` 序列化成空串，会让布尔查询参数 422**（充电桩小程序实测）。请求变成 `/work-orders/subtasks/mine?status=&scope_all=&page=1` —— 字符串参数收空串等价于没传，但 **`scope_all` / `mine` / `is_read` 这类布尔参数收到空串，FastAPI 直接 422「Input should be a valid boolean, unable to interpret input」**，表现是**任务列表、工单列表、消息中心三个页面同时变错误态**，看着像后端挂了。
    修法：`charging-pile/miniapp/src/utils/request.js` 的 `cleanQuery()`，**只对 GET** 剔除 `undefined/null/''`（POST 请求体不能这么干：有些接口 `''` 与「不传」语义不同，比如把备注清空）。
18. **ant-design-vue 的 `a-upload` 自定义上传会「吞掉」你挂在文件对象上的字段**（充电桩后台图片上传 bug 的根因，详见 §4）。`customRequest` 成功后，Upload 内部用 `file2Obj(file)` 造**新对象**替换列表项，只保留 `uid/name/size/type/status/percent/response/originFileObj`。所以：**任何自定义字段（url、业务 id…）都必须存在 `response` 里、或在 `onSuccess` 之后按 uid 重新 find 回列表项再补**。反过来看，这个 bug 的症状极具误导性 —— 服务端 200、文件真落盘，前端「照片一闪就没了」，所以**别先怀疑接口**，先看 `syncValue()` 发出去的是什么。
19. **`new Date().toISOString()` 是 UTC，不是本地时间**（充电桩小程序签到打卡实测：09:21 显示成 01:21）。凡是要显示「现在几点」，用 `utils/format.js` 的 `nowClock()` / `nowDateTime()`；从后端拿到的 `2026-10-11T09:00:00` 是**朴素本地时间**，直接字符串切片即可，**不要过 `new Date()`**（iOS 对 `YYYY-MM-DD HH:mm:ss` 的解析历史不一致）。
20. **验证小程序 H5 时，Playwright 选择器别用泛匹配 + `.first()`**。uni-app 里 `<view>` 会编译成 `<uni-view>`，`page.locator('uni-view', { hasText: '全部正常' }).first()` 命中的是**最外层页面容器**，点了等于没点 —— 我因此一度误判「『全部正常』功能坏了」，实际功能是好的。要 `page.locator('uni-view.tool-btn', { hasText: '全部正常' })`。
    同理：**`uni.showModal` 渲染的是 `<div class="uni-modal__btn">`，不是 `<uni-button>`**，用 `uni-button` 找弹窗按钮永远找不到（且按钮文案是自定义的，如「提交完成」而不是「确认」）。
21. **小程序里「网络不通」= 请求根本没到后端，跟「后端返回 4xx/5xx」是两回事**。`utils/request.js` 里 `uni.request` 的 `fail` 回调被触发才给 `err.code = 0`，文案是「无法连接后端服务（xxx），请确认后端已启动」/「网络不通，操作可能未提交成功，请重试」。**用户报这句时，先看后端绑在哪，不要看业务代码。**
    ★ 充电桩这次的真实原因：`run.py` 的 `--host` 默认取 `settings.HOST = 127.0.0.1`，而 `start.bat` 原来只写 `"%PY%" run.py`（没带 `--host`）→ 后端只绑回环；小程序 `DEV_HOST` 是**局域网 IP** `192.168.1.4:8010` → 必连不上。实测对照：`127.0.0.1:8010/health` = **200**，`192.168.1.4:8010/health` = **HTTP 000**。
    修法（已落地）：`充电桩项目/start.bat` 第 78 行改成 `run.py --host 0.0.0.0`（★ 单行内替换，**没有引入 LF 行尾**，窗口标题也没动 —— 标题是 stop.bat 杀进程的依据）。绑 `0.0.0.0` 同时覆盖回环，所以网页端/H5 代理（都走 `127.0.0.1:8010`）不受影响；验证方式：临时起一个 `python -m http.server 8099 --bind 0.0.0.0`，用 `192.168.1.4:8099` 访问得 **200**（同机走局域网 IP 这条路是通的）。
    ★ 自查命令：`netstat -ano | findstr :8010` —— 显示 `127.0.0.1:8010` 就是只绑了回环（真机/局域网都连不上），显示 `0.0.0.0:8010` 才对。
    ★ 附带：**真机**还要过 Windows 防火墙（本机目前**没有**放行 8010 的入站规则，模拟器不受影响，因为同机走回环路径）。需要时用管理员 PowerShell：`New-NetFirewallRule -DisplayName "DSH-8010" -Direction Inbound -Protocol TCP -LocalPort 8010 -Action Allow -Profile Any`。
    ★ `run.py` 第 51 行**无条件写 `backend/.runtime_port`**，所以别拿它起临时实例做实验（会把端口文件写歪，前端代理只认那一个值）；要试端口就用 `python -m http.server`。
    ★ 同类问题在物流项目同样存在（它的 `run.py` 默认也是 127.0.0.1，AGENTS 早就写了「真机要 `python run.py --host 0.0.0.0`」）—— 但物流的 `start.bat` 是否也需要加，**没查过，别顺手改**。
22. **同一个业务对象，两个接口的字段名可能不一样**（充电桩巡检录入 422 的根因）。`GET /work-orders/inspections/template` 返回 `{ group, name }`，`POST /work-orders/inspections` 要 `{ item_group, item_name }` —— 名字像但不是同一个，中间必须显式映射一次。原来页面用 `{...t}` 直接展开，`item_name` 恒为 `undefined`：**前端不报错**（列表照样渲染，只是每行标题空白），只有提交时后端才抛 `422 items.0.item_name Field required`。所以看到「弹窗里列表是空的/没标题」不要先怀疑样式，先 `console.log` 一条模板项看字段名。
23. **Vue 模板里没有 `:` 前缀的属性是静态属性，`{{ }}` 不会被解析**（`WorkOrderDetail.vue` 的 `label="站点（{{ ... }}）"` 原样显示在页面上）。凡是属性值里要算东西，一律写 `:label="'站点（' + n + '）'"`。这类 bug 很好认：页面上出现「双大括号」或「`|| []`」这种源码片段。
24. **`uni.getLocation` 的 `timeout` 参数不是所有平台都实现**（微信底层 `wx.getLocation` 就没有）—— 一旦 success/fail 都不回调，Promise 永不 settle，而调用方是 `uni.showLoading({ mask: true })` + `await`，**结果就是遮罩永远盖着，整页按钮全部点不动**，而且看起来完全不像是定位的问题（这是「小程序里按钮点不动」最容易踩的一种）。
    修法（已落地）：`miniapp/src/utils/format.js` 的 `getLocationSafe(timeoutMs = 6000)` 自带 `setTimeout` 兜底 + `settled` 标志 + `try/catch`，**保证最多 6 秒一定 resolve 一次**。
    ★ 排查口诀：小程序「整页按钮点不动」= 十有八九有个全屏遮罩没关（`showLoading({mask:true})` 忘了 `hideLoading`），或者有个 `position:fixed` 的层盖住了；先用真机/模拟器的 WXML 面板看有没有 `.uni-mask`。
25. **路由参数一律用 `safeDecode()`，不要裸 `decodeURIComponent`**。两个原因：①**各平台的 query 解码次数不一致** —— 实测 H5 的路由会把整个 hash 再编一次（URL 里是 `orderType=%25E5%25B7%25A1...`），到达页面时要多解一次，小程序端只编过一次；②值里只要出现一个**孤立的 `%`**（例如站名写「1#桩 100%」），`decodeURIComponent` 就抛 `URIError: URI malformed`，而它写在 `onLoad` 里，**一抛整页数据加载就断**（页面看着在、什么都点不动）。
    `safeDecode()` 的做法：有 `%xx` 才尝试解，最多解 3 轮、解到不变为止，解不出来就停在上一步 —— 两端都对。
26. **列表接口和详情接口的「数据范围」可能不一样，别拿详情接口的结果当"我的列表"用**（充电桩小程序「任务不见了」的根因）。`GET /work-orders` 与 `/work-orders/subtasks/mine` **会按执行人过滤**，而 `GET /work-orders/{id}` 返回的 `subtasks` 是**整张工单的全部子任务、不按执行人过滤**。大工单（AI 生成的 128 条）分给 3 个人，某个人名下只有 22 条 —— 界面上如果把整张工单的子任务当"我的任务"列出来并可点，点别人的就会「找不到」。
    ★ 配套的坑：**`uni.redirectTo` 会关掉当前页**。用它做"跳到兄弟条目"时，一旦目标页打不开（找不到数据/参数错），用户按返回就**直接掉回上上级**，主观感受是「我刚才那条任务不见了」。所以：`redirectTo` 只用于**确定能打开**的目标；跳转前先用本地已有的集合判断一下。
27. **`onLoad` ≠ `onShow`**：`onLoad` 一个页面实例只跑一次，从子页面 `navigateBack` 回来**不会再跑**。详情页如果只写 `onLoad`，子页面里改了状态（例如提交巡检后任务变「已完成」）回来看到的还是旧数据 + 一个已经没意义的按钮。凡是「子页面会改动本页展示的数据」的详情页，都要补 `onShow`（用 `firstShowDone` 之类的标志跳过紧随 `onLoad` 的首次触发，避免同一请求发两遍）。

---

## 6. 未完成 / 待办

- 物流小程序登录页「一键填入」列的是 driver1~8（已含 dispatcher/admin/viewer，共 11 个），与后端一致 —— **已修，别再当待办**。
- 管理端只做了**只读**；确认方案 / 下发执行 / 异常重排 / 改派车辆都还没搬到手机上。
- 微信订阅消息未做（需要 AppID + 微信登录拿 openid，做不到就别答应）。
- 充电桩项目小程序 **已做完**（15 个页面，见 §4）；它后端已有 `/api/v1/auth/wechat-login`（支持直接传 openid 联调），但**微信授权登录还没接进小程序**（需要 AppID + code 换 openid，`WECHAT_APPID/SECRET` 在 `.env` 里为空）—— 现在小程序走的是账号密码登录。
- 充电桩小程序**没做**的：AI 巡检报告生成入口、知识库问答、运维报告查看/推送、消息的微信订阅消息（同上，需要 AppID）。
- ★ **充电桩后端一个既有的小不一致，未修（不是本次引入的）**：`POST /work-orders/inspections` 在 `finish=true` 时会把子任务置「已完成」，但**不会把工单状态从「待接单」推进到「已完成」**（`work_order.recalc_subtask_progress` 只在 `PUT /subtasks/{id}` 路径上被调用）。实测：工单 `WO202610070006` 现在 `status=待接单` 而 `subtask_stats={total:1,completed:1}`、进度条显示 1/1 100%。要修就在 `services/inspection.py` 保存后补一次 `recalc_subtask_progress` + 相同的结单提示。
- ★ **充电桩演示库（SQLite `backend/data/maintenance.db`）被本次验证改动了 3 处**，都不是代码问题：
  ① `work_order_subtask` `3bf3402e…`（东西湖物流园充电站·消缺，工单 WO202610070006）由**待完成 → 已完成**，并新增 1 条 `inspection_record`（正常 17 项 / 异常 0 项 / `checkin_time=2026-10-11 09:25`）—— 这是跑通「现场闭环」必须真提交一次留下的，**建议保留**，正好能演示「已完成回看巡检记录」。
  ② `work_order_subtask` `74956e36…`（岳阳城陵矶港·巡视第 2 项）测试中被推到「巡检中」，**已还原成「待完成」**（它没留下任何记录，留着会像卡住的任务）。
  ③ 新增故障单 `FT202610110907229184`（枫泾服务区·充电枪故障，2 张图）—— 验证「上传修复」时提交的，可删可留。
  ④ 验证「网页端巡检录入 422 修复」时又在 AI 工单 `WO202610110944021538` 的子任务 `90018622…`（大兴公交枢纽充电站，序号 12 附近）上真提交了一条巡检记录（14 项全正常）并把该子任务置「已完成」—— 留着正好能演示「AI 大工单里已完成的那一条可以回看记录」。
  ⑤ AI 工单 `WO202610110944021538` 本身有 **128 个子任务**（8 站点 × 周期 4 × 频率周），这是 AI 排产按公式算出来的，不是 bug；但它意味着**演示时不要点「展开全部 128 条」**（H5 会渲染 128 行，卡一下）。
  要全部还原：把 ① 的子任务改回 `待完成`、删掉对应 `inspection_record`，再删 ③ 的故障单与它的 `attachment` 行（改库前先备份）。
- 物流 AI：`物流项目/backend/.env` 的 `DEEPSEEK_API_KEY` 为空（但 Windows 机器级环境变量里有兜底，AI 实测在线）；充电桩的 `LLM_API_KEY` 也为空。
- 物流项目地形矩阵：`seed.py` 里的数据与界面上点出来的**是反的**（界面那个才对），重跑 seed 会翻回去，未修。
- **演示库（MySQL）里有两处历史数据不一致**，都不是代码问题、但演示时可能被问到：
  ① `trip_stop_record` 里有 2 条记录指向 `plan_detail_id=38/39`，而这两个明细属于 `plan_id=2`（任务 2 的另一个方案），跟打卡记录里的 `plan_id=2` 对不上 —— 早期测试或重跑 seed 留下的孤儿数据；
  ② `plan_detail` 1034（沪C1002 第 4 趟，属任务 6/方案 22）挂着一对 arrive+complete 打卡记录，但明细状态还是 `dispatched`，说明当时的状态推进没成功（可能是被中断的一次打卡）。修法：把该明细状态改成 `done`（页面就会显示已完成并沉底），或删掉那两条打卡记录。**当前数据库状态分布（2026-10-10 记录）：planned 1094 / dispatched 60 / done 4，trip_stop_record 共 8 条** —— 改之前先按这个对一遍。
- ★ **本机演示库的排班日期是 `2026-10-12`，系统日期比它早**（库是 10-10 灌的、排班往后排了两天；系统日期已跨到 10-11），所以：**网页端 `/dashboard` 一进去「今日趟次明细」是 0 趟**（`manager_overview` 不带参数就取今天），把日期选择器切到 **2026-10-12** 才是 1 个任务 / 47 趟全部已下发；**司机端不受影响**（`my-trips` 不带日期返回全部已下发趟次，driver1 就是 6 趟）。演示前先切日期，别以为是数据没了。要把它挪到"今天"：`UPDATE scheduling_task SET schedule_date=CURDATE();` + `UPDATE md_store_demand SET schedule_date=CURDATE() WHERE schedule_date='2026-10-12';`（改库前先备份）。

---

## 7. 沟通偏好（重要）

- **别慢吞吞**：先给结论和证据，再补一句原因。不要长篇分析、不要每步一问。
- **批量做**：能一次跑完的别拆成多轮；避免"改一处、查一次"的碎步。
- **给证据**：说"验证过了"要附真实返回值 / 端口状态 / 构建结果。
- **说人话**：少用分层标题和术语堆砌。
- 演示优先用**浏览器 H5**，微信开发者工具容易出环境问题。⚠️ 但**实时推送/H5 收不到**（见坑 11）：要现场演「管理员下发→司机当场收到」，只能用微信开发者工具；H5 演示就靠「切页面/下拉刷新」。
- 成本敏感：能用一次调用解决的，不要用三次。

---

---

## 8. 换新电脑（3 步）

1. `cd 物流项目\backend` → `copy .env.example .env`（填数据库密码）→ `python run.py`
   ★ 后端**首次启动会自动建表并灌演示数据**（只有空库才做，已有数据不覆盖，
   `AUTO_SEED_ON_EMPTY=false` 可关）。首次启动要跑 20~30 秒，跑完再访问页面。
2. 三个前端各自 `npm install` 后 `npm run dev`（一律用 npm；pnpm 在本机会卡死）。
3. 要手机测小程序时：`miniapp/src/config.js` 的 `DEV_HOST` 改成这台电脑的局域网 IP，
   后端用 `--host 0.0.0.0` 起；`miniapp/.appid` 自己建一行 AppID（不进仓库）。
