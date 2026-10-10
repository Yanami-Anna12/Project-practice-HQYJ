# 车辆智能调度 Agent —— 后端

FastAPI + SQLAlchemy 2.0 + MySQL + OR-Tools CP-SAT。

**项目总览与快速开始见上级目录的 `README.md`**，本文件只讲后端。

---

## 启动

```bash
# 使用 py312 环境（base 是 3.7.13，太旧）
C:\Users\12966\miniconda3\envs\py312\python.exe -m pip install -r requirements.txt
python seed.py                # 建库 + 初始数据（幂等；含司机端账号与门店坐标）
python seed.py --reset        # 先删表重建（会清空数据）
python run.py                 # http://127.0.0.1:8000
python demo_mobile.py         # 可选：造一条已下发的趟次，司机端接口立刻有数据
```

- 接口文档：http://127.0.0.1:8000/docs
- 健康检查：http://127.0.0.1:8000/api/health

配置在 `.env`（首次从 `.env.example` 复制）。

---

## 目录结构

```
backend/
├── app/
│   ├── config.py        配置（pydantic-settings）；含 SQLAlchemy 连接串的两个坑
│   ├── database.py      连接、会话、建库建表（建表后会自动补增量列）
│   ├── migrations.py    轻量加列迁移（create_all 不会给老表加列）
│   ├── errors.py        统一错误（全部返回 {"error": "..."}）
│   ├── security.py      bcrypt 密码哈希 + JWT
│   ├── deps.py          ★ 权限依赖 require_permission() / require_mobile_access()
│   ├── menus.py         菜单定义与服务端裁剪
│   ├── schemas.py       Pydantic v2 请求/响应模型
│   ├── main.py          应用装配（含 /uploads 静态目录）
│   ├── models/          30 张表的 ORM 模型
│   │   ├── rbac.py        用户/角色/权限 + 中间表
│   │   ├── sys.py         字典/参数/附件
│   │   ├── audit.py       审计日志
│   │   ├── master.py      门店/线路/映射/车辆类型/车辆/司机/地形
│   │   ├── scheduling.py  货量/任务/方案/明细/确认/下发/异常/重排/报告
│   │   ├── mobile.py      司机端执行层：trip_stop_record / mobile_notification
│   │   └── rule.py        规则版本
│   ├── routers/         12 个路由模块（含 mobile.py）
│   └── services/
│       ├── rbac.py        ★ 有效权限计算（多角色并集）
│       ├── audit.py       ★ 审计写入（全项目唯一入口）
│       ├── demand.py      货量维护 + 可重复的演示数据生成
│       ├── solver.py      ★ 三阶段混合求解 + 独立校验
│       ├── scheduling.py  调度任务落库
│       ├── mobile.py      ★ 司机端：趟次 / 打卡 / 异常上报 / 上传 / 站内消息
│       ├── reports.py     5 类报表聚合
│       ├── rules.py       规则总览 / 冲突检测 / 版本快照与回滚
│       └── monitor.py     监控指标 / 预警 / 集成状态
├── seed.py              初始数据
├── run.py               开发服务器
├── demo_mobile.py       司机端演示数据（走真实下发链路，幂等）
├── uploads/             司机端上传的现场照片（运行时生成，静态目录 /uploads）
├── check_*.py           6 个自检脚本（共 173 项）
└── requirements.txt
```

---

## 数据模型（30 张表）

| 分类 | 表 |
| --- | --- |
| RBAC | `sys_user`、`sys_role`、`sys_permission`、`sys_user_role`、`sys_role_permission` |
| 系统配置 | `sys_dict_type`、`sys_dict_item`、`sys_param`、`sys_attachment` |
| 审计与规则 | `sys_audit_log`、`sys_rule_version` |
| 基础主数据 | `md_store`、`md_route`、`md_store_route`、`md_vehicle_type`、`md_vehicle`、`md_driver`、`md_terrain_rule`、`md_terrain_matrix` |
| 调度业务 | `md_store_demand`、`scheduling_task`、`scheduling_plan`、`scheduling_plan_detail`、`scheduling_confirmation`、`dispatch_record`、`exception_event`、`replan_record`、`scheduling_report` |
| 司机端执行层 | `trip_stop_record`（现场执行记录）、`mobile_notification`（站内消息） |

初始数据（数值取自需求文档 一.3「现有条件」）：

- 车辆类型：四米二 630-800 日 2 趟 / 大包 300-420 日 2 趟 / 小包 1-300 日 4 趟
- 车辆 **40 台 = 28 + 3 + 9**
- 门店 16 个（3 个交界门店）、线路 5 条、映射 19 条
- 地形通行矩阵 9 格（严控地形只允许「全能去」）
- 司机 8 名，其中前 3 名各有一个司机端账号（见下）

