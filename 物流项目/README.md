# 车辆智能调度 Agent —— 项目总览

门店配送车辆与趟次智能分配系统。按《需求文档.md》实现，覆盖需求里的 **9 大模块**。

- 需求来源：`需求文档.md`（由《随堂笔记.pdf》物流项目章节 + 《车辆智能调度 Agent 项目技术方案.pdf》整理而成）
- 后端：`backend/`（FastAPI + SQLAlchemy 2.0 + MySQL + LangGraph 就位 + OR-Tools CP-SAT）
- 前端：`frontend/`（Vue 3 + Vite + Element Plus + ECharts）

---

## 快速开始

### 方式一：一键启动（推荐）

双击 **`start.bat`** 即可。它会自动完成环境检查、依赖安装、载入初始数据，
然后开出两个窗口分别跑后端和前端，并打开浏览器。

停止服务：双击 **`stop.ps1`**，或直接关掉那两个黑窗口。

> PowerShell 用户也可以运行 `start.ps1`（在当前终端显示前端日志，
> Ctrl+C 一并停掉后端）。
>
> 注意：`start.ps1` / `stop.ps1` 是 **UTF-8 with BOM** 编码保存的。
> 如果你用编辑器改动它们，请保留 BOM —— Windows PowerShell 5.1 默认按 GBK
> 读取 .ps1，没有 BOM 时中文会变乱码并导致语法错误。

### 方式二：手动启动两个终端

```bash
# 终端 1：后端
cd backend
C:\Users\12966\miniconda3\envs\py312\python.exe -m pip install -r requirements.txt   # 首次
python seed.py            # 建库 + 载入初始数据（幂等，可重复执行）
python run.py             # http://127.0.0.1:8000  接口文档 /docs

# 终端 2：前端
cd frontend
pnpm install              # 首次
pnpm run dev              # http://127.0.0.1:5175
```

### 运行前提

| 依赖 | 要求 | 本机状态 |
| --- | --- | --- |
| Python | 3.12（conda 环境 `py312`） | ✅ `C:\Users\12966\miniconda3\envs\py312\python.exe` |
| Node.js | 18+ | ✅ v24.9.0 |
| pnpm | 8+ | ✅ 10.34.5 |
| MySQL | 8.0，服务需在运行 | ✅ 8.0.42 @ 127.0.0.1:3306 |

数据库连接配置在 `backend/.env`。首次运行 `seed.py` 会自动建库（`logistics_db`）。

### 演示账号

密码见 `backend/.env`。登录页可点账号卡片自动填入。

| 用户名 | 密码 | 角色 | 权限数 |
| --- | --- | --- | --- |
| `admin` | `admin123` | 系统管理员 | 29 |
| `dispatcher` | `123456` | 调度员 | 9 |
| `dataadmin` | `123456` | 基础数据管理员 | 10 |
| `viewer` | `123456` | 只读观察者 | 5 |
| `multi` | `123456` | 调度员 + 只读 | 9 |
| `disabled` | `123456` | 已停用 | — |

> 数据来自本机 MySQL（`logistics_db`）。菜单与权限实时从服务端取，改完权限刷新页面即生效。

---

## 第一次用怎么跑通全流程

```
① 业务基础数据 → 门店配送需求     点「生成演示货量」（16 个门店，日货量约 19920）
② 智能调度 Agent → 调度任务       点「开始调度」→ 生成 A/B/C/D 四套方案
③ 智能调度 Agent → 多方案比选     横向对比四套方案，看绿色最优值与推荐理由
④ 智能调度 Agent → 人工确认       选一个方案「确认」→ 再「下发」（可重复点，验证幂等）
⑤ 智能调度 Agent → 异常重排       上报异常 → 触发重排（连点到上限，验证防死循环）
⑥ 报表与看板                     车辆出勤 / 趟次达成 / 装载率 / 门店配送达成 / 成本对比
⑦ 调度规则配置 → 规则版本治理     改个参数 → 发布新版本 → 看变更摘要 → 回滚
⑧ 集成与监控                     监控预警（真实指标）+ 集成清单（如实标注未连通）
```

