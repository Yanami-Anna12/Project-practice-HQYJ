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

---

## 6. 未完成 / 待办

- 物流小程序登录页「一键填入」只列了 driver1~3，后端有 driver1~8。
- 管理端只做了**只读**；确认方案 / 下发执行 / 异常重排 / 改派车辆都还没搬到手机上。
- 微信订阅消息未做（需要 AppID + 微信登录拿 openid，做不到就别答应）。
- 充电桩项目**还没做小程序**；它后端已有 `/api/v1/auth/wechat-login`（支持直接传 openid 联调）。
- 物流 AI：`物流项目/backend/.env` 的 `DEEPSEEK_API_KEY` 为空（但 Windows 机器级环境变量里有兜底，AI 实测在线）；充电桩的 `LLM_API_KEY` 也为空。
- 物流项目地形矩阵：`seed.py` 里的数据与界面上点出来的**是反的**（界面那个才对），重跑 seed 会翻回去，未修。

---

## 7. 沟通偏好（重要）

- **别慢吞吞**：先给结论和证据，再补一句原因。不要长篇分析、不要每步一问。
- **批量做**：能一次跑完的别拆成多轮；避免"改一处、查一次"的碎步。
- **给证据**：说"验证过了"要附真实返回值 / 端口状态 / 构建结果。
- **说人话**：少用分层标题和术语堆砌。
- 演示优先用**浏览器 H5**，微信开发者工具容易出环境问题。
- 成本敏感：能用一次调用解决的，不要用三次。