### 增量列与轻量迁移

司机端用到两处新增字段，**已存在的库不会自动加列**（`create_all()` 只建表）：

| 表 | 新增列 | 用途 |
| --- | --- | --- |
| `md_driver` | `user_id`（Integer，可空，带索引） | 司机档案 ↔ 登录账号 `sys_user.id`。原模型里两者毫无关联，账号密码登录场景绕不开 |
| `md_store` | `latitude` / `longitude`（Numeric(10,6)，可空） | 门店坐标，小程序「一键导航」用；只有 address 文字打不开地图 |

`app/migrations.py` 的 `apply_lightweight_migrations()` 会在 `create_all_tables()`
之后把缺的列补上（先查列、再 `ALTER TABLE ... ADD COLUMN`），
**MySQL 8.0 与 SQLite 都没有 `ADD COLUMN IF NOT EXISTS`**，所以只能这么做，且天然幂等。
它只能加可空列，不能改类型/删列/迁数据 —— 正式项目请上 Alembic。

---

## 司机端（小程序）后端执行层

司机端接口前缀 `/api/mobile`，业务逻辑在 `app/services/mobile.py`。

### 三个既定设计

1. **司机 ↔ 任务**：走现成的 `md_vehicle.driver_id`（一台车绑一个司机）。
   `scheduling_plan_detail` **不加** driver_id —— 它是计划快照。
2. **登录**：复用 `POST /api/auth/login`（账号密码），不做微信登录。
3. **消息**：只做站内消息（表 + 未读计数 + 列表 + 已读），
   不做微信订阅消息（需要 openid，账号密码登录拿不到）。

### 计划不可变，执行另表

`trip_stop_record` 一行 = 某趟次某门店的一次现场操作（到店/离店/完成）：
`plan_detail_id`、`driver_id`、`store_id`、`action`、`occurred_at`、
打卡经纬度、备注、照片附件 id 列表。

★ 为什么不直接给 `scheduling_plan_detail` 加字段：那是**计划快照**，
必须不可变，否则方案比选、下发幂等、异常重排的「锁定已执行趟次」都失去比对基准。
这与 `scheduling_confirmation`（确认）、`dispatch_record`（下发）的做法一致。
本模块**只改** `scheduling_plan_detail.status`，从不改门店/货量/顺序等计划内容。

状态取值（沿用现有代码）：`planned` 已计划 → `dispatched` 已下发 →
`arrived` 已到店 → `done` 已完成（`completed` 是旧口径同义值，读取时一并视作完成）。
动作序列：**到店 →（离店 | 完成）**，两个终态是平的。

### 接口清单

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| GET | `/api/mobile/my-trips` | 我的趟次（`schedule_date` 可留空 = 全部已下发） |
| GET | `/api/mobile/trips/{trip_key}` | 趟次详情：门店序列、货量、地址/电话/坐标、执行状态 |
| POST | `/api/mobile/checkin` | 现场打卡（到店 / 离店 / 完成） |
| POST | `/api/mobile/exceptions` | 异常上报（复用 `exception_event`，不新建表） |
| POST | `/api/mobile/files` | 图片上传（真落盘 + `sys_attachment` 登记） |
| GET | `/api/mobile/notifications` | 站内消息列表 |
| GET | `/api/mobile/notifications/unread-count` | 未读数 |
| POST | `/api/mobile/notifications/{id}/read` | 标记已读 |
| GET | `/api/mobile/profile` | 当前司机档案 + 名下车辆 |

`trip_key` 形如 `3:5:12:1`（任务:方案:车辆:趟次），**与 `dispatch_record.trip_id` 同规则**，
所以「下发的那一刻」和「司机端看到的趟次」是同一个键，便于对账。

### 权限

统一依赖 `require_mobile_access`（`app/deps.py`）放行其一即可：

1. 持有权限点 **`mobile:use`**（新增；司机角色默认持有，admin 是 `*` 自动包含）
2. 账号已绑定司机档案（`md_driver.user_id = 当前用户`）—— 兜底，避免建了司机却没配角色就 403

执行类接口（打卡/异常）另外要求「这一趟是你名下车辆」，越权返回 403。

### 站内消息的产生

`POST /api/scheduling/tasks/{id}/dispatch` 下发成功后调用 `notify_dispatch()`，
给该方案涉及车辆对应的司机各写一条消息（标题带车牌，便于一个司机多台车时区分）。
**通知失败只记日志，不影响下发本身**，返回结构也未改变（只在审计 detail 里多了「通知司机」计数）。
没绑定登录账号的司机拿不到站内消息 —— 只记日志，不报错。

