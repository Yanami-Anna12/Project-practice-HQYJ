# 充电桩运维管理 AI Agent 平台

> 依据《充电桩运维管理 AI Agent 项目技术方案》完整实现的可运行工程。
> 技术栈：**FastAPI + SQLAlchemy(async) + LangGraph + OR-Tools + RAG + Vue3 + Ant Design Vue**

---

## 一、快速开始

```bash
# Windows 一键启动（自动建库 + 注入演示数据 + 拉起前后端）
双击 start.bat

# 停止服务
双击 stop.bat
```

手动启动：

```bash
# 后端（默认 http://127.0.0.1:8000）
cd backend
pip install -r requirements.txt
python run.py

# 前端（默认 http://127.0.0.1:5175）
cd frontend
pnpm install
pnpm run dev
```

访问入口：

| 入口 | 地址 |
| --- | --- |
| 管理后台 | http://127.0.0.1:5175 |
| 接口文档（Swagger） | http://127.0.0.1:8000/docs |
| 健康检查 | http://127.0.0.1:8000/health |
| 系统指标 | http://127.0.0.1:8000/metrics |

### 演示账号

| 用户名 | 密码 | 角色 | 数据权限 |
| --- | --- | --- | --- |
| `admin` | `admin123` | 平台管理员 | 平台数据 |
| `project_admin` | `123456` | 项目管理员 | 项目数据 |
| `station_admin` | `123456` | 站点管理员 | 站点数据 |
| `inspector` | `123456` | 运维人员 | 个人数据 |

> 登录页可点击卡片自动填入。

---

## 二、核心设计原则（严格对齐方案 PDF 4.1）

1. **硬约束代码化** —— 工单类型、巡检频率、子任务数量公式、故障等级、数据权限、
   报告周期全部由确定性代码保证，集中在 `app/core/enums.py` 与 `app/services/`。
2. **LLM 只做解释和辅助** —— 报告生成、根因分析、运维建议、方案解释走 LLM；
   无 API Key 或调用失败时自动降级为规则引擎，主流程不阻塞。
3. **多 Agent 协作** —— 8 类 Agent（工单调度 / 故障诊断 / 巡检报告 / 运维建议 /
   风控 / 报告 / 数据分析 / 编排）。
4. **多方案比选 + 人工确认** —— 生成 3 个候选方案并评分，必须人工确认后才建单下发。
5. **规则版本化** —— 每次调度记录 `rule_version`，可追溯。
6. **混合求解** —— 启发式快速出解 + OR-Tools CP-SAT 精确优化。
7. **异常可重排** —— 锁定已执行任务，只重排未完成部分，`replan_count` 限次防死循环。
8. **全流程闭环** —— 工单下发 → 巡检执行 → 故障核查 → 报告推送。

### 子任务数量公式（硬约束，`app/services/work_order.py`）

| 工单类型 | 子任务数量 |
| --- | --- |
| 巡视 / 设备检查 / 其他 | 站点数量 × 巡检周期 × 巡检频率 |
| 特巡 | 站点数量 × 巡检次数 |
| 消缺 | 固定 1 个子任务 |

巡检频率折算：日 = 30/周期、周 = 4/周期、月 = 1/周期。

---

## 三、项目结构

```
充电桩项目/
├── start.bat / stop.bat           一键启停
├── backend/                       FastAPI 后端（约 17000 行）
│   ├── app/
│   │   ├── core/                  配置、数据库、枚举、权限依赖、异常、工具
│   │   ├── models/                25+ 张表（rbac / operations / system / ai）
│   │   ├── services/              工单、故障、巡检、台账、消息、统计、导出、审计
│   │   ├── api/                   认证、工单、故障、统计、导出、管理、AI、WebSocket
│   │   ├── ai/
│   │   │   ├── graph.py           LangGraph 工作流（正常流程 + 异常重排）
│   │   │   ├── nodes.py           17 个节点（对照 PDF 4.4）
│   │   │   ├── solver.py          启发式 + CP-SAT 混合求解与评分
│   │   │   ├── llm.py             LLM 客户端（可降级）
│   │   │   ├── knowledge.py       RAG 知识库（内置 TF-IDF 检索）
│   │   │   ├── report_service.py  报告 Agent（日/周/月/即时，MD/HTML/PDF）
│   │   │   └── pdf_reader.py      内置 PDF 文本提取
│   │   ├── bootstrap.py           权限/角色/参数/规则/定时任务初始化
│   │   ├── seed.py                演示数据（含时间戳回填）
│   │   └── main.py                应用入口
│   ├── smoke_test.py              端到端冒烟测试（83 项）
│   └── requirements.txt
└── frontend/                      Vue3 + Ant Design Vue 管理后台
    └── src/
        ├── api/                   接口封装
        ├── router/                路由
        ├── stores/                Pinia 状态
        ├── layouts/               主框架
        ├── components/            BaseChart / StatCard
        └── views/                 各业务页面
```

