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
| 各项目下的 `答辩PPT/` | 答辩 PPTD 源 + 答辩稿 | — |

---

## 2. 本机环境（已确认，不要再查）

| 项 | 值 |
|---|---|
| Python | `C:\Users\12966\miniconda3\envs\py312\python.exe`（依赖齐全，含 ortools/langgraph/pymysql/jose） |
| node / npm | `C:\nvm4w\nodejs\node.exe` v24.12 / `C:\nvm4w\nodejs\npm.cmd` |
| pnpm | 存在但**在这台机器上会卡死在链接阶段 → 一律用 npm** |
| MySQL | 8.0.42 已运行，库 `logistics_db`，凭据在 `物流项目/backend/.env` |
| Edge | `C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe`，可无头截图验证页面 |
| 端口 | 物流：后端 8000 / web 5175 / 小程序 H5 5173；充电桩：后端 8010 / web 5185 |

**演示账号**：`driver1`~`driver8` / `123456`（司机）；`dispatcher`、`viewer` / `123456`；`admin` 密码见 `物流项目/backend/.env` 的 `ADMIN_INIT_PASSWORD`。充电桩：`admin`/`admin123`，另有 project_admin / station_admin / inspector（均 `123456`）。

---

## 3. 怎么起停

```
物流项目：双击 start.bat → 后端 8000 + web 5175     stop.bat 停止
充电桩项目：双击 start.bat → 后端 8010 + web 5185   stop.bat 停止
```
- 端口被占用会**自动顺延**，实际端口写在后端 `backend/.runtime_port`。
- 小程序 H5：`cd 物流项目/miniapp && npm run dev:h5` → http://127.0.0.1:5173
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
- **小程序真机测试（已配好 AppID）**：`src/manifest.json` 的 `mp-weixin.appid` = `wx506e7ceb13d4a7c2`（微信**测试号**，不是 `touristappid` —— 游客模式**不能**预览/真机调试/上传，这就是之前扫不出码的原因）。真机三件套：①`src/config.js` 的 `DEV_HOST` 必须是**电脑局域网 IP**（当前 `http://192.168.50.209:8000`；`127.0.0.1` 在手机上是手机自己，必失败，换网络只需改这一行 + 重新 `build:mp-weixin`）；②后端必须绑 `0.0.0.0`（本机默认只绑 127.0.0.1，手机连不上）——`python run.py --host 0.0.0.0`；③开发者工具「详情 → 本地设置 → 勾『不校验合法域名』」+「不校验……TLS」。手机与电脑要**同一个 WiFi/网段**（本机以太网 `192.168.50.209/23`，网关 `192.168.50.1`）。防火墙对 8000/5173 没有放行规则且**加规则需要管理员**（我这边 Access denied），若手机连不上就让用户用管理员 PowerShell 跑 `New-NetFirewallRule -DisplayName "DSH-8000" -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow -Profile Any`（5173 同理）。
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

---

## 6. 未完成 / 待办

- 物流小程序登录页「一键填入」列的是 driver1~8（已含 dispatcher/admin/viewer，共 11 个），与后端一致 —— **已修，别再当待办**。
- 管理端只做了**只读**；确认方案 / 下发执行 / 异常重排 / 改派车辆都还没搬到手机上。
- 微信订阅消息未做（需要 AppID + 微信登录拿 openid，做不到就别答应）。
- 充电桩项目**还没做小程序**；它后端已有 `/api/v1/auth/wechat-login`（支持直接传 openid 联调）。
- 物流 AI：`物流项目/backend/.env` 的 `DEEPSEEK_API_KEY` 为空（但 Windows 机器级环境变量里有兜底，AI 实测在线）；充电桩的 `LLM_API_KEY` 也为空。
- 物流项目地形矩阵：`seed.py` 里的数据与界面上点出来的**是反的**（界面那个才对），重跑 seed 会翻回去，未修。
- **演示库（MySQL）里有两处历史数据不一致**，都不是代码问题、但演示时可能被问到：
  ① `trip_stop_record` 里有 2 条记录指向 `plan_detail_id=38/39`，而这两个明细属于 `plan_id=2`（任务 2 的另一个方案），跟打卡记录里的 `plan_id=2` 对不上 —— 早期测试或重跑 seed 留下的孤儿数据；
  ② `plan_detail` 1034（沪C1002 第 4 趟，属任务 6/方案 22）挂着一对 arrive+complete 打卡记录，但明细状态还是 `dispatched`，说明当时的状态推进没成功（可能是被中断的一次打卡）。修法：把该明细状态改成 `done`（页面就会显示已完成并沉底），或删掉那两条打卡记录。**当前数据库状态分布（2026-10-10 记录）：planned 1094 / dispatched 60 / done 4，trip_stop_record 共 8 条** —— 改之前先按这个对一遍。

---

## 7. 沟通偏好（重要）

- **别慢吞吞**：先给结论和证据，再补一句原因。不要长篇分析、不要每步一问。
- **批量做**：能一次跑完的别拆成多轮；避免"改一处、查一次"的碎步。
- **给证据**：说"验证过了"要附真实返回值 / 端口状态 / 构建结果。
- **说人话**：少用分层标题和术语堆砌。
- 演示优先用**浏览器 H5**，微信开发者工具容易出环境问题。⚠️ 但**实时推送/H5 收不到**（见坑 11）：要现场演「管理员下发→司机当场收到」，只能用微信开发者工具；H5 演示就靠「切页面/下拉刷新」。
- 成本敏感：能用一次调用解决的，不要用三次。
