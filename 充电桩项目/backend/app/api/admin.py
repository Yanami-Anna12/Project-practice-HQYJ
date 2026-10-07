"""管理后台接口 —— PDF 5.2 管理后台核心接口 + 3.1/3.2/3.3/3.7 模块。

/api/v1/admin/roles            角色管理
/api/v1/admin/users            用户管理
/api/v1/admin/permissions      权限菜单（树形，默认折叠）
/api/v1/admin/projects         项目
/api/v1/admin/stations         站点（含二期灭火器/摄像头/充电枪字段）
/api/v1/admin/piles            充电桩
/api/v1/admin/ledger           台账
/api/v1/admin/configs          系统参数（热更新）
/api/v1/admin/rules            规则版本
/api/v1/admin/logs             操作日志 / 登录日志
/api/v1/admin/shifts           人员排班
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select

from app.core.deps import CurrentUser, DbSession, require_permission
from app.core.enums import DataScope
from app.core.errors import BizError, NotFoundError
from app.core.response import ApiResponse, PageData
from app.models import (
    AssetLedger,
    ChargingPile,
    LoginLog,
    OperationLog,
    Permission,
    Project,
    Role,
    RuleVersion,
    ScheduleShift,
    Station,
    SystemConfig,
    User,
)
from app.schemas import (
    ChargingPileOut,
    LedgerOut,
    PermissionOut,
    PermissionTreeNode,
    ProjectOut,
    RoleCreate,
    RoleOut,
    RoleUpdate,
    StationExtensionUpdate,
    StationOut,
    UserCreate,
    UserOut,
    UserUpdate,
)
from app.services import asset as asset_service
from app.services import audit as audit_service
from app.services import rbac as rbac_service

router = APIRouter(prefix="/admin", tags=["管理后台"])


# ================================================================ 角色


@router.get("/roles", response_model=ApiResponse[PageData[RoleOut]], summary="角色列表")
async def list_roles(
    db: DbSession,
    user: CurrentUser,
    keyword: str | None = Query(default=None, description="识别码/名称/备注 模糊查询"),
    data_scope: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
):
    roles, total = await rbac_service.list_roles(
        db,
        keyword=keyword,
        data_scope=data_scope,
        limit=page_size,
        offset=(page - 1) * page_size,
    )
    items = [RoleOut.model_validate(r) for r in roles]
    return ApiResponse.ok(PageData.build(items, total, page, page_size))


@router.post("/roles", response_model=ApiResponse[RoleOut], summary="新增角色")
async def create_role(payload: RoleCreate, db: DbSession, user: CurrentUser):
    role = await rbac_service.create_role(
        db,
        code=payload.code,
        name=payload.name,
        data_scope=payload.data_scope,
        sort_order=payload.sort_order,
        remark=payload.remark,
        permission_codes=payload.permission_codes,
    )
    await audit_service.log_operation(
        db,
        module="角色管理",
        action="新增角色",
        user=user,
        target_type="role",
        target_id=role.id,
        description=f"新增角色 {role.name}（{role.code}），数据权限 {role.data_scope}",
        after={"code": role.code, "name": role.name, "data_scope": role.data_scope},
    )
    return ApiResponse.ok(RoleOut.model_validate(role))


@router.put("/roles/{role_id}", response_model=ApiResponse[RoleOut], summary="编辑角色")
async def update_role(
    role_id: str, payload: RoleUpdate, db: DbSession, user: CurrentUser
):
    before = await db.get(Role, role_id)
    if before is None:
        raise NotFoundError("角色不存在")
    snapshot = {
        "name": before.name,
        "data_scope": before.data_scope,
        "sort_order": before.sort_order,
        "remark": before.remark,
    }
    role = await rbac_service.update_role(
        db,
        role_id=role_id,
        name=payload.name,
        data_scope=payload.data_scope,
        sort_order=payload.sort_order,
        remark=payload.remark,
        status=payload.status,
        permission_codes=payload.permission_codes,
    )
    await audit_service.log_operation(
        db,
        module="角色管理",
        action="编辑角色",
        user=user,
        target_type="role",
        target_id=role.id,
        description=f"编辑角色 {role.name}",
        before=snapshot,
        after={
            "name": role.name,
            "data_scope": role.data_scope,
            "sort_order": role.sort_order,
        },
    )
    return ApiResponse.ok(RoleOut.model_validate(role))


@router.delete("/roles/{role_id}", response_model=ApiResponse[dict], summary="删除角色")
async def delete_role(role_id: str, db: DbSession, user: CurrentUser):
    role = await db.get(Role, role_id)
    name = role.name if role else role_id
    await rbac_service.delete_role(db, role_id)
    await audit_service.log_operation(
        db,
        module="角色管理",
        action="删除角色",
        user=user,
        target_type="role",
        target_id=role_id,
        description=f"删除角色 {name}",
    )
    return ApiResponse.ok({"deleted": True})


@router.get(
    "/roles/{role_id}/permissions",
    response_model=ApiResponse[dict],
    summary="查看角色权限",
)
async def role_permissions(role_id: str, db: DbSession, user: CurrentUser):
    codes = await rbac_service.role_permission_codes(db, role_id)
    return ApiResponse.ok({"role_id": role_id, "permission_codes": codes})


# ================================================================ 权限菜单


@router.get(
    "/permissions",
    response_model=ApiResponse[list[PermissionOut]],
    summary="权限列表",
)
async def list_permissions(db: DbSession, user: CurrentUser):
    rows = (
        await db.execute(
            select(Permission).order_by(Permission.sort_order.desc(), Permission.code)
        )
    ).scalars().all()
    return ApiResponse.ok([PermissionOut.model_validate(p) for p in rows])


@router.get(
    "/permissions/tree",
    response_model=ApiResponse[list[PermissionTreeNode]],
    summary="树形权限菜单（默认折叠）",
)
async def permission_tree(db: DbSession, user: CurrentUser):
    rows = (
        await db.execute(
            select(Permission).order_by(Permission.sort_order.desc(), Permission.code)
        )
    ).scalars().all()
    nodes = {
        p.code: PermissionTreeNode(
            code=p.code,
            name=p.name,
            perm_type=p.perm_type,
            route_path=p.route_path,
            icon=p.icon,
            data_scope=p.data_scope,
        )
        for p in rows
    }
    roots: list[PermissionTreeNode] = []
    for p in rows:
        node = nodes[p.code]
        if p.parent_code and p.parent_code in nodes:
            nodes[p.parent_code].children.append(node)
        else:
            roots.append(node)
    return ApiResponse.ok(roots)


# ================================================================ 用户


@router.get("/users", response_model=ApiResponse[PageData[UserOut]], summary="用户列表")
async def list_users(
    db: DbSession,
    user: CurrentUser,
    keyword: str | None = Query(default=None, description="用户名/姓名/手机号 模糊查询"),
    project_id: str | None = None,
    station_id: str | None = None,
    role_id: str | None = None,
    status: bool | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
):
    users, total = await rbac_service.list_users(
        db,
        keyword=keyword,
        project_id=project_id,
        station_id=station_id,
        role_id=role_id,
        status=status,
        limit=page_size,
        offset=(page - 1) * page_size,
    )
    items = []
    for u in users:
        out = UserOut.model_validate(u)
        out.project_name = u.project.name if u.project else None
        out.station_name = u.station.name if u.station else None
        out.data_scope = u.role.data_scope if u.role else None
        items.append(out)
    return ApiResponse.ok(PageData.build(items, total, page, page_size))


@router.post(
    "/users",
    response_model=ApiResponse[UserOut],
    summary="新增用户",
    dependencies=[Depends(require_permission("system:user:create"))],
)
async def create_user(payload: UserCreate, db: DbSession, user: CurrentUser):
    created = await rbac_service.create_user(
        db,
        username=payload.username,
        real_name=payload.real_name,
        password=payload.password,
        phone=payload.phone,
        email=payload.email,
        role_id=payload.role_id,
        project_id=payload.project_id,
        station_id=payload.station_id,
        user_type=payload.user_type,
        skills=payload.skills,
    )
    await audit_service.log_operation(
        db,
        module="用户管理",
        action="新增用户",
        user=user,
        target_type="user",
        target_id=created.id,
        description=f"新增用户 {created.real_name}（{created.username}）",
        after={"username": created.username, "real_name": created.real_name},
    )
    return ApiResponse.ok(UserOut.model_validate(created))


@router.put(
    "/users/{user_id}",
    response_model=ApiResponse[UserOut],
    summary="编辑用户",
    dependencies=[Depends(require_permission("system:user:update"))],
)
async def update_user(
    user_id: str, payload: UserUpdate, db: DbSession, user: CurrentUser
):
    target = await db.get(User, user_id)
    if target is None:
        raise NotFoundError("用户不存在")
    before = {
        "real_name": target.real_name,
        "phone": target.phone,
        "role_id": target.role_id,
        "project_id": target.project_id,
        "station_id": target.station_id,
        "status": target.status,
    }
    updated = await rbac_service.update_user(
        db,
        user_id=user_id,
        real_name=payload.real_name,
        phone=payload.phone,
        email=payload.email,
        role_id=payload.role_id,
        project_id=payload.project_id,
        station_id=payload.station_id,
        status=payload.status,
        password=payload.password,
        skills=payload.skills,
        on_duty=payload.on_duty,
    )
    await audit_service.log_operation(
        db,
        module="用户管理",
        action="编辑用户",
        user=user,
        target_type="user",
        target_id=user_id,
        description=f"编辑用户 {updated.real_name}",
        before=before,
        after={
            "real_name": updated.real_name,
            "phone": updated.phone,
            "role_id": updated.role_id,
            "project_id": updated.project_id,
            "station_id": updated.station_id,
            "status": updated.status,
        },
    )
    out = UserOut.model_validate(updated)
    out.project_name = updated.project.name if updated.project else None
    out.station_name = updated.station.name if updated.station else None
    out.data_scope = updated.role.data_scope if updated.role else None
    return ApiResponse.ok(out)


@router.delete(
    "/users/{user_id}",
    response_model=ApiResponse[dict],
    summary="删除用户",
    dependencies=[Depends(require_permission("system:user:delete"))],
)
async def delete_user(user_id: str, db: DbSession, user: CurrentUser):
    await rbac_service.delete_user(db, user_id)
    await audit_service.log_operation(
        db,
        module="用户管理",
        action="删除用户",
        user=user,
        target_type="user",
        target_id=user_id,
        description="删除用户",
    )
    return ApiResponse.ok({"deleted": True})


# ================================================================ 项目 / 站点 / 桩


@router.get("/projects", response_model=ApiResponse[list[ProjectOut]], summary="项目列表")
async def list_projects(db: DbSession, user: CurrentUser):
    rows = (await db.execute(select(Project).order_by(Project.name))).scalars().all()
    return ApiResponse.ok([ProjectOut.model_validate(p) for p in rows])


@router.get(
    "/stations",
    response_model=ApiResponse[PageData[StationOut]],
    summary="站点列表（含二期扩展字段）",
)
async def list_stations(
    db: DbSession,
    user: CurrentUser,
    project_id: str | None = None,
    keyword: str | None = Query(default=None, description="站点编码/名称/地址 模糊查询"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
):
    conditions = []
    if project_id:
        conditions.append(Station.project_id == project_id)
    if keyword:
        from sqlalchemy import or_

        conditions.append(
            or_(
                Station.code.ilike(f"%{keyword}%"),
                Station.name.ilike(f"%{keyword}%"),
                Station.address.ilike(f"%{keyword}%"),
            )
        )

    base = select(Station)
    count_stmt = select(func.count(Station.id))
    for cond in conditions:
        base = base.where(cond)
        count_stmt = count_stmt.where(cond)
    total = int((await db.execute(count_stmt)).scalar() or 0)
    rows = (
        await db.execute(
            base.order_by(Station.code).limit(page_size).offset((page - 1) * page_size)
        )
    ).scalars().all()

    projects = {p.id: p.name for p in (await db.execute(select(Project))).scalars().all()}
    pile_counts = dict(
        (
            await db.execute(
                select(ChargingPile.station_id, func.count(ChargingPile.id)).group_by(
                    ChargingPile.station_id
                )
            )
        ).all()
    )

    items = []
    for s in rows:
        out = StationOut.model_validate(s)
        out.project_name = projects.get(s.project_id or "")
        out.pile_count = int(pile_counts.get(s.id, 0))
        items.append(out)
    return ApiResponse.ok(PageData.build(items, total, page, page_size))


@router.put(
    "/stations/{station_id}/extensions",
    response_model=ApiResponse[StationOut],
    summary="站点二期扩展字段（灭火器/摄像头）",
)
async def update_station_extensions(
    station_id: str, payload: StationExtensionUpdate, db: DbSession, user: CurrentUser
):
    """PDF 3.10：灭火器增加「无」选项、单瓶规格与生产日期动态表单；摄像头球机/枪机数量与密码。"""
    station = await asset_service.update_station_extensions(
        db,
        station_id=station_id,
        extinguisher_type=payload.extinguisher_type,
        extinguisher_spec=payload.extinguisher_spec,
        extinguisher_produced_at=payload.extinguisher_produced_at,
        dome_camera_count=payload.dome_camera_count,
        bullet_camera_count=payload.bullet_camera_count,
        camera_password=payload.camera_password,
    )
    await audit_service.log_operation(
        db,
        module="台账管理",
        action="修改站点扩展字段",
        user=user,
        target_type="station",
        target_id=station_id,
        description=f"修改站点 {station.name} 的灭火器/摄像头字段",
        after={
            "extinguisher_type": station.extinguisher_type,
            "extinguisher_spec": station.extinguisher_spec,
            "dome_camera_count": station.dome_camera_count,
            "bullet_camera_count": station.bullet_camera_count,
        },
    )
    return ApiResponse.ok(StationOut.model_validate(station))


@router.get(
    "/stations/{station_id}/navigation",
    response_model=ApiResponse[dict],
    summary="站点导航与地图分享（PDF 3.10）",
)
async def station_navigation(station_id: str, db: DbSession, user: CurrentUser):
    return ApiResponse.ok(await asset_service.station_navigation(db, station_id))


@router.get(
    "/stations/options",
    response_model=ApiResponse[list[dict]],
    summary="站点下拉选项（项目联动）",
)
async def station_options(
    db: DbSession, user: CurrentUser, project_id: str | None = None
):
    return ApiResponse.ok(await rbac_service.station_options(db, project_id))


@router.get(
    "/piles",
    response_model=ApiResponse[PageData[ChargingPileOut]],
    summary="充电桩列表（含充电枪数量）",
)
async def list_piles(
    db: DbSession,
    user: CurrentUser,
    station_id: str | None = None,
    keyword: str | None = Query(default=None, description="资产码/名称/型号 模糊查询"),
    status: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
):
    conditions = []
    if station_id:
        conditions.append(ChargingPile.station_id == station_id)
    if status:
        conditions.append(ChargingPile.status == status)
    if keyword:
        from sqlalchemy import or_

        conditions.append(
            or_(
                ChargingPile.asset_code.ilike(f"%{keyword}%"),
                ChargingPile.name.ilike(f"%{keyword}%"),
                ChargingPile.model.ilike(f"%{keyword}%"),
            )
        )

    base = select(ChargingPile)
    count_stmt = select(func.count(ChargingPile.id))
    for cond in conditions:
        base = base.where(cond)
        count_stmt = count_stmt.where(cond)
    total = int((await db.execute(count_stmt)).scalar() or 0)
    rows = (
        await db.execute(
            base.order_by(ChargingPile.asset_code)
            .limit(page_size)
            .offset((page - 1) * page_size)
        )
    ).scalars().all()

    station_names = {
        s.id: s.name for s in (await db.execute(select(Station))).scalars().all()
    }
    items = []
    for p in rows:
        out = ChargingPileOut.model_validate(p)
        out.station_name = station_names.get(p.station_id or "")
        items.append(out)
    return ApiResponse.ok(PageData.build(items, total, page, page_size))


@router.get(
    "/ledger",
    response_model=ApiResponse[PageData[LedgerOut]],
    summary="台账查询（站台台账 / 充电桩台账）",
)
async def list_ledger(
    db: DbSession,
    user: CurrentUser,
    ledger_type: str | None = Query(default=None, description="station / pile"),
    keyword: str | None = None,
    project_id: str | None = None,
    station_id: str | None = None,
    status: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
):
    rows, total = await asset_service.list_ledger(
        db,
        ledger_type=ledger_type,
        keyword=keyword,
        project_id=project_id,
        station_id=station_id,
        status=status,
        limit=page_size,
        offset=(page - 1) * page_size,
    )
    return ApiResponse.ok(
        PageData.build([LedgerOut.model_validate(r) for r in rows], total, page, page_size)
    )


@router.post("/ledger/sync", response_model=ApiResponse[dict], summary="同步台账数据")
async def sync_ledger(db: DbSession, user: CurrentUser):
    result = await asset_service.sync_ledger(db)
    await audit_service.log_operation(
        db,
        module="台账管理",
        action="同步台账",
        user=user,
        description=f"台账同步：新增 {result['created']}，更新 {result['updated']}",
        after=result,
    )
    return ApiResponse.ok(result)


@router.get(
    "/piles/status-summary",
    response_model=ApiResponse[dict],
    summary="充电桩状态汇总（含充电枪总数）",
)
async def pile_status_summary(db: DbSession, user: CurrentUser):
    return ApiResponse.ok(await asset_service.pile_status_summary(db))


# ================================================================ 系统参数 / 规则


@router.get("/configs", response_model=ApiResponse[list[dict]], summary="系统参数列表")
async def list_configs(
    db: DbSession, user: CurrentUser, group: str | None = Query(default=None)
):
    stmt = select(SystemConfig).order_by(SystemConfig.config_group, SystemConfig.config_key)
    if group:
        stmt = stmt.where(SystemConfig.config_group == group)
    rows = (await db.execute(stmt)).scalars().all()
    return ApiResponse.ok(
        [
            {
                "id": c.id,
                "config_key": c.config_key,
                "config_name": c.config_name,
                "config_group": c.config_group,
                "config_value": c.config_value,
                "value_type": c.value_type,
                "description": c.description,
                "editable": c.editable,
                "updated_at": c.updated_at,
            }
            for c in rows
        ]
    )


@router.put("/configs/{config_key}", response_model=ApiResponse[dict], summary="修改系统参数（热更新）")
async def update_config(
    config_key: str, payload: dict, db: DbSession, user: CurrentUser
):
    row = (
        await db.execute(select(SystemConfig).where(SystemConfig.config_key == config_key))
    ).scalar_one_or_none()
    if row is None:
        raise NotFoundError("参数不存在")
    if not row.editable:
        raise BizError("该参数为只读参数，不允许修改")
    value = payload.get("config_value")
    if value is None:
        raise BizError("缺少 config_value")
    before = row.config_value
    row.config_value = str(value)
    await db.commit()
    await audit_service.log_operation(
        db,
        module="系统参数",
        action="修改参数",
        user=user,
        target_type="config",
        target_id=row.id,
        description=f"修改参数 {row.config_name}（{config_key}）",
        before={"config_value": before},
        after={"config_value": row.config_value},
    )
    return ApiResponse.ok({"config_key": config_key, "config_value": row.config_value})


@router.get("/rules", response_model=ApiResponse[list[dict]], summary="规则版本列表")
async def list_rules(db: DbSession, user: CurrentUser):
    rows = (
        await db.execute(select(RuleVersion).order_by(RuleVersion.created_at.desc()))
    ).scalars().all()
    return ApiResponse.ok(
        [
            {
                "id": r.id,
                "version": r.version,
                "is_active": r.is_active,
                "hard_constraints": r.hard_constraints,
                "soft_constraints": r.soft_constraints,
                "change_log": r.change_log,
                "effective_at": r.effective_at,
                "created_at": r.created_at,
            }
            for r in rows
        ]
    )


@router.get("/rules/active", response_model=ApiResponse[dict], summary="当前生效规则")
async def active_rule(db: DbSession, user: CurrentUser):
    from app.ai.nodes import DEFAULT_HARD_CONSTRAINTS, DEFAULT_SOFT_CONSTRAINTS

    record = await audit_service.active_rule_version(db)
    if record is None:
        return ApiResponse.ok(
            {
                "version": "v1-default",
                "hard_constraints": DEFAULT_HARD_CONSTRAINTS,
                "soft_constraints": DEFAULT_SOFT_CONSTRAINTS,
                "is_active": True,
                "source": "内置默认规则",
            }
        )
    return ApiResponse.ok(
        {
            "version": record.version,
            "hard_constraints": record.hard_constraints,
            "soft_constraints": record.soft_constraints,
            "is_active": record.is_active,
            "change_log": record.change_log,
            "effective_at": record.effective_at,
            "source": "规则中心",
        }
    )


# ================================================================ 日志 / 排班


@router.get("/logs/operations", response_model=ApiResponse[PageData[dict]], summary="操作日志")
async def list_operation_logs(
    db: DbSession,
    user: CurrentUser,
    module: str | None = None,
    user_name: str | None = None,
    action: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
):
    rows, total = await audit_service.list_operation_logs(
        db,
        module=module,
        user_name=user_name,
        action=action,
        limit=page_size,
        offset=(page - 1) * page_size,
    )
    items = [
        {
            "id": r.id,
            "user_name": r.user_name,
            "module": r.module,
            "action": r.action,
            "target_type": r.target_type,
            "target_id": r.target_id,
            "description": r.description,
            "method": r.method,
            "path": r.path,
            "ip": r.ip,
            "status_code": r.status_code,
            "duration_ms": r.duration_ms,
            "before": r.before,
            "after": r.after,
            "created_at": r.created_at,
        }
        for r in rows
    ]
    return ApiResponse.ok(PageData.build(items, total, page, page_size))


@router.get("/logs/logins", response_model=ApiResponse[PageData[dict]], summary="登录日志")
async def list_login_logs(
    db: DbSession,
    user: CurrentUser,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
):
    rows, total = await audit_service.list_login_logs(
        db, limit=page_size, offset=(page - 1) * page_size
    )
    items = [
        {
            "id": r.id,
            "user_name": r.user_name,
            "login_type": r.login_type,
            "success": r.success,
            "message": r.message,
            "ip": r.ip,
            "user_agent": r.user_agent,
            "created_at": r.created_at,
        }
        for r in rows
    ]
    return ApiResponse.ok(PageData.build(items, total, page, page_size))


@router.get("/shifts", response_model=ApiResponse[list[dict]], summary="人员排班查询")
async def list_shifts(
    db: DbSession,
    user: CurrentUser,
    user_id: str | None = None,
    start: str | None = None,
    end: str | None = None,
):
    stmt = select(ScheduleShift)
    if user_id:
        stmt = stmt.where(ScheduleShift.user_id == user_id)
    if start:
        stmt = stmt.where(ScheduleShift.shift_date >= datetime.fromisoformat(start))
    if end:
        stmt = stmt.where(ScheduleShift.shift_date <= datetime.fromisoformat(end))
    rows = (await db.execute(stmt.order_by(ScheduleShift.shift_date))).scalars().all()
    users = {u.id: u.real_name for u in (await db.execute(select(User))).scalars().all()}
    return ApiResponse.ok(
        [
            {
                "id": s.id,
                "user_id": s.user_id,
                "user_name": users.get(s.user_id),
                "station_id": s.station_id,
                "shift_date": s.shift_date,
                "shift_name": s.shift_name,
                "start_time": s.start_time,
                "end_time": s.end_time,
                "available": s.available,
            }
            for s in rows
        ]
    )


@router.post("/shifts", response_model=ApiResponse[dict], summary="维护人员排班")
async def upsert_shift(payload: dict, db: DbSession, user: CurrentUser):
    user_id = payload.get("user_id")
    shift_date = payload.get("shift_date")
    if not user_id or not shift_date:
        raise BizError("缺少 user_id 或 shift_date")
    shift = await rbac_service.upsert_shift(
        db,
        user_id=user_id,
        shift_date=datetime.fromisoformat(str(shift_date)[:19]),
        station_id=payload.get("station_id"),
        shift_name=payload.get("shift_name") or "白班",
        start_time=payload.get("start_time") or "08:00",
        end_time=payload.get("end_time") or "18:00",
        available=bool(payload.get("available", True)),
    )
    return ApiResponse.ok(
        {
            "id": shift.id,
            "user_id": shift.user_id,
            "shift_date": shift.shift_date,
            "shift_name": shift.shift_name,
            "available": shift.available,
        }
    )
