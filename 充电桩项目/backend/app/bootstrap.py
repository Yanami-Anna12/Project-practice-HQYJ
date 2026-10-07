"""基线数据初始化：权限、角色、用户、系统参数、规则版本、定时任务。

对应 PDF 3.2 系统管理（菜单/字典/参数/定时任务）与 PDF 9.3 配置管理。
"""

from __future__ import annotations

import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.nodes import DEFAULT_HARD_CONSTRAINTS, DEFAULT_SOFT_CONSTRAINTS
from app.core.database import AsyncSessionLocal
from app.core.enums import DataScope, ReportType
from app.core.security import hash_password
from app.models import (
    AIScheduledJob,
    Permission,
    Project,
    Role,
    RolePermission,
    RuleVersion,
    ScheduleShift,
    Station,
    SystemConfig,
    User,
)
from app.services.rbac import BUILTIN_ROLES

logger = logging.getLogger("app.bootstrap")


# 权限菜单（PDF 3.1 模块总览 + 3.2 系统管理）
PERMISSIONS: list[dict] = [
    # --- 系统管理 ---
    {"code": "system", "name": "系统管理", "perm_type": "menu", "icon": "SettingOutlined", "sort_order": 100, "route_path": "/system"},
    {"code": "system:user", "name": "用户管理", "perm_type": "menu", "parent_code": "system", "route_path": "/system/users", "sort_order": 99},
    {"code": "system:user:create", "name": "新增用户", "perm_type": "button", "parent_code": "system:user", "sort_order": 98},
    {"code": "system:user:update", "name": "编辑用户", "perm_type": "button", "parent_code": "system:user", "sort_order": 97},
    {"code": "system:user:delete", "name": "删除用户", "perm_type": "button", "parent_code": "system:user", "sort_order": 96},
    {"code": "system:role", "name": "角色管理", "perm_type": "menu", "parent_code": "system", "route_path": "/system/roles", "sort_order": 95},
    {"code": "system:role:create", "name": "新增角色", "perm_type": "button", "parent_code": "system:role", "sort_order": 94},
    {"code": "system:role:update", "name": "编辑角色", "perm_type": "button", "parent_code": "system:role", "sort_order": 93},
    {"code": "system:role:delete", "name": "删除角色", "perm_type": "button", "parent_code": "system:role", "sort_order": 92},
    {"code": "system:permission", "name": "菜单权限", "perm_type": "menu", "parent_code": "system", "route_path": "/system/permissions", "sort_order": 91},
    {"code": "system:config", "name": "参数配置", "perm_type": "menu", "parent_code": "system", "route_path": "/system/configs", "sort_order": 90},
    {"code": "system:rule", "name": "规则中心", "perm_type": "menu", "parent_code": "system", "route_path": "/system/rules", "sort_order": 89},
    {"code": "system:log", "name": "日志审计", "perm_type": "menu", "parent_code": "system", "route_path": "/system/logs", "sort_order": 88},

    # --- 工单管理 ---
    {"code": "work_order", "name": "工单管理", "perm_type": "menu", "icon": "ProfileOutlined", "sort_order": 80, "route_path": "/work-orders"},
    {"code": "work_order:create", "name": "工单申请", "perm_type": "button", "parent_code": "work_order", "sort_order": 79},
    {"code": "work_order:accept", "name": "接单/退回", "perm_type": "button", "parent_code": "work_order", "sort_order": 78},
    {"code": "work_order:cancel", "name": "取消工单", "perm_type": "button", "parent_code": "work_order", "sort_order": 77},
    {"code": "work_order:inspect", "name": "巡检录入", "perm_type": "button", "parent_code": "work_order", "sort_order": 76},
    {"code": "work_order:export", "name": "工单导出", "perm_type": "button", "parent_code": "work_order", "sort_order": 75},

    # --- 故障管理 ---
    {"code": "fault", "name": "故障管理", "perm_type": "menu", "icon": "WarningOutlined", "sort_order": 70, "route_path": "/faults"},
    {"code": "fault:report", "name": "故障上报", "perm_type": "button", "parent_code": "fault", "sort_order": 69},
    {"code": "fault:verify", "name": "故障核查", "perm_type": "button", "parent_code": "fault", "sort_order": 68},
    {"code": "fault:export", "name": "故障导出", "perm_type": "button", "parent_code": "fault", "sort_order": 67},

    # --- 作业管理 ---
    {"code": "task", "name": "作业管理", "perm_type": "menu", "icon": "ScheduleOutlined", "sort_order": 60, "route_path": "/tasks"},

    # --- 台账管理 ---
    {"code": "ledger", "name": "台账管理", "perm_type": "menu", "icon": "DatabaseOutlined", "sort_order": 50, "route_path": "/ledger"},
    {"code": "ledger:export", "name": "台账导出", "perm_type": "button", "parent_code": "ledger", "sort_order": 49},
    {"code": "ledger:sync", "name": "台账同步", "perm_type": "button", "parent_code": "ledger", "sort_order": 48},
    {"code": "ledger:extension", "name": "二期字段维护", "perm_type": "button", "parent_code": "ledger", "sort_order": 47},

    # --- 消息中心 ---
    {"code": "message", "name": "消息中心", "perm_type": "menu", "icon": "BellOutlined", "sort_order": 40, "route_path": "/messages"},

    # --- 统计分析 ---
    {"code": "statistics", "name": "统计分析", "perm_type": "menu", "icon": "BarChartOutlined", "sort_order": 30, "route_path": "/statistics"},
    {"code": "statistics:export", "name": "数据导出", "perm_type": "button", "parent_code": "statistics", "sort_order": 29},

    # --- AI Agent 中心 ---
    {"code": "ai", "name": "AI Agent 中心", "perm_type": "menu", "icon": "RobotOutlined", "sort_order": 20, "route_path": "/ai"},
    {"code": "ai:work_order", "name": "智能工单调度", "perm_type": "menu", "parent_code": "ai", "route_path": "/ai/work-order", "sort_order": 19},
    {"code": "ai:fault", "name": "智能故障诊断", "perm_type": "menu", "parent_code": "ai", "route_path": "/ai/fault", "sort_order": 18},
    {"code": "ai:inspection", "name": "智能巡检报告", "perm_type": "menu", "parent_code": "ai", "route_path": "/ai/inspection", "sort_order": 17},
    {"code": "ai:risk", "name": "智能风控", "perm_type": "menu", "parent_code": "ai", "route_path": "/ai/risk", "sort_order": 16},
    {"code": "ai:confirm", "name": "人工确认", "perm_type": "button", "parent_code": "ai", "sort_order": 15},
    {"code": "ai:replan", "name": "异常重排", "perm_type": "button", "parent_code": "ai", "sort_order": 14},
    {"code": "ai:knowledge", "name": "知识库", "perm_type": "menu", "parent_code": "ai", "route_path": "/ai/knowledge", "sort_order": 13},

    # --- 运维分析建议报告 Agent ---
    {"code": "report", "name": "运维报告", "perm_type": "menu", "icon": "FileTextOutlined", "sort_order": 10, "route_path": "/reports"},
    {"code": "report:generate", "name": "生成报告", "perm_type": "button", "parent_code": "report", "sort_order": 9},
    {"code": "report:push", "name": "报告推送", "perm_type": "button", "parent_code": "report", "sort_order": 8},
    {"code": "report:follow_up", "name": "追问下钻", "perm_type": "button", "parent_code": "report", "sort_order": 7},
]


