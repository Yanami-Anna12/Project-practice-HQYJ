"""司机端（小程序）执行层模型：现场执行记录与站内消息。

对应需求文档 二.7「移动端/司机端」与「司机端（小程序）后端执行层」的实现。

★ 为什么要单独建 trip_stop_record，而不是给 scheduling_plan_detail 加字段？

  `scheduling_plan_detail` 是**计划快照**：它记录「调度那一刻算出来的安排」，
  必须保持**不可变**，否则方案比选、下发幂等、异常重排的「锁定已执行趟次」
  都会失去比对基准。现场执行是**计划之外的新事实**，因此另表存放 ——
  这与本项目里 `scheduling_confirmation`（人工确认）、`dispatch_record`（下发）
  的做法一致：计划、确认、下发、执行各自一张表，谁都不改谁。

  driver_id 刻意冗余存一份：车辆与司机的关系（md_vehicle.driver_id）将来会变，
  执行记录要能回答「当时是谁操作的」，所以按审计思路存快照。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, now_default

# ---------------------------------------------------------------------------
# 字典值的约定（与 seed 写入 sys_dict_item 的值保持一致）
# ---------------------------------------------------------------------------
# trip_action:         arrive 到店 / depart 离店 / complete 完成
# 计划明细的状态取值沿用现有代码：
#   planned 已计划 / dispatched 已下发 / arrived 已到店 / done 已完成
#   （completed 是旧口径，读取时一并视作「已完成」，见 services/mobile.py）


class TripStopRecord(Base):
    """趟次执行记录：一行 = 某趟次某门店的一次现场操作。

    一次完整的门店作业通常产生两条记录（到店 + 离店），
    因此本表**刻意不加唯一约束** —— 同 (plan_detail_id, store_id) 允许多行，
    由 `services/mobile.py` 按动作类型做业务校验（例如不能连打两次到店）。
    """

    __tablename__ = "trip_stop_record"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 关联计划明细（scheduling_plan_detail.id）。本次执行「兑现」的是哪一行计划
    plan_detail_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    driver_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    store_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    # 动作类型：arrive 到店 / depart 离店 / complete 完成
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    # 发生时间：由服务端落库，避免司机端改本地时间伪造打卡
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=now_default()
    )
    # 打卡定位。用 Numeric 而非 Float：经纬度要参与「是否到店范围内」这类判断，
    # 浮点误差没有意义；Numeric(10,6) 约 0.1 米精度，足够。
    latitude: Mapped[float | None] = mapped_column(Numeric(10, 6), nullable=True)
    longitude: Mapped[float | None] = mapped_column(Numeric(10, 6), nullable=True)
    # 备注（司机填写的现场情况）
    remark: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    # 照片附件 id 列表，JSON 数组字符串（与项目里其他 JSON 字段一致用文本存）。
    # 例如 "[12,13]"；解析失败一律当作空列表，坏数据不让接口 500。
    photo_attachment_ids: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=now_default()
    )


class MobileNotification(Base):
    """站内消息（司机端消息中心）。

    ★ 只做站内消息，不做微信订阅消息：微信订阅消息需要 openid，
      而本项目采用「账号密码登录」（复用 POST /api/auth/login），拿不到 openid。
      真要接微信时，只需在 sys_user 上补 openid 字段并在此表基础上加一个推送通道。
    """

    __tablename__ = "mobile_notification"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 接收人：sys_user.id（司机账号），不是 md_driver.id
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(128), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # 业务类型：dispatch 下发通知 / exception 异常 / system 系统
    biz_type: Mapped[str] = mapped_column(String(32), nullable=False, default="system")
    # 关联业务主键（如 dispatch 时为 scheduling_task.id），便于前端跳转
    biz_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=now_default()
    )