---

## 实现范围（9 大模块全部落地）

| 需求模块 | 实现情况 |
| --- | --- |
| 1. 系统管理 | ✅ 用户 / 角色 / 权限 / 字典 / 参数 / 附件 / 日志 7 个页面 |
| 2. 业务基础数据与调度规则配置中心 | ✅ 门店 / 线路 / 映射 / 车辆档案 / 车辆类型 / 司机 / 地形矩阵；规则总览 + 版本治理 |
| 3. 车辆分配管理 | ✅ 可出勤车辆 / 门店配送需求 / 分配结果 |
| 4. 智能调度 Agent | ✅ LangGraph 节点设计 + 三阶段混合求解 + 多方案比选 + 人工确认 + 下发幂等 + 异常重排 + 调度报告 |
| 5. 报表与看板 | ✅ 车辆出勤 / 趟次达成 / 装载率 / 门店配送达成 / 成本与方案对比（ECharts） |
| 6. 移动端 / 司机端 | ⚠️ 未实现（需求里定位为独立端，本地无法演示） |
| 7. 接口集成与数据交换 | ⚠️ 清单与本地链路已就绪，**外部系统未真实连通**（如实标注） |
| 8. 监控预警与异常处理 | ✅ 真实指标 + 按数据推导的预警 |
| 9. 数据与算法平台 | ⚠️ 求解器/规则中心已实现；向量库与案例沉淀为规划项 |

---

## 技术选型

| 层 | 选型 |
| --- | --- |
| 前端 | Vue 3.5 · Vite 6 · Pinia · Vue Router 4 · Element Plus 2 · ECharts 5 · axios |
| 后端 | Python 3.12 · FastAPI 0.138 · SQLAlchemy 2.0 · Pydantic v2 · Uvicorn |
| 数据库 | MySQL 8.0（本机）· PyMySQL |
| 认证 | JWT（PyJWT HS256）+ bcrypt |
| 求解 | OR-Tools CP-SAT 9.15 + 自研启发式（三阶段混合求解） |
| LLM | LangChain + langchain-deepseek（可选，仅用于方案解释） |
| 测试 | pytest · httpx · Playwright-core（浏览器端到端） |

### 与《需求文档》技术方案的四处偏离

| 文档写的 | 实际用的 | 原因 |
| --- | --- | --- |
| PostgreSQL 15+ | **MySQL 8.0** | 本机无 PG 且 Docker 守护进程未启动。**代码未使用任何 MySQL 方言**，换 PG 只需改 `backend/app/config.py` 的 drivername |
| Redis | 未引入 | Windows 无官方 Redis；锁/缓存用数据库与进程内结构替代 |
| RabbitMQ / Kafka | 未引入 | 同上；异步用 FastAPI 后台任务 |
| LangGraph 检查点用 Postgres | SQLite 文件 | `langgraph-checkpoint-sqlite` 已装就绪 |

---

## 核心设计要点

### 权限：三个易错点

有效权限 = **所有启用角色权限的并集**，且权限点自身也须启用。实现只在 `backend/app/services/rbac.py`。

1. 角色被停用 → 该角色贡献的权限**整块失效**（不是取最严）
2. 权限点被停用 → 即使角色仍引用它也不生效
3. 用户无任何角色 → 权限空集，所有受保护接口 403

前端的菜单裁剪、按钮隐藏都只是体验优化，**最终防线是后端 `require_permission()`**。

### 求解器：三阶段混合求解 + 允许拆单

`backend/app/services/solver.py`：

1. **启发式**（毫秒级，保证有解）：按车型优先级 + best-fit 贪心装车
2. **CP-SAT**：按方案各自权重优化，超时回退启发式
3. **多方案**：A 四米二优先 / B 成本最低 / C 大包小包保障 / D 装载率均衡

