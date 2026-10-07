"""角色与用户管理服务 —— PDF 3.3 模块 2：角色与用户管理。

角色：唯一识别码、角色名称、数据权限、倒序排列、复杂模糊查询、
权限分配、角色删除、角色新增。
数据权限：个人数据 / 站点数据 / 项目数据 / 平台数据。
用户：所属项目、所属站点、用户名、手机号、角色、启用状态、
新增、编辑、信息展示、站点数据联动显示。
微信授权手机号登录：授权获取手机号与用户信息，管理员确认身份并授予权限。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import DataScope
from app.core.errors import BizError, ConflictError, NotFoundError
from app.core.security import hash_password
from app.core.utils import like_filter
from app.models import (
    Permission,
    Project,
    Role,
    RolePermission,
    ScheduleShift,
    Station,
    User,
)

# 内置角色（PDF 3.3 / 3.4 分权限显示：个人管理员、站点管理员、项目管理员、平台管理员）
BUILTIN_ROLES: list[dict] = [
    {
        "code": "platform_admin",
        "name": "平台管理员",
        "data_scope": DataScope.PLATFORM.value,
        "sort_order": 100,
        "remark": "拥有平台级数据权限，可管理全部项目、站点、用户与规则",
    },
    {
        "code": "project_admin",
        "name": "项目管理员",
        "data_scope": DataScope.PROJECT.value,
        "sort_order": 80,
        "remark": "拥有所属项目数据权限，可管理项目下站点与工单",
    },
    {
        "code": "station_admin",
        "name": "站点管理员",
        "data_scope": DataScope.STATION.value,
        "sort_order": 60,
        "remark": "拥有所属站点数据权限，可处理本站点工单与故障",
    },
    {
        "code": "personal_admin",
        "name": "个人管理员",
        "data_scope": DataScope.PERSONAL.value,
        "sort_order": 40,
        "remark": "仅可查看与处理本人相关的工单与任务",
    },
    {
        "code": "inspector",
        "name": "运维人员",
        "data_scope": DataScope.PERSONAL.value,
        "sort_order": 20,
        "remark": "员工端接单、巡检录入、故障上报",
    },
]


async def ensure_builtin_roles(db: AsyncSession) -> list[Role]:
    """初始化内置角色。"""
    roles: list[Role] = []
    for item in BUILTIN_ROLES:
        existing = (
            await db.execute(select(Role).where(Role.code == item["code"]))
        ).scalar_one_or_none()
        if existing:
            roles.append(existing)
            continue
        role = Role(
            code=item["code"],
            name=item["name"],
            data_scope=item["data_scope"],
            sort_order=item["sort_order"],
            remark=item["remark"],
            is_builtin=True,
        )
        db.add(role)
        roles.append(role)
    await db.commit()
    return roles


async def list_roles(
    db: AsyncSession,
    *,
    keyword: str | None = None,
    data_scope: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[Role], int]:
    """角色列表：倒序排列 + 复杂模糊查询（PDF 3.3）。"""
    conditions = []
    kw = like_filter([Role.code, Role.name, Role.remark], keyword)
    if kw is not None:
        conditions.append(kw)
    if data_scope:
        conditions.append(Role.data_scope == data_scope)

    base = select(Role)
    count_stmt = select(func.count(Role.id))
    for cond in conditions:
        base = base.where(cond)
        count_stmt = count_stmt.where(cond)

    total = int((await db.execute(count_stmt)).scalar() or 0)
    stmt = base.order_by(Role.sort_order.desc(), Role.created_at.desc()).limit(limit).offset(offset)
    return list((await db.execute(stmt)).scalars().all()), total


async def create_role(
    db: AsyncSession,
    *,
    code: str,
    name: str,
    data_scope: str,
    sort_order: int = 0,
    remark: str | None = None,
    permission_codes: list[str] | None = None,
) -> Role:
    if data_scope not in {e.value for e in DataScope}:
        raise BizError(f"非法数据权限：{data_scope}")
    exists = (await db.execute(select(Role).where(Role.code == code))).scalar_one_or_none()
    if exists:
        raise ConflictError(f"角色识别码已存在：{code}")

    role = Role(
        code=code, name=name, data_scope=data_scope, sort_order=sort_order, remark=remark
    )
    db.add(role)
    await db.flush()
    if permission_codes:
        await _assign_permissions(db, role, permission_codes)
    await db.commit()
    await db.refresh(role)
    return role


async def update_role(
    db: AsyncSession,
    *,
    role_id: str,
    name: str | None = None,
    data_scope: str | None = None,
    sort_order: int | None = None,
    remark: str | None = None,
    status: bool | None = None,
    permission_codes: list[str] | None = None,
) -> Role:
    role = await db.get(Role, role_id)
    if role is None:
        raise NotFoundError("角色不存在")
    if data_scope is not None:
        if data_scope not in {e.value for e in DataScope}:
            raise BizError(f"非法数据权限：{data_scope}")
        role.data_scope = data_scope
    if name is not None:
        role.name = name
    if sort_order is not None:
        role.sort_order = sort_order
    if remark is not None:
        role.remark = remark
    if status is not None:
        role.status = status
    if permission_codes is not None:
        await _assign_permissions(db, role, permission_codes)
    await db.commit()
    await db.refresh(role)
    return role


async def delete_role(db: AsyncSession, role_id: str) -> None:
    role = await db.get(Role, role_id)
    if role is None:
        raise NotFoundError("角色不存在")
    if role.is_builtin:
        raise BizError("内置角色不允许删除")
    in_use = (
        await db.execute(select(func.count(User.id)).where(User.role_id == role_id))
    ).scalar()
    if in_use:
        raise BizError(f"该角色下仍有 {in_use} 个用户，无法删除")
    await db.delete(role)
    await db.commit()


async def _assign_permissions(db: AsyncSession, role: Role, codes: list[str]) -> None:
    await db.execute(
        RolePermission.__table__.delete().where(RolePermission.role_id == role.id)
    )
    if not codes:
        return
    perms = (
        await db.execute(select(Permission).where(Permission.code.in_(codes)))
    ).scalars().all()
    for perm in perms:
        db.add(RolePermission(role_id=role.id, permission_id=perm.id))


async def role_permission_codes(db: AsyncSession, role_id: str) -> list[str]:
    rows = (
        await db.execute(
            select(Permission.code)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .where(RolePermission.role_id == role_id)
        )
    ).all()
    return [r[0] for r in rows]


# ---------------------------------------------------------------- 用户


async def list_users(
    db: AsyncSession,
    *,
    keyword: str | None = None,
    project_id: str | None = None,
    station_id: str | None = None,
    role_id: str | None = None,
    status: bool | None = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[User], int]:
    conditions = []
    kw = like_filter([User.username, User.real_name, User.phone], keyword)
    if kw is not None:
        conditions.append(kw)
    if project_id:
        conditions.append(User.project_id == project_id)
    if station_id:
        conditions.append(User.station_id == station_id)
    if role_id:
        conditions.append(User.role_id == role_id)
    if status is not None:
        conditions.append(User.status == status)

    base = select(User)
    count_stmt = select(func.count(User.id))
    for cond in conditions:
        base = base.where(cond)
        count_stmt = count_stmt.where(cond)

    total = int((await db.execute(count_stmt)).scalar() or 0)
    stmt = base.order_by(User.created_at.desc()).limit(limit).offset(offset)
    return list((await db.execute(stmt)).scalars().all()), total


async def create_user(
    db: AsyncSession,
    *,
    username: str,
    real_name: str,
    password: str,
    phone: str | None = None,
    email: str | None = None,
    role_id: str | None = None,
    project_id: str | None = None,
    station_id: str | None = None,
    user_type: str = "admin",
    skills: str | None = None,
) -> User:
    exists = (
        await db.execute(select(User).where(User.username == username))
    ).scalar_one_or_none()
    if exists:
        raise ConflictError(f"用户名已存在：{username}")
    if len(password) < 6:
        raise BizError("密码长度至少 6 位")

    # 站点数据联动显示：站点必须属于所选项目
    if station_id and project_id:
        station = await db.get(Station, station_id)
        if station and station.project_id and station.project_id != project_id:
            raise BizError("所选站点不属于所选项目，请重新选择")

    user = User(
        username=username,
        real_name=real_name,
        hashed_password=hash_password(password),
        phone=phone,
        email=email,
        role_id=role_id,
        project_id=project_id,
        station_id=station_id,
        user_type=user_type,
        skills=skills,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def update_user(
    db: AsyncSession,
    *,
    user_id: str,
    real_name: str | None = None,
    phone: str | None = None,
    email: str | None = None,
    role_id: str | None = None,
    project_id: str | None = None,
    station_id: str | None = None,
    status: bool | None = None,
    password: str | None = None,
    skills: str | None = None,
    on_duty: bool | None = None,
) -> User:
    user = await db.get(User, user_id)
    if user is None:
        raise NotFoundError("用户不存在")

    if real_name is not None:
        user.real_name = real_name
    if phone is not None:
        user.phone = phone
    if email is not None:
        user.email = email
    if role_id is not None:
        user.role_id = role_id
    if project_id is not None:
        user.project_id = project_id
    if station_id is not None:
        user.station_id = station_id
    if status is not None:
        user.status = status
    if password:
        if len(password) < 6:
            raise BizError("密码长度至少 6 位")
        user.hashed_password = hash_password(password)
    if skills is not None:
        user.skills = skills
    if on_duty is not None:
        user.on_duty = on_duty

    if user.station_id and user.project_id:
        station = await db.get(Station, user.station_id)
        if station and station.project_id and station.project_id != user.project_id:
            raise BizError("所选站点不属于所选项目，请重新选择")

    await db.commit()
    await db.refresh(user)
    return user


async def delete_user(db: AsyncSession, user_id: str) -> None:
    user = await db.get(User, user_id)
    if user is None:
        raise NotFoundError("用户不存在")
    if user.username == "admin":
        raise BizError("内置管理员账号不允许删除")
    await db.delete(user)
    await db.commit()


async def station_options(db: AsyncSession, project_id: str | None = None) -> list[dict]:
    """站点数据联动显示（PDF 3.3）：按项目联动返回站点下拉选项。"""
    stmt = select(Station).where(Station.status.is_(True))
    if project_id:
        stmt = stmt.where(Station.project_id == project_id)
    rows = (await db.execute(stmt.order_by(Station.name))).scalars().all()
    return [
        {
            "id": s.id,
            "code": s.code,
            "name": s.name,
            "project_id": s.project_id,
            "address": s.address,
            "terrain": s.terrain,
        }
        for s in rows
    ]


async def project_options(db: AsyncSession) -> list[dict]:
    rows = (await db.execute(select(Project).order_by(Project.name))).scalars().all()
    return [{"id": p.id, "code": p.code, "name": p.name} for p in rows]


async def wechat_login(
    db: AsyncSession,
    *,
    openid: str,
    phone: str | None = None,
    nickname: str | None = None,
) -> tuple[User | None, bool]:
    """微信授权手机号登录（PDF 3.3）。

    返回 (user, need_admin_confirm)：
    - 已绑定用户直接返回；
    - 未绑定但手机号能匹配到用户则自动绑定；
    - 都匹配不到则返回 (None, True)，需管理员确认身份并授予权限。
    """
    user = (
        await db.execute(select(User).where(User.wechat_openid == openid))
    ).scalar_one_or_none()
    if user:
        if not user.status:
            raise BizError("账号已被停用，请联系管理员")
        return user, False

    if phone:
        matched = (
            await db.execute(select(User).where(User.phone == phone))
        ).scalar_one_or_none()
        if matched:
            matched.wechat_openid = openid
            if nickname and not matched.real_name:
                matched.real_name = nickname
            await db.commit()
            await db.refresh(matched)
            return matched, False

    return None, True


async def upsert_shift(
    db: AsyncSession,
    *,
    user_id: str,
    shift_date: datetime,
    station_id: str | None = None,
    shift_name: str = "白班",
    start_time: str = "08:00",
    end_time: str = "18:00",
    available: bool = True,
) -> ScheduleShift:
    """人员排班维护（PDF 4.4 task_scheduling 依赖排班）。"""
    existing = (
        await db.execute(
            select(ScheduleShift).where(
                ScheduleShift.user_id == user_id,
                ScheduleShift.shift_date == shift_date,
            )
        )
    ).scalar_one_or_none()
    if existing:
        existing.station_id = station_id
        existing.shift_name = shift_name
        existing.start_time = start_time
        existing.end_time = end_time
        existing.available = available
        await db.commit()
        await db.refresh(existing)
        return existing

    shift = ScheduleShift(
        user_id=user_id,
        station_id=station_id,
        shift_date=shift_date,
        shift_name=shift_name,
        start_time=start_time,
        end_time=end_time,
        available=available,
    )
    db.add(shift)
    await db.commit()
    await db.refresh(shift)
    return shift