SYSTEM_CONFIGS: list[dict] = [
    # PDF 3.2：工单类型、巡检频率、提醒规则、报告周期、AI 开关
    {"config_key": "work_order.types", "config_name": "工单类型", "config_group": "work_order", "config_value": '["巡视","特巡","消缺","设备检查","其他"]', "value_type": "json", "description": "工单可申请的类型列表"},
    {"config_key": "work_order.inspect_frequencies", "config_name": "巡检频率选项", "config_group": "work_order", "config_value": '["日","周","月"]', "value_type": "json", "description": "巡检频率可选值"},
    {"config_key": "work_order.default_frequency", "config_name": "默认巡检频率", "config_group": "work_order", "config_value": "月", "value_type": "string"},
    {"config_key": "work_order.due_soon_hours", "config_name": "快到期提醒阈值(小时)", "config_group": "work_order", "config_value": "24", "value_type": "int", "description": "工单距离结束时间小于该值时推送紧急提醒（PDF 3.4 定时任务检测）"},
    {"config_key": "work_order.subtask_formula_patrol", "config_name": "巡视类子任务公式", "config_group": "work_order", "config_value": "站点数量 × 巡检周期 × 巡检频率", "value_type": "string"},
    {"config_key": "work_order.subtask_formula_special", "config_name": "特巡子任务公式", "config_group": "work_order", "config_value": "站点数量 × 巡检次数", "value_type": "string"},
    {"config_key": "work_order.subtask_formula_defect", "config_name": "消缺子任务公式", "config_group": "work_order", "config_value": "固定 1 个子任务", "value_type": "string"},

    {"config_key": "fault.levels", "config_name": "故障等级", "config_group": "fault", "config_value": '["一般","严重","危急"]', "value_type": "json"},
    {"config_key": "fault.sla_hours", "config_name": "故障响应时限(小时)", "config_group": "fault", "config_value": '{"一般":72,"严重":24,"危急":4}', "value_type": "json", "description": "用于风控与超期提醒"},
    {"config_key": "fault.risk_keywords", "config_name": "故障高风险关键词", "config_group": "fault", "config_value": '["起火","冒烟","漏电","触电","爆炸","绝缘失效","烧毁"]', "value_type": "json"},

    {"config_key": "inspection.remark_max_length", "config_name": "巡检备注最大字数", "config_group": "inspection", "config_value": "200", "value_type": "int", "description": "PDF 3.4：200 字备注"},
    {"config_key": "inspection.require_images", "config_name": "巡检必须上传照片", "config_group": "inspection", "config_value": "true", "value_type": "bool"},
    {"config_key": "inspection.require_gps", "config_name": "巡检必须 GPS 签到", "config_group": "inspection", "config_value": "false", "value_type": "bool", "description": "开启后巡检录入需带签到定位（PDF 4.9 定位异常检测）"},

    {"config_key": "report.daily_hour", "config_name": "日报告生成时间(时)", "config_group": "report", "config_value": "2", "value_type": "int", "description": "日报告 T+1 凌晨 2 点（PDF 3.12）"},
    {"config_key": "report.weekly_hour", "config_name": "周报告生成时间(时)", "config_group": "report", "config_value": "3", "value_type": "int", "description": "周报告每周一凌晨 3 点"},
    {"config_key": "report.monthly_hour", "config_name": "月报告生成时间(时)", "config_group": "report", "config_value": "4", "value_type": "int", "description": "月报告每月 1 日凌晨 4 点"},
    {"config_key": "report.push_channels", "config_name": "默认推送通道", "config_group": "report", "config_value": '["站内信"]', "value_type": "json", "description": "可选：站内信/微信/飞书/邮件"},

    {"config_key": "ai.enabled", "config_name": "AI 总开关", "config_group": "ai", "config_value": "true", "value_type": "bool"},
    {"config_key": "ai.llm_model", "config_name": "LLM 模型", "config_group": "ai", "config_value": "deepseek-chat", "value_type": "string"},
    {"config_key": "ai.kb_top_k", "config_name": "知识库召回条数", "config_group": "ai", "config_value": "5", "value_type": "int"},
    {"config_key": "ai.max_replan", "config_name": "最大重排次数", "config_group": "ai", "config_value": "3", "value_type": "int", "description": "PDF 4.9：replan_count 限制，避免无限循环"},
    {"config_key": "ai.require_confirm", "config_name": "必须人工确认", "config_group": "ai", "config_value": "true", "value_type": "bool", "description": "PDF 4.8：真实商业项目必须有人工确认环节"},

    {"config_key": "ledger.extinguisher_types", "config_name": "灭火器类型选项", "config_group": "ledger", "config_value": '["无","干粉","二氧化碳","水基","洁净气体"]', "value_type": "json", "description": "PDF 3.10 二期：增加「无」选项"},
    {"config_key": "ledger.show_gun_count", "config_name": "显示充电枪数量", "config_group": "ledger", "config_value": "true", "value_type": "bool", "description": "PDF 3.10 二期扩展"},
    {"config_key": "ledger.camera_fields", "config_name": "摄像头字段", "config_group": "ledger", "config_value": '["球机数量","枪机数量","监控密码"]', "value_type": "json"},
]


