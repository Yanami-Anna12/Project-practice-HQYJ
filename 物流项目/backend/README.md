# 车辆智能调度 Agent —— 后端

FastAPI + SQLAlchemy 2.0 + MySQL + OR-Tools CP-SAT。

**项目总览与快速开始见上级目录的 `README.md`**，本文件只讲后端。

---

## 启动

```bash
# 使用 py312 环境（base 是 3.7.13，太旧）
C:\Users\12966\miniconda3\envs\py312\python.exe -m pip install -r requirements.txt
python seed.py                # 建库 + 初始数据（幂等）
python seed.py --reset        # 先删表重建（会清空数据）
python run.py                 # http://127.0.0.1:8000
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
│   ├── database.py      连接、会话、建库建表
│   ├── errors.py        统一错误（全部返回 {"error": "..."}）
│   ├── security.py      bcrypt 密码哈希 + JWT
│   ├── deps.py          ★ 权限依赖 require_permission()
│   ├── menus.py         菜单定义与服务端裁剪
│   ├── schemas.py       Pydantic v2 请求/响应模型
│   ├── main.py          应用装配
│   ├── models/          28 张表的 ORM 模型
│   │   ├── rbac.py        用户/角色/权限 + 中间表
│   │   ├── sys.py         字典/参数/附件
│   │   ├── audit.py       审计日志
│   │   ├── master.py      门店/线路/映射/车辆类型/车辆/司机/地形
│   │   ├── scheduling.py  货量/任务/方案/明细/确认/下发/异常/重排/报告
│   │   └── rule.py        规则版本
│   ├── routers/         11 个路由模块
│   └── services/
│       ├── rbac.py        ★ 有效权限计算（多角色并集）
│       ├── audit.py       ★ 审计写入（全项目唯一入口）
│       ├── demand.py      货量维护 + 可重复的演示数据生成
│       ├── solver.py      ★ 三阶段混合求解 + 独立校验
│       ├── scheduling.py  调度任务落库
│       ├── reports.py     5 类报表聚合
│       ├── rules.py       规则总览 / 冲突检测 / 版本快照与回滚
│       └── monitor.py     监控指标 / 预警 / 集成状态
├── seed.py              初始数据
├── run.py               开发服务器
├── check_*.py           6 个自检脚本（共 173 项）
└── requirements.txt
```

---

## 数据模型（28 张表）

| 分类 | 表 |
| --- | --- |
| RBAC | `sys_user`、`sys_role`、`sys_permission`、`sys_user_role`、`sys_role_permission` |
| 系统配置 | `sys_dict_type`、`sys_dict_item`、`sys_param`、`sys_attachment` |
| 审计与规则 | `sys_audit_log`、`sys_rule_version` |
| 基础主数据 | `md_store`、`md_route`、`md_store_route`、`md_vehicle_type`、`md_vehicle`、`md_driver`、`md_terrain_rule`、`md_terrain_matrix` |
| 调度业务 | `md_store_demand`、`scheduling_task`、`scheduling_plan`、`scheduling_plan_detail`、`scheduling_confirmation`、`dispatch_record`、`exception_event`、`replan_record`、`scheduling_report` |

初始数据（数值取自需求文档 一.3「现有条件」）：

- 车辆类型：四米二 630-800 日 2 趟 / 大包 300-420 日 2 趟 / 小包 1-300 日 4 趟
- 车辆 **40 台 = 28 + 3 + 9**
- 门店 16 个（3 个交界门店）、线路 5 条、映射 19 条
- 地形通行矩阵 9 格（严控地形只允许「全能去」）

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

- `check_db.py` —— 直接查库确认落库
- `restore_params.py` —— 还原自检改动的参数值
- `debug_reports.py` —— 诊断报表口径
- `debug_solver.py` —— 打印槽位池与门店安置情况

---

## 两个 SQLAlchemy 的坑（已在代码注释里标注）

1. **`str(URL.create(...))` 会把密码渲染成 `***`**，导致 MySQL 报 1045。
   必须用 `render_as_string(hide_password=False)`。见 `app/config.py`。
2. **`func.now()` 在旧版 MySQL 上会生成 `DEFAULT (now())` 语法错误**。
   用 `text("CURRENT_TIMESTAMP")` 代替。见 `app/database.py` 的 `now_default()`。