---

## 四、功能模块对照（方案 PDF 3.1 模块总览）

| 模块 | 实现位置 | 说明 |
| --- | --- | --- |
| 系统管理 | `api/admin.py` + `views/system/*` | 用户、角色、权限树、参数、规则、日志、定时任务 |
| 角色与用户 | `services/rbac.py` | 4 级数据权限（个人/站点/项目/平台）、微信授权登录 |
| 工单管理 | `api/work_orders.py` + `services/work_order.py` | 申请、接单、退回、取消、重新下发、子任务、巡检、导出 |
| 故障管理 | `api/faults.py` + `services/fault.py` | 上报（草稿）、核查、等级判定、SLA、故障卡片与统计 |
| 作业管理 | `api/work_orders.py` `subtasks/mine` | 我的作业任务、复杂模糊查询、任务卡片 |
| 台账管理 | `services/asset.py` | 站台/充电桩台账、导出、二期字段（充电枪/灭火器/摄像头） |
| 消息中心 | `services/message.py` | 4 类工单提醒、未读小红点、多通道推送 |
| 统计分析与看板 | `services/statistics.py` | 工单统计、5 类分布、逾期率、项目与站点排名、导出 |
| 二期扩展 | `services/asset.py` | 充电枪数量、站点导航与地图分享、灭火器「无」选项、摄像头字段 |
| 附件与多图上传 | `api/uploads.py` + `services/upload.py` | 巡检/故障/核查现场照片多图上传、文档上传、附件归档 |
| AI Agent 中心 | `ai/` | 8 类 Agent + LangGraph 编排 + 人工确认 + 异常重排 |
| 运维分析报告 Agent | `ai/report_service.py` | 日/周/月/即时、6 大内容模块、追问下钻、历史对比、推送 |
| 接口集成 | `core/config.py` + 服务层 | 储能平台/充电桩平台/电价/天气/地图/微信/飞书/邮件 |
| 监控预警 | `main.py` `/metrics` + `services/audit.py` | Prometheus 指标、操作审计、异常事件扫描 |

---

## 五、AI Agent 工作流

**正常流程**（`app/ai/graph.py`）：

```
START → load_task → data_perception → constraint_parse → rule_validation
      → work_order_generation → task_scheduling → inspection_processing
      → fault_diagnosis → report_generation → human_confirmation
      → dispatch_execution → END
```

**异常重排入口**：

```
monitor_exception → impact_analysis → replan → plan_scoring
                 → human_confirmation → dispatch_execution
```

**关键机制**

- **人工确认（两阶段执行）**：阶段一跑到 `human_confirmation` 即停止，把候选方案
  写入 `ai_agent_task` 并置为 `waiting_confirmation`；调用
  `POST /api/v1/ai/agent/tasks/{id}/confirm` 后，阶段二带着确认结果重跑工作流完成建单下发。
  未确认不会创建任何工单，且状态存数据库，支持多 worker 部署。
  实现说明见 `app/ai/nodes.py::human_confirmation` 的文档字符串。
- **防死循环**：`relax_constraints` 带 `relax_count` 计数，达到 `MAX_RELAX_RETRY` 后
  路由到 `exception_handler` 终止；`replan_count` 同理限次。
- **可观测**：每个节点写入 `ai_agent_trace`；WebSocket
  `/api/v1/ws/agent/tasks/{task_id}` 实时推送进度（PDF 5.4 格式）。

---

## 六、LLM 配置

后端按以下顺序解析 API Key（`app/core/config.py`）：

1. 环境变量 / `backend/.env` 中的 `LLM_API_KEY`
2. Windows 机器级环境变量 `DEEPSEEK_API_KEY`
3. `OPENAI_API_KEY`

未配置时自动降级为确定性规则引擎，报告与诊断仍可完整产出，并在界面上标记
「规则引擎模式」。查询当前状态：`GET /api/v1/ai/health`。

```bash
# backend/.env 示例
LLM_PROVIDER=deepseek
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat
LLM_API_KEY=
```

---

## 七、数据库

- **本地开发（默认）**：SQLite，开箱即跑，无需安装数据库。
- **生产**：把 `DATABASE_URL` 改为
  `postgresql+psycopg://user:pass@host:5432/dbname`，模型与业务代码零改动
  （已按 PostgreSQL 15+ 设计，含连接池、索引与命名约定）。