SCHEDULED_JOBS: list[dict] = [
    {"job_code": "daily_report", "job_name": "日运营简报生成", "job_type": "report", "run_hour": 2, "cron_expr": "0 2 * * *", "params": {"report_type": ReportType.DAILY.value}},
    {"job_code": "weekly_report", "job_name": "周运维分析报告生成", "job_type": "report", "run_hour": 3, "weekday": 1, "cron_expr": "0 3 * * 1", "params": {"report_type": ReportType.WEEKLY.value}},
    {"job_code": "monthly_report", "job_name": "月度深度报告生成", "job_type": "report", "run_hour": 4, "day_of_month": 1, "cron_expr": "0 4 1 * *", "params": {"report_type": ReportType.MONTHLY.value}},
    {"job_code": "daily_statistics", "job_name": "统计日报生成", "job_type": "stat", "run_hour": 1, "cron_expr": "0 1 * * *"},
    {"job_code": "due_soon_reminder", "job_name": "工单快到期/逾期提醒", "job_type": "reminder", "run_hour": 8, "cron_expr": "0 8,14,20 * * *", "params": {"hours": 24}},
    {"job_code": "exception_scan", "job_name": "异常事件扫描", "job_type": "monitor", "run_hour": 0, "cron_expr": "*/30 * * * *"},
]


