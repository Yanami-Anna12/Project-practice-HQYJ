"""基础主数据模型。

对应需求文档 二.2.1「基础主数据管理」：
  门店、线路、车辆类型、车辆档案、司机、配送区域、班次时段、仓库/站点。

业务约束（需求文档 一.3 / 一.5）在本文件里体现为字段与注释：
  - 车辆类型决定装载量区间与每日趟次（四米二 630-800/2 趟、大包 300-420/2 趟、小包 1-300/4 趟）
  - 门店与线路是多对多，且部分门店处于多线路交界 → store_route_mapping 带 priority
  - 地形分普通/中控/严控；车辆地形能力分全能去/大小包能去/小包能去
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, now_default

# ---------------------------------------------------------------------------
# 字典值的约定（与 seed 写入 sys_dict_item 的值保持一致）
# ---------------------------------------------------------------------------
# terrain_type:        normal / medium / strict        普通 / 中控 / 严控
# terrain_capability:  all / big_small / small_only    全能去 / 大小包能去 / 小包能去
# time_window:         AM / PM                          上午 / 下午
# vehicle_type:        4.2m / big / small               四米二 / 大包 / 小包


class Store(Base):
    """门店。"""

    __tablename__ = "md_store"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    # 地形限制：normal / medium / strict
    terrain_type: Mapped[str] = mapped_column(String(16), nullable=False, default="normal")
    # 配送时段属性：AM 上午送 / PM 下午送（需求：上午门店上午送，下午门店下午送）
    delivery_window: Mapped[str] = mapped_column(String(8), nullable=False, default="AM")
    # 交界门店的优先级的补充排序权重，数字越小越优先
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    # 配送区域、地址等
    area: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    address: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    contact: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    phone: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    # 是否处于多条线路的交界处（需求：8. 部分门店处于多条线路的交界处）
    is_intersection: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=now_default()
    )


class Route(Base):
    """线路。

    ★ 注意：这里的「线路」是配送线路（业务概念），不是编程意义上的路由。
    """

    __tablename__ = "md_route"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    # 线路覆盖的地形集合，逗号分隔，例如 "normal,medium"；空表示不限制
    terrain_scope: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    area: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    # 该线路是否允许通行（禁限行规则，需求 2.2.3）
    is_restricted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    remark: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=now_default()
    )


class StoreRouteMapping(Base):
    """门店-线路映射（多对多）。

    需求：一个门店可能属于多个线路，一个线路上也有多个门店。
    priority 用于「多线路门店分配优先级」：数字越小越优先派给该线路。
    is_primary 标记主线路，用于交界门店归属策略。
    """

    __tablename__ = "md_store_route"
    __table_args__ = (UniqueConstraint("store_id", "route_id", name="uq_store_route"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    store_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    route_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=now_default()
    )


class VehicleType(Base):
    """车辆类型。装载量区间与每日趟次规则挂在类型上。

    默认值取自需求文档 一.3：
      四米二 28 台 630-800 日 2 趟（上午 1 + 下午 1）
      大包   3 台  300-420 日 2 趟（上午 1 + 下午 1）
      小包   9 台  1-300   日 4 趟（上午 2 + 下午 2）
    """

    __tablename__ = "md_vehicle_type"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(16), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(32), nullable=False)
    min_load: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_load: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    trips_per_day: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    am_trips: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    pm_trips: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 计划保有量，用于「不保障满勤」的对比基线（28 / 3 / 9）
    planned_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    remark: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=now_default()
    )


class Vehicle(Base):
    """车辆档案。"""

    __tablename__ = "md_vehicle"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    plate_no: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    vehicle_type_code: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    # 车辆地形能力：all / big_small / small_only
    terrain_capability: Mapped[str] = mapped_column(String(16), nullable=False, default="all")
    # 可跑线路，逗号分隔的 route code；空表示不限制
    route_scope: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    # 状态：idle 空闲 / running 出车中 / maintenance 维保中 / offline 停用
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="idle")
    driver_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    remark: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=now_default()
    )


class VehicleTerrainCapability(Base):
    """地形-车辆通行矩阵（需求 2.2.3）。

    (terrain_type, capability) → allowed 表示该能力能否通行该地形。
    单独建表而不是硬编码，是为了让规则可配置、可版本化。
    """

    __tablename__ = "md_terrain_matrix"
    __table_args__ = (
        UniqueConstraint("terrain_type", "capability", name="uq_terrain_capability"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    terrain_type: Mapped[str] = mapped_column(String(16), nullable=False)
    capability: Mapped[str] = mapped_column(String(16), nullable=False)
    allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    remark: Mapped[str] = mapped_column(String(255), nullable=False, default="")


class Driver(Base):
    """司机。"""

    __tablename__ = "md_driver"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    phone: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    # 班次：AM 上午班 / PM 下午班 / FULL 全天
    shift: Mapped[str] = mapped_column(String(8), nullable=False, default="FULL")
    # 状态：available 可出勤 / leave 请假 / offline 停用
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="available")
    remark: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=now_default()
    )


class TerrainRule(Base):
    """地形限制规则（普通/中控/严控）。

    这是地形的「主数据」，与 md_terrain_matrix 的通行矩阵区分开：
    本表描述地形本身，矩阵描述「哪种车能进哪种地形」。
    """

    __tablename__ = "md_terrain_rule"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(16), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(32), nullable=False)
    # 管控等级，数字越大越严，用于排序与冲突校验
    level: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=now_default()
    )