```bash
# backend/.env
DATABASE_URL=postgresql+psycopg://maintenance:password@127.0.0.1:5432/maintenance
```

---

## 八、验证

三套验证脚本，全部可重复运行：

```bash
# 1) 后端端到端冒烟测试（91 项断言，自拉独立服务与数据库）
cd backend
python smoke_test.py            # 结果写入 smoke_report.txt / smoke_result.json
python smoke_test.py --verbose  # 输出框架日志，便于排查

# 2) 真实服务联调验证（需先启动前后端；48 项断言）
cd ..
python verify_live.py

# 3) 前端页面编译验证（Vite 实时编译每个模块；32 项断言）
python verify_frontend.py
```

覆盖范围：

- **系统与鉴权**：健康检查、OpenAPI 接口清单、Prometheus 指标、登录、权限菜单、数据权限隔离。
- **工单闭环**：申请（三类公式校验）、接单、退回、取消、状态机非法迁移拦截、
  子任务、巡检录入（含 200 字限制）、巡检详情、Excel 导出与下载。
- **故障闭环**：草稿保存、确认上报、高风险关键词自动判定「危急」、核查、tab 筛选。
- **台账与二期**：站台/充电桩台账、灭火器「无」选项动态表单、站点导航分享。
- **附件上传**：多图上传、静态可访问性、非法类型拒绝、附件归属回填业务单据。
- **AI Agent**：LangGraph 全流程（10 个节点追踪）、多方案比选与评分、
  挂起待确认、人工确认后建单下发、故障诊断、运维建议、巡检报告、风控、
  报告生成（6 大模块校验）、追问下钻、历史对比、定时任务。

---

## 九、附件与多图上传

PDF 3.4「支持多图上传」与 3.5「多图上传」已完整实现：

| 接口 | 用途 |
| --- | --- |
| `GET /api/v1/uploads/info` | 上传能力与限制（前端据此做校验与提示） |
| `POST /api/v1/uploads/images` | 批量上传现场照片，`biz_type` = inspection / fault / verify / station |
| `POST /api/v1/uploads/files` | 批量上传文档（知识库导入：PDF/Word/Excel/PPT/txt/md） |
| `GET /api/v1/uploads/attachments` | 按业务单据查询附件 |

流程：前端先调上传接口拿到 URL → 随巡检/故障表单提交 → 后端自动把
`attachment.biz_id` 回填到业务单据（`services/upload.py::bind_attachments`），
便于后续按单据检索影像资料。

已接入真实上传的业务入口：

| 页面 | 组件位置 | biz_type |
| --- | --- | --- |
| 巡检情况录入 | `WorkOrderDetail.vue` | `inspection` |
| 故障上报 | `FaultList.vue` | `fault` |
| 故障核查 | `FaultDetail.vue` | `verify` |

> 一次上传只归属一条业务记录（`bind_attachments` 只回填 `biz_id IS NULL` 的行），
> 因此故障照片与核查照片需分别上传。这与附件语义一致：每张照片属于一次具体作业。

限制与安全：图片单张 ≤ 10MB、单次 ≤ 12 张、仅允许 jpg/png/webp/gif/bmp/heic；
文档单个 ≤ 50MB；文件名做路径穿越清洗；按业务类型校验扩展名与 MIME。

存储后端由 `STORAGE_BACKEND` 决定（`local` 默认写入 `backend/data/uploads`，
经 `/static/data/uploads` 访问；`minio` / `oss` 保留接入位）。
前端组件：`frontend/src/components/ImageUploader.vue`。

---

## 十、已知环境说明

- **CP-SAT**：OR-Tools 为可选增强。若目标机器上不可用，在 `.env` 设置
  `CPSAT_ENABLED=false` 即退化为纯启发式，多方案比选与硬约束校验不受影响。
- **报告 PDF**：使用 `reportlab`（内置中文字体 `STSong-Light`），
  无需 GTK，避免了 WeasyPrint 在 Windows 上的依赖问题。
- **向量库**：`VECTOR_STORE=local` 使用内置 TF-IDF 检索（支持中文 bigram），
  无需外部服务；切换 `milvus` / `infinity` 时调用接口保持一致。
- **npm 源**：`frontend/.npmrc` 已配置 `registry.npmmirror.com`
  （默认源在部分网络下会超时）；如可直连官方源可自行改回。
- **pnpm 构建脚本**：`frontend/pnpm-workspace.yaml` 中声明了
  `onlyBuiltDependencies: [esbuild, vue-demi, core-js]`，
  否则 pnpm v10 会跳过 esbuild 的 postinstall 导致 vite 构建失败。