async def ensure_permissions(db: AsyncSession) -> int:
    existing = {
        p.code for p in (await db.execute(select(Permission))).scalars().all()
    }
    created = 0
    for item in PERMISSIONS:
        if item["code"] in existing:
            continue
        db.add(Permission(**item))
        created += 1
    if created:
        await db.commit()
    return created


async def ensure_roles(db: AsyncSession) -> int:
    created = 0
    for item in BUILTIN_ROLES:
        existing = (
            await db.execute(select(Role).where(Role.code == item["code"]))
        ).scalar_one_or_none()
        if existing:
            continue
        db.add(
            Role(
                code=item["code"],
                name=item["name"],
                data_scope=item["data_scope"],
                sort_order=item["sort_order"],
                remark=item["remark"],
                is_builtin=True,
            )
        )
        created += 1
    if created:
        await db.commit()
    return created


async def ensure_role_permissions(db: AsyncSession) -> int:
    """平台/项目/站点管理员获得全部菜单权限；运维人员获得作业类权限。"""
    roles = {r.code: r for r in (await db.execute(select(Role))).scalars().all()}
    perms = {p.code: p for p in (await db.execute(select(Permission))).scalars().all()}

    full = set(perms.keys())
    inspector_codes = {
        "work_order",
        "work_order:accept",
        "work_order:inspect",
        "fault",
        "fault:report",
        "task",
        "message",
        "statistics",
        "ai:fault",
        "ledger",
    }

    plan = {
        "platform_admin": full,
        "project_admin": full,
        "station_admin": full - {"system:user:delete", "system:role:delete", "system:config", "system:rule"},
        "personal_admin": full - {"system", "system:user", "system:role", "system:permission", "system:config", "system:rule", "system:log"},
        "inspector": inspector_codes,
    }

    created = 0
    for role_code, codes in plan.items():
        role = roles.get(role_code)
        if role is None:
            continue
        current = {
            rp.permission_id
            for rp in (
                await db.execute(
                    select(RolePermission).where(RolePermission.role_id == role.id)
                )
            ).scalars().all()
        }
        for code in codes:
            perm = perms.get(code)
            if perm is None or perm.id in current:
                continue
            db.add(RolePermission(role_id=role.id, permission_id=perm.id))
            created += 1
    if created:
        await db.commit()
    return created


async def ensure_configs(db: AsyncSession) -> int:
    existing = {
        c.config_key for c in (await db.execute(select(SystemConfig))).scalars().all()
    }
    created = 0
    for item in SYSTEM_CONFIGS:
        if item["config_key"] in existing:
            continue
        db.add(SystemConfig(**item))
        created += 1
    if created:
        await db.commit()
    return created