### 文件上传

`POST /api/mobile/files` 是本项目**第一个真落盘**的上传接口
（`app/routers/attachments.py` 只登记元信息，`storage_path` 留空）。

- 扩展名白名单 jpg/jpeg/png/webp，大小 ≤10MB（分块读，超限即删除半截文件）
- 落盘名由服务端生成（`安全前缀-uuid.ext`），**不用客户端文件名**，避免路径穿越；同名自动改名
- 同时写一条 `sys_attachment`（`storage_path` 形如 `uploads/xxx.png`）并返回可访问 URL
- `app/main.py` 挂载 `/uploads` 静态目录提供访问
- **已知边界**：静态目录没有鉴权、没有防盗链，属演示级方案；
  生产应换对象存储 + 签名临时 URL

### 演示账号与数据

`python seed.py` 会打印司机端账号（密码取 `.env` 的 `DEMO_PASSWORD`）：

```
driver1 / 123456  —— 赵师傅（D001）   名下有车、已绑定 md_driver.user_id
driver2 / 123456  —— 钱师傅（D002）
driver3 / 123456  —— 孙师傅（D003）
```

第 4 名司机起**刻意不开号**，用于覆盖「有档案、无账号」这种情况。
`python demo_mobile.py` 走真实链路（货量 → 调度 → 确认 → 下发）造出已下发趟次，
幂等：当天已有已下发任务时直接复用。

---

## 求解器

`app/services/solver.py`。三阶段：

```
阶段 1  启发式      按车型优先级 + best-fit 贪心装车 → 毫秒级，保证有解
阶段 2  CP-SAT      按方案权重优化，超时回退启发式
阶段 3  多方案      A 四米二优先 / B 成本最低 / C 大包小包保障 / D 装载率均衡
```

**7 条硬约束**（`validate_solution()` 会独立复核，不复用求解器内部判断）：

1. 门店货量必须全部满足
2. 上午门店只能排上午趟，下午门店只能排下午趟
3. 车辆地形能力必须覆盖门店地形
4. 门店必须属于车辆可跑线路
5. 发车必须达到最低装载量
6. 不能超过最高装载量
7. 四米二 ≤2 趟、大包 ≤2 趟、小包 ≤4 趟

**★ 允许拆单**：一个门店的货量可拆到多个趟次配送。这是必须的 ——
实测单店日货量常达 2290，而四米二单车上限 800，一趟车物理上装不下。
不拆单会导致大量门店无法覆盖。

**实测效果**（16 店 / 40 车 / 日货量 19920）：

| 方案 | 趟次 | 用车 | 四米二使用率 | 装载率 | 货量满足 |
| --- | --- | --- | --- | --- | --- |
| A 四米二优先（CP-SAT） | 29 | 15 | 86.2% | 91.9% | 100% |
| B 成本最低 | 47 | 16 | 23.4% | 99.6% | 98.5% |
| C 大包小包保障 | 47 | 16 | 23.4% | 99.6% | 100% |
| D 装载率均衡 | 25 | 13 | 100% | 99.4% | 99.8% |

---

## 自检

```bash
python check_api.py            # 42 项：认证/权限/CRUD/删除保护
python check_demand.py         # 16 项：货量维护与幂等生成
python check_solver.py         # 17 项：求解器硬约束（--cp-sat 加验精确求解）
python check_scheduling.py     # 35 项：调度全链路
python check_reports.py        # 26 项：报表口径
python check_rules_monitor.py  # 37 项：规则版本 + 监控
```

辅助脚本：

- `demo_mobile.py` —— 造司机端演示数据（走真实下发链路，幂等）
- `check_db.py` —— 直接查库确认落库
- `restore_params.py` —— 还原自检改动的参数值
- `debug_reports.py` —— 诊断报表口径
- `debug_solver.py` —— 打印槽位池与门店安置情况

★ 6 个自检脚本都用 `httpx.Client(..., trust_env=False)`：开着系统代理
（Clash 等，本机 `127.0.0.1:7897`）的机器上，httpx 会读 Windows 的 WinINET
代理设置，把发往 `127.0.0.1` 的请求也交给代理，脚本会误报成 502。
这是环境问题，不是接口问题。

---

## 两个 SQLAlchemy 的坑（已在代码注释里标注）

1. **`str(URL.create(...))` 会把密码渲染成 `***`**，导致 MySQL 报 1045。
   必须用 `render_as_string(hide_password=False)`。见 `app/config.py`。
2. **`func.now()` 在旧版 MySQL 上会生成 `DEFAULT (now())` 语法错误**。
   用 `text("CURRENT_TIMESTAMP")` 代替。见 `app/database.py` 的 `now_default()`。