**★ 允许一个门店的货量拆到多个趟次配送。** 这不是偷懒：实测单店日货量常达 2290，
超过四米二单车上限 800，一趟车物理上装不下。不拆单会导致大批门店无法覆盖
（早期版本实测覆盖率仅 25%，改成允许拆单后达到 99.8%）。

每套方案生成后由 `validate_solution()` **独立复核**全部 7 条硬约束 ——
刻意不复用求解器内部判断，避免求解器的 bug 被自己的校验逻辑掩盖。

### 下发幂等

`dispatch_record` 上 `task_id + plan_id + trip_id` 唯一。重复下发返回
「新增 0、跳过 47」，不会产生重复任务。

### 审计只追加

由四层保证：代码层（只有 `services/audit.py` 写日志且只 INSERT）、
接口层（`/api/audit-logs` 只有 GET，其余 405）、模型层（`actor_id` 可为 NULL）、
数据层（`actor_name` 冗余快照）。

---

## 自检与验证

全部自检脚本都可**重复执行**（不会因为跑第二遍而失败）。

### 后端（6 个脚本，共 173 项）

```bash
cd backend
python check_api.py            # 42 项：认证/权限/CRUD/删除保护
python check_demand.py         # 16 项：货量维护与幂等生成
python check_solver.py         # 17 项：求解器硬约束校验（加 --cp-sat 验证精确求解）
python check_scheduling.py     # 35 项：调度全链路（确认/下发幂等/重排上限/报告）
python check_reports.py        # 26 项：5 类报表口径
python check_rules_monitor.py  # 37 项：规则版本发布回滚 + 监控预警
```

### 前端（5 个脚本，共 106 项）

```bash
cd frontend
pnpm run dev                          # 需保持运行
node scripts/verify-all.mjs           # 一次跑全部（含模板编译检查）
# 或分别跑：
node scripts/verify-ui.mjs            # 30 项：系统管理 + 基础数据 + 权限裁剪
node scripts/verify-edit-save.mjs     # 15 项：各编辑弹窗的保存回归
node scripts/verify-scheduling.mjs    # 18 项：车辆分配 + 调度页面
node scripts/verify-reports.mjs       # 14 项：5 个报表页 + 图表渲染
node scripts/verify-rules-monitor.mjs # 29 项：规则配置 + 监控集成
node scripts/compile-check.mjs        # 40 个 .vue 组件的模板编译检查
node scripts/check-form-fields.mjs    # 静态检查：禁用字段是否已回填
```

所有脚本都会收集浏览器控制台错误，正常运行应为 **0 条**。

---

## 已知限制（如实说明）

1. **MP4/文件上传**：附件管理只登记元信息，不做真实文件落盘。
2. **外部系统全部未连通**：TMS/OMS/WMS/ERP/地图/GPS 都未真实对接。
   集成页如实标注 `not_connected`，并说明本地已落地哪些链路
   （例如 TMS 的下发记录、OMS 的货量入口）。
3. **监控指标不完整**：API QPS、P95 延迟、Redis 命中率、MQ 堆积需要
   Prometheus + Grafana 等外部组件，本项目未引入，因此**不展示这些数字**
   —— 编造的监控数据比没有监控更危险。
4. **成本是相对系数**：四米二 1.0 / 大包 0.85 / 小包 0.5，用于方案间相对比较，
   不是真实金额。
5. **移动端/司机端未实现**：需求里定位为独立端。
6. **路径规划简化**：求解器用「一趟最多 8 个门店」约束顺序，
   未接入真实地图路径规划（无路径矩阵时算不出真实里程成本）。
7. **规则版本回滚范围**：只回滚车辆类型规则、地形通行矩阵、参数；
   线路策略数据量大且变动频繁，未纳入快照回滚（快照里仍会记录用于追溯）。