async def ensure_rule_version(db: AsyncSession) -> str:
    existing = (
        await db.execute(select(RuleVersion).where(RuleVersion.is_active.is_(True)))
    ).scalars().first()
    if existing:
        return existing.version

    record = RuleVersion(
        version="v1.0.0",
        rule_snapshot={"hard": DEFAULT_HARD_CONSTRAINTS, "soft": DEFAULT_SOFT_CONSTRAINTS},
        hard_constraints=DEFAULT_HARD_CONSTRAINTS,
        soft_constraints=DEFAULT_SOFT_CONSTRAINTS,
        is_active=True,
        change_log="初始规则版本：硬约束来源《充电桩运维管理 AI Agent 项目技术方案》3.4/3.5/3.3/4.9",
    )
    db.add(record)
    await db.commit()
    return record.version


async def ensure_jobs(db: AsyncSession) -> int:
    existing = {
        j.job_code for j in (await db.execute(select(AIScheduledJob))).scalars().all()
    }
    created = 0
    for item in SCHEDULED_JOBS:
        if item["job_code"] in existing:
            continue
        db.add(AIScheduledJob(**item))
        created += 1
    if created:
        await db.commit()
    return created


async def ensure_users(db: AsyncSession) -> int:
    """创建默认账号（仅当用户表为空时）。"""
    count = int((await db.execute(select(func.count(User.id)))).scalar() or 0)
    if count > 0:
        return 0

    roles = {r.code: r for r in (await db.execute(select(Role))).scalars().all()}
    projects = list((await db.execute(select(Project))).scalars().all())
    stations = list((await db.execute(select(Station))).scalars().all())

    project = projects[0] if projects else None
    station = stations[0] if stations else None

    defaults = [
        {
            "username": "admin",
            "password": "admin123",
            "real_name": "平台管理员",
            "role": "platform_admin",
            "phone": "13800000001",
            "user_type": "admin",
            "project_id": project.id if project else None,
            "station_id": None,
        },
        {
            "username": "project_admin",
            "password": "123456",
            "real_name": "项目管理员",
            "role": "project_admin",
            "phone": "13800000002",
            "user_type": "admin",
            "project_id": project.id if project else None,
            "station_id": None,
        },
        {
            "username": "station_admin",
            "password": "123456",
            "real_name": "站点管理员",
            "role": "station_admin",
            "phone": "13800000003",
            "user_type": "admin",
            "project_id": project.id if project else None,
            "station_id": station.id if station else None,
        },
        {
            "username": "inspector",
            "password": "123456",
            "real_name": "张巡检",
            "role": "inspector",
            "phone": "13800000004",
            "user_type": "staff",
            "project_id": project.id if project else None,
            "station_id": station.id if station else None,
            "skills": "充电桩,电气,通信",
        },
        {
            "username": "inspector2",
            "password": "123456",
            "real_name": "李运维",
            "role": "inspector",
            "phone": "13800000005",
            "user_type": "staff",
            "project_id": project.id if project else None,
            "station_id": stations[1].id if len(stations) > 1 else None,
            "skills": "储能,消防,巡检",
        },
        {
            "username": "inspector3",
            "password": "123456",
            "real_name": "王检修",
            "role": "inspector",
            "phone": "13800000006",
            "user_type": "staff",
            "project_id": project.id if project else None,
            "station_id": stations[2].id if len(stations) > 2 else None,
            "skills": "直流桩,功率模块,电气",
        },
        {
            "username": "inspector4",
            "password": "123456",
            "real_name": "赵巡检",
            "role": "inspector",
            "phone": "13800000007",
            "user_type": "staff",
            "project_id": project.id if project else None,
            "station_id": stations[3].id if len(stations) > 3 else None,
            "skills": "通信,监控,巡检",
        },
        {
            "username": "inspector5",
            "password": "123456",
            "real_name": "陈工",
            "role": "inspector",
            "phone": "13800000008",
            "user_type": "staff",
            "project_id": project.id if project else None,
            "station_id": stations[4].id if len(stations) > 4 else None,
            "skills": "计费,刷卡模块,巡检",
        },
        {
            "username": "inspector6",
            "password": "123456",
            "real_name": "周维护",
            "role": "inspector",
            "phone": "13800000009",
            "user_type": "staff",
            "project_id": project.id if project else None,
            "station_id": stations[5].id if len(stations) > 5 else None,
            "skills": "消防,绝缘,应急处置",
        },
    ]

    created = 0
    for item in defaults:
        role = roles.get(item["role"])
        user = User(
            username=item["username"],
            real_name=item["real_name"],
            hashed_password=hash_password(item["password"]),
            phone=item.get("phone"),
            email=f"{item['username']}@example.com",
            role_id=role.id if role else None,
            project_id=item.get("project_id"),
            station_id=item.get("station_id"),
            user_type=item["user_type"],
            skills=item.get("skills"),
            on_duty=True,
        )
        db.add(user)
        created += 1
    await db.commit()

    # 为运维人员排班（近 30 天）
    from datetime import date, timedelta

    inspectors = (
        await db.execute(select(User).where(User.user_type == "staff"))
    ).scalars().all()
    today = date.today()
    for person in inspectors:
        for offset in range(-7, 30):
            db.add(
                ScheduleShift(
                    user_id=person.id,
                    station_id=person.station_id,
                    shift_date=today + timedelta(days=offset),
                    shift_name="白班",
                    start_time="08:00",
                    end_time="18:00",
                    available=True,
                )
            )
    await db.commit()
    return created


