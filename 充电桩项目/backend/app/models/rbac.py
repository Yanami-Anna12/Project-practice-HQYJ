"""用户、角色、权限、项目、站点（PDF 6.1 核心表 + 3.3 角色与用户管理）。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import DataScope
from app.models.mixins import BaseModel


class Permission(BaseModel):
    """菜单 / 按钮 / 接口权限（PDF 3.2 树形权限菜单，默认折叠）。"""

    __tablename__ = "permission"

    code: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128))
    # menu / button / api
    perm_type: Mapped[str] = mapped_column(String(16), default="menu")
    parent_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    route_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    component: Mapped[str | None] = mapped_column(String(255), nullable=True)
    icon: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    visible: Mapped[bool] = mapped_column(Boolean, default=True)
    # 平台数据 / 项目数据 / 站点数据 / 个人数据
    data_scope: Mapped[str | None] = mapped_column(String(16), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)


class Role(BaseModel):
    """角色（PDF 3.3：唯一识别码、角色名称、数据权限、倒序排列、复杂模糊查询）。"""

    __tablename__ = "role"

    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(64), index=True)
    data_scope: Mapped[str] = mapped_column(String(16), default=DataScope.PERSONAL.value)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[bool] = mapped_column(Boolean, default=True)
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 内置角色不允许删除
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False)

    permissions: Mapped[list["RolePermission"]] = relationship(
        back_populates="role", cascade="all, delete-orphan", lazy="selectin"
    )


class RolePermission(BaseModel):
    """角色权限表（PDF 6.1）。"""

    __tablename__ = "role_permission"
    __table_args__ = (UniqueConstraint("role_id", "permission_id", name="uq_role_permission"),)

    role_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("role.id", ondelete="CASCADE"), index=True
    )
    permission_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("permission.id", ondelete="CASCADE"), index=True
    )

    role: Mapped[Role] = relationship(back_populates="permissions")
    permission: Mapped["Permission"] = relationship(lazy="selectin")


class Project(BaseModel):
    """项目（数据权限中的“项目数据”主体）。"""

    __tablename__ = "project"

    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128), index=True)
    owner: Mapped[str | None] = mapped_column(String(64), nullable=True)
    region: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[bool] = mapped_column(Boolean, default=True)
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)

    stations: Mapped[list["Station"]] = relationship(back_populates="project")


class Station(BaseModel):
    """站点 / 站台（PDF 3.7 站台台账）。"""

    __tablename__ = "station"

    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128), index=True)
    project_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("project.id"), index=True, nullable=True
    )
    address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    longitude: Mapped[float | None] = mapped_column(nullable=True)
    latitude: Mapped[float | None] = mapped_column(nullable=True)
    # 地形（PDF 3.11 智能工单调度需考虑地形）
    terrain: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # 灭火器字段（PDF 3.10 二期：增加“无”选项，单瓶录入规格/生产日期，动态表单）
    extinguisher_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    extinguisher_spec: Mapped[str | None] = mapped_column(String(64), nullable=True)
    extinguisher_produced_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    # 摄像头字段（PDF 3.10 二期：球机数量、枪机数量、监控密码）
    dome_camera_count: Mapped[int] = mapped_column(Integer, default=0)
    bullet_camera_count: Mapped[int] = mapped_column(Integer, default=0)
    camera_password: Mapped[str | None] = mapped_column(String(128), nullable=True)
    contact_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[bool] = mapped_column(Boolean, default=True)

    project: Mapped[Project | None] = relationship(back_populates="stations")
    piles: Mapped[list["ChargingPile"]] = relationship(back_populates="station")


class ChargingPile(BaseModel):
    """充电桩（PDF 3.7 充电桩台账，含二期充电枪数量）。"""

    __tablename__ = "charging_pile"

    asset_code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128))
    station_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("station.id"), index=True, nullable=True
    )
    model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    rated_power: Mapped[float | None] = mapped_column(nullable=True)  # kW
    # PDF 3.10 二期扩展：追加充电枪数量显示
    gun_count: Mapped[int] = mapped_column(Integer, default=1)
    gun_types: Mapped[str | None] = mapped_column(String(64), nullable=True)
    manufacturer: Mapped[str | None] = mapped_column(String(128), nullable=True)
    install_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    warranty_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="运行")  # 运行/停用/故障/离线
    online: Mapped[bool] = mapped_column(Boolean, default=True)

    station: Mapped[Station | None] = relationship(back_populates="piles")


class User(BaseModel):
    """用户（PDF 3.3：所属项目、所属站点、用户名、手机号、角色、启用状态）。"""

    __tablename__ = "user"
    __table_args__ = (
        Index("ix_user_station_scope", "station_id", "project_id"),
        UniqueConstraint("username", name="uq_user_username"),
    )

    username: Mapped[str] = mapped_column(String(64), index=True)
    real_name: Mapped[str] = mapped_column(String(64), index=True)
    phone: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)
    email: Mapped[str | None] = mapped_column(String(128), nullable=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    avatar: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # 微信登录（PDF 3.3 微信授权手机号登录）
    wechat_openid: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    wechat_unionid: Mapped[str | None] = mapped_column(String(64), nullable=True)
    project_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("project.id"), index=True, nullable=True
    )
    station_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("station.id"), index=True, nullable=True
    )
    role_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("role.id"), index=True, nullable=True
    )
    # 员工端 / 小程序端 / 管理后台
    user_type: Mapped[str] = mapped_column(String(16), default="admin")
    status: Mapped[bool] = mapped_column(Boolean, default=True)
    # 排班与技能（PDF 3.11 调度需结合人员排班、地形与权限）
    skills: Mapped[str | None] = mapped_column(String(255), nullable=True)
    on_duty: Mapped[bool] = mapped_column(Boolean, default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    role: Mapped[Role | None] = relationship(lazy="selectin")
    project: Mapped[Project | None] = relationship(lazy="selectin")
    station: Mapped[Station | None] = relationship(lazy="selectin")


class ScheduleShift(BaseModel):
    """人员排班（PDF 4.4 task_scheduling 需结合人员排班）。"""

    __tablename__ = "schedule_shift"

    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("user.id"), index=True)
    station_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("station.id"), index=True, nullable=True
    )
    shift_date: Mapped[datetime] = mapped_column(DateTime, index=True)
    shift_name: Mapped[str] = mapped_column(String(32), default="白班")
    start_time: Mapped[str] = mapped_column(String(8), default="08:00")
    end_time: Mapped[str] = mapped_column(String(8), default="18:00")
    available: Mapped[bool] = mapped_column(Boolean, default=True)