async def backfill_user_scope(db: AsyncSession) -> int:
    """按站点 / 项目把用户铺开归属，保证每个项目都有可用人员。

    首次启动时用户先于演示数据创建，user.project_id 为空，会影响
    数据权限过滤与智能调度的人员筛选（H3 人员可用性约束）。
    这里做幂等分配：
      - 管理员：按顺序分配到各项目（保证每个项目都有管理员）
      - 一线人员：按顺序分配到各站点，并继承该站点所属项目
    这样任意项目下都能找到可用执行人，同时保留项目级数据权限语义。
    """
    projects = list((await db.execute(select(Project).order_by(Project.code))).scalars().all())
    stations = list((await db.execute(select(Station).order_by(Station.code))).scalars().all())
    if not projects:
        return 0

    users = list((await db.execute(select(User).order_by(User.username))).scalars().all())
    admins = [u for u in users if u.user_type != "staff"]
    staff = [u for u in users if u.user_type == "staff"]

    fixed = 0

    # 一线人员：先按项目轮转、再在项目内按站点轮转，
    # 保证每个项目至少有一名可用执行人（H3 人员可用性约束）
    stations_by_project: dict[str, list[Station]] = {}
    for station in stations:
        if station.project_id:
            stations_by_project.setdefault(station.project_id, []).append(station)

    for idx, user in enumerate(staff):
        project = projects[idx % len(projects)]
        project_stations = stations_by_project.get(project.id) or []
        station = project_stations[(idx // len(projects)) % len(project_stations)] if project_stations else None
        target_station = station.id if station else None
        if user.project_id != project.id or user.station_id != target_station:
            user.project_id = project.id
            user.station_id = target_station
            fixed += 1

    # 管理员：轮转分配到项目（无站点绑定）
    for idx, user in enumerate(admins):
        target_project = projects[idx % len(projects)].id
        if user.project_id != target_project:
            user.project_id = target_project
            fixed += 1

    if fixed:
        await db.commit()
    return fixed


async def ensure_baseline_data(with_demo: bool = True) -> dict:
    """应用启动时调用：确保基线数据存在。"""
    async with AsyncSessionLocal() as db:
        result: dict = {}
        result["permissions"] = await ensure_permissions(db)
        result["roles"] = await ensure_roles(db)
        await ensure_role_permissions(db)
        result["configs"] = await ensure_configs(db)
        result["rule_version"] = await ensure_rule_version(db)
        await ensure_jobs(db)

        # 用户先于演示数据创建：工单/巡检/排班需要执行人；
        # seed_demo_data 内部也会兜底调用 ensure_users（用户表为空时）。
        result["users"] = await ensure_users(db)

        # 演示数据（项目/站点/桩/工单/故障/巡检/台账/知识库/统计/报告）
        from app.seed import seed_demo_data

        seeded = False
        if with_demo:
            seeded = await seed_demo_data(db)
        result["seeded"] = seeded

        # 用户归属补齐（幂等）：必须在项目/站点就绪之后
        result["users_fixed"] = await backfill_user_scope(db)

        return result
