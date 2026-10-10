"""司机端（小程序）服务层。

对应需求文档 二.7「移动端/司机端」。本模块承载司机端**执行层**的全部业务逻辑，
路由层（app/routers/mobile.py）只做参数接收与调用，保持项目一贯的分层。

★ 三条贯穿全模块的设计说明：

1. **司机是怎么被认出来的**
   登录复用 `POST /api/auth/login`（账号密码），不做微信登录。
   当前登录人 → `md_driver.user_id` 命中司机档案 → 用 `md_vehicle.driver_id`
   反查名下车辆 → 用车辆去找已下发的趟次。
   （车辆与司机是一对多绑定：一台车绑一个司机，所以不需要给方案明细加 driver_id。）

2. **计划不可变，执行另表**
   `scheduling_plan_detail` 是计划快照，本模块**只改它的 status**，从不改
   趟次/门店/货量等计划内容；现场事实（到店时间、打卡坐标、照片、备注）
   一律写入 `trip_stop_record`。

3. **状态取值沿用现有代码**
   计划明细 status：`planned` 已计划 → `dispatched` 已下发 → `arrived` 已到店
   → `done` 已完成（`completed` 是任务级/旧口径的同义值，读取时一并视作已完成）。
   异常复用现有 `exception_event` 表，`source` 记为 `driver:<工号>`，`status` 用 `pending`。

4. **站内消息落库即推送**
   消息写入只有两个入口：`create_notification()`（单条）与 `notify_dispatch()`
   （下发时批量），两者都在 commit 之后调用 `push_notification()` 走 WebSocket
   实时推给司机（见 app/services/realtime.py）。推送是「锦上添花」，
   司机离线/连接断开只记日志，绝不影响下发与入库。
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Any

from fastapi import UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.errors import AppError, ConflictError, ForbiddenError, NotFoundError
from app.models import (
    DispatchRecord,
    Driver,
    ExceptionEvent,
    MobileNotification,
    SchedulingPlan,
    SchedulingPlanDetail,
    SchedulingTask,
    Store,
    SysAttachment,
    SysPermission,
    SysRole,
    SysUser,
    TripStopRecord,
    Vehicle,
    VehicleType,
)
from app.schemas import (
    MobileCheckinRequest,
    MobileCheckinResult,
    MobileCompletionStatOut,
    MobileExceptionBriefOut,
    MobileExceptionCreate,
    MobileExceptionOut,
    MobileExceptionStatOut,
    MobileFileOut,
    MobileManagerOverviewOut,
    MobileNotificationOut,
    MobileProfileOut,
    MobileTaskStatOut,
    MobileTripAcceptResult,
    MobileTripBriefOut,
    MobileTripDetailOut,
    MobileTripOut,
    MobileTripStatOut,
    MobileTripStopOut,
    MobileVehicleOut,
    MobileVehicleStatOut,
)
from app.services import realtime

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
# 趟次标识。★ 与 dispatch_record.trip_id 的构造保持一致（task:plan:vehicle:trip），
# 这样「下发的那一刻」和「司机端看到的趟次」是同一个键，便于对账。
TRIP_KEY_PATTERN = re.compile(r"^(\d+):(\d+):(\d+):(\d+)$")

ACTION_ARRIVE = "arrive"
ACTION_DEPART = "depart"
ACTION_COMPLETE = "complete"
VALID_ACTIONS = {ACTION_ARRIVE, ACTION_DEPART, ACTION_COMPLETE}

# 动作的中文名（拼消息用）
ACTION_LABELS = {
    ACTION_ARRIVE: "到店",
    ACTION_DEPART: "离店",
    ACTION_COMPLETE: "完成",
}

# 计划明细状态
DETAIL_PLANNED = "planned"
DETAIL_DISPATCHED = "dispatched"
DETAIL_ARRIVED = "arrived"
DETAIL_DONE = "done"
# 旧口径的「完成」值：读取时一并当作已完成，避免历史数据被误判为未开始
DETAIL_DONE_ALIASES = {"done", "completed"}

# 趟次整体状态（司机端展示用，由站点状态推导，不落库）
TRIP_STATUS_PLANNED = "planned"
TRIP_STATUS_RUNNING = "running"
TRIP_STATUS_DONE = "done"

# 消息业务类型
BIZ_DISPATCH = "dispatch"
BIZ_EXCEPTION = "exception"
BIZ_SYSTEM = "system"
# 司机确认接单（司机 → 调度方向的消息，与 BIZ_DISPATCH 的「调度 → 司机」相反）
BIZ_ACCEPT = "accept"

# 「调度相关角色」的判定权限点：持有它的启用账号会收到「司机已确认接单」的消息。
# 口径说明见 _dispatcher_user_ids()：admin（*）/ dispatcher / viewer / multi 都命中，
# 司机与基础数据管理员不命中。
DISPATCH_VIEW_PERMISSION = "scheduling:read"

# 上传限制
ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10MB
# 一次读取的分块大小：不把整个文件读进内存再判断大小
UPLOAD_CHUNK_BYTES = 1024 * 1024


# ---------------------------------------------------------------------------
# 通用小工具
# ---------------------------------------------------------------------------
def _f(value: Any) -> float | None:
    """Numeric → float。None 原样返回（坐标本来就可以没有）。"""
    return None if value is None else float(value)


def parse_photo_ids(raw: str | None) -> list[int]:
    """把 JSON 数组字符串解析成附件 id 列表。

    坏数据（空串、半截 JSON、非数字）一律当作空列表 ——
    执行记录是现场数据，不能因为一条脏记录把整个趟次详情接口打成 500。
    """
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except (ValueError, TypeError):
        return []
    if not isinstance(value, list):
        return []
    ids: list[int] = []
    for item in value:
        try:
            ids.append(int(item))
        except (TypeError, ValueError):
            continue
    return ids


def dump_photo_ids(ids: list[int] | None) -> str:
    """附件 id 列表 → JSON 字符串。"""
    return json.dumps([int(i) for i in (ids or [])], ensure_ascii=False)


def build_trip_key(task_id: int, plan_id: int, vehicle_id: int, trip_no: int) -> str:
    """构造趟次标识（与 dispatch_record.trip_id 同规则）。"""
    return f"{task_id}:{plan_id}:{vehicle_id}:{trip_no}"


def parse_trip_key(trip_key: str) -> tuple[int, int, int, int]:
    """解析趟次标识，返回 (task_id, plan_id, vehicle_id, trip_no)。

    格式错误直接 400 —— 这个键是路径参数，格式不对没有「降级处理」的意义。
    """
    matched = TRIP_KEY_PATTERN.match((trip_key or "").strip())
    if matched is None:
        raise AppError("趟次标识格式错误，应为 任务:方案:车辆:趟次（例如 3:5:12:1）")
    return tuple(int(g) for g in matched.groups())  # type: ignore[return-value]


def _is_detail_done(status: str) -> bool:
    return status in DETAIL_DONE_ALIASES


# ---------------------------------------------------------------------------
# 司机身份
# ---------------------------------------------------------------------------
def get_driver(db: Session, user: SysUser) -> Driver | None:
    """当前登录人对应的司机档案（未绑定返回 None）。"""
    return (
        db.query(Driver)
        .filter(Driver.user_id == user.id, Driver.is_active.is_(True))
        .one_or_none()
    )


def require_driver(db: Session, user: SysUser) -> Driver:
    """要求当前登录人必须是司机（执行类接口都用它）。"""
    driver = get_driver(db, user)
    if driver is None:
        raise ForbiddenError(
            f"账号「{user.username}」未绑定司机档案，无法执行司机端操作"
            "（需在 md_driver.user_id 上关联登录账号）"
        )
    return driver


def get_driver_vehicles(db: Session, driver: Driver) -> list[Vehicle]:
    """司机名下车辆（一台车绑一个司机，所以这里是「司机 → 车」的反查）。"""
    return (
        db.query(Vehicle)
        .filter(Vehicle.driver_id == driver.id, Vehicle.is_active.is_(True))
        .order_by(Vehicle.id)
        .all()
    )


def _vehicle_type_names(db: Session) -> dict[str, str]:
    return {t.code: t.name for t in db.query(VehicleType).all()}


# ---------------------------------------------------------------------------
# 我的趟次
# ---------------------------------------------------------------------------
def _dispatched_details_stmt(driver_vehicle_ids: list[int]):
    """司机名下车辆「已下发（含已完成）」的计划明细查询。

    ★ 状态范围为什么是 dispatched / arrived / done 三个，而不是只认 dispatched：

      `dispatch_task` 下发时把明细置为 dispatched，之后司机打卡会把状态往前推
      （dispatched → arrived → done）。**如果这里只筛 'dispatched'，司机一打完
      「离店/完成」卡，这一趟就从列表里消失了** —— 现场反馈正是这个：
      「完成本单之后能不能保留记录，不要删掉了」。

      所以：已下发过的趟次一律保留在列表里，`done` 的排到最后（见 my_trips 的排序），
      司机既能看见今天还要跑几趟，也能回看刚跑完的那趟送去哪几家。

    ★ 仍然要求任务处于 dispatched / completed：
      任务被人工驳回（退回 pending_confirm）后，明细状态可能残留，不该再展示。
    """
    return (
        select(SchedulingPlanDetail)
        .join(SchedulingPlan, SchedulingPlan.id == SchedulingPlanDetail.plan_id)
        .join(SchedulingTask, SchedulingTask.id == SchedulingPlan.task_id)
        .where(
            SchedulingPlanDetail.vehicle_id.in_(driver_vehicle_ids),
            SchedulingPlanDetail.status.in_([DETAIL_DISPATCHED, DETAIL_ARRIVED, DETAIL_DONE]),
            SchedulingTask.status.in_(["dispatched", "completed"]),
        )
    )


def _trip_sort_key(trip: MobileTripOut) -> tuple:
    """趟次列表的排序：**红的排最上面，绿的沉到最后**。

    顺序：日期新 → 状态（未确认 → 已接单未完成 → 已完成）→ 上午先于下午 → 趟次号小 → 车牌。

    ★ 三色状态与前端卡片颜色、标签是同一套口径（用户明确要求）：
      · 未确认接单（红）—— 需要司机动手，**排最上面**
      · 已确认但没跑完（黄）—— 已经在手上，排中间
      · 已完成（绿）—— 可以回看，**沉到最下面**

    ★ 为什么「日期」仍排在第一个：日期是司机找活的第一维度，先按日期分组更符合
      直觉。若把状态提到日期之前，前天那张没确认的红卡会一直压住今天整天的活。
      （以后若要「跨日期把所有红卡置顶」，把下面 `state_rank` 与
      `-toordinal()` 两项换位即可，其余不动。）

    ★ 日期用 `-toordinal()` 取负，才能和整数 rank 放同一个升序 key：
      取负后「日期新」等价于数值小，排在前面。
    """
    window_rank = {"AM": 0, "PM": 1, "FULL": 0}.get(trip.time_window, 9)
    # 三色状态的排序权重：0 红 → 1 黄 → 2 绿
    state_rank = (
        2
        if trip.trip_status == TRIP_STATUS_DONE
        else 1
        if trip.accepted
        else 0
    )
    return (
        -trip.schedule_date.toordinal(),
        state_rank,
        window_rank,
        trip.trip_no,
        trip.plate_no,
    )


def my_trips(
    db: Session, user: SysUser, schedule_date: date | None = None
) -> list[MobileTripOut]:
    """我的趟次列表。

    聚合口径：一行 = 某（任务, 方案, 车辆, 趟次），按 plan_detail 的
    trip_no / time_window 归组，返回该趟的门店数与总货量。

    schedule_date 留空时不报错也不返回空数组，而是返回**全部已下发趟次**
    （按日期倒序）—— 演示数据是某一天生成的，第二天再打开小程序
    仍然能看到自己的趟次，比直接空列表可用得多。
    """
    driver = require_driver(db, user)
    vehicles = get_driver_vehicles(db, driver)
    if not vehicles:
        return []

    vehicle_by_id = {v.id: v for v in vehicles}
    detail_stmt = _dispatched_details_stmt(list(vehicle_by_id))

    tasks = {t.id: t for t in db.query(SchedulingTask).all()}
    if schedule_date is not None:
        allowed_task_ids = [tid for tid, t in tasks.items() if t.schedule_date == schedule_date]
        if not allowed_task_ids:
            return []
        detail_stmt = detail_stmt.where(SchedulingPlanDetail.plan_id.in_(
            select(SchedulingPlan.id).where(SchedulingPlan.task_id.in_(allowed_task_ids))
        ))

    details = db.execute(detail_stmt).scalars().all()
    if not details:
        return []

    plans = {
        p.id: p
        for p in db.query(SchedulingPlan)
        .filter(SchedulingPlan.id.in_({d.plan_id for d in details}))
        .all()
    }

    # 执行进度一律以 scheduling_plan_detail.status 为准：它在打卡时被服务端推进
    # （dispatched → arrived → done），由 checkin() 与 trip_stop_record 同事务写入，
    # 因此这里不需要再去扫一遍执行记录。
    grouped: dict[tuple[int, int, int], list[SchedulingPlanDetail]] = {}
    for detail in details:
        grouped.setdefault((detail.plan_id, detail.vehicle_id, detail.trip_no), []).append(detail)

    vehicle_type_names = _vehicle_type_names(db)
    # 确认接单状态：一次查完本批任务的下发记录，避免在循环里逐趟查库。
    # ★ 计划明细上没有 task_id，任务号要从它所属的方案取（plans 已在上面查好）。
    accepted_map = _acceptance_map(
        db,
        [p.task_id for p in plans.values()],
    )

    # ★ 「这辆车当天一共跑几趟」：按 (日期, 车辆) 数出实际存在的 trip_no 个数。
    #   为什么不能直接用车型规则里的 trips_per_day：那是**计划的**上限，
    #   实际排几趟由求解器按货量决定，可能少于上限（例如 4.2m 车当天只排了 1 趟）。
    #   司机要看到的是「今天这辆车实际一共几趟」，所以按明细实际去重数出来。
    trip_nos_by_vehicle: dict[tuple[date, int], set[int]] = {}
    for (plan_id, vehicle_id, trip_no) in grouped:
        plan = plans.get(plan_id)
        task = tasks.get(plan.task_id) if plan is not None else None
        if task is None:
            continue
        trip_nos_by_vehicle.setdefault((task.schedule_date, vehicle_id), set()).add(trip_no)

    out: list[MobileTripOut] = []
    for (plan_id, vehicle_id, trip_no), rows in grouped.items():
        plan = plans.get(plan_id)
        if plan is None:
            continue
        task = tasks.get(plan.task_id)
        if task is None:
            continue

        vehicle = vehicle_by_id.get(vehicle_id)
        done = sum(1 for r in rows if _is_detail_done(r.status))
        arrived = sum(1 for r in rows if r.status == DETAIL_ARRIVED)
        trip_key = build_trip_key(task.id, plan_id, vehicle_id, trip_no)
        accepted_at = accepted_map.get(trip_key)
        out.append(
            MobileTripOut(
                trip_key=trip_key,
                task_id=task.id,
                task_code=task.code,
                plan_id=plan_id,
                plan_code=plan.plan_code,
                schedule_date=task.schedule_date,
                time_window=rows[0].time_window,
                trip_no=trip_no,
                vehicle_id=vehicle_id,
                plate_no=vehicle.plate_no if vehicle else "",
                vehicle_type=rows[0].vehicle_type,
                vehicle_type_name=vehicle_type_names.get(rows[0].vehicle_type, ""),
                store_count=len(rows),
                total_load=round(sum(float(r.load_amount) for r in rows), 2),
                done_stores=done,
                arrived_stores=arrived,
                trip_status=_trip_status(len(rows), done, arrived),
                vehicle_trip_count=len(
                    trip_nos_by_vehicle.get((task.schedule_date, vehicle_id), set())
                ),
                accepted=accepted_at is not None,
                accepted_at=accepted_at,
            )
        )

    # ★ 排序见 _trip_sort_key：还要跑的排最前，**跑完的沉到最底下**
    #   （用户要求「完成的记录别删掉，放到最下面」）。
    out.sort(key=_trip_sort_key)
    return out


def _trip_status(store_count: int, done: int, arrived: int) -> str:
    """趟次整体状态：全部完成 → done；有任一动作 → running；否则 planned。"""
    if store_count and done >= store_count:
        return TRIP_STATUS_DONE
    if done or arrived:
        return TRIP_STATUS_RUNNING
    return TRIP_STATUS_PLANNED


# ---------------------------------------------------------------------------
# 司机确认接单（dispatch_record.accepted_at / accepted_by）
# ---------------------------------------------------------------------------
def _acceptance_map(db: Session, task_ids: list[int]) -> dict[str, datetime]:
    """任务范围内的「趟次 → 首次确认时间」。

    ★ 为什么用 dispatch_record 而不是新表：它的粒度就是
      「任务 · 方案 · 车辆 · 趟次」，与 trip_key 一一对应（见模型注释）。
    ★ 为什么返回 dict 而不是逐个查询：趟次列表一次可能二三十行，
      逐行查库就是 N+1；这里一次查完所有下发记录再按 trip_id 建索引。
    ★ 键就是 `dispatch_record.trip_id` 原文（形如 `1:2:1:1`），与
      `build_trip_key()` 的输出同规则，所以可以直接查表命中，
      不要在这里再拼 task_id —— 那样会拼成 `1:1:2:1:1` 而永远查不到。
    """
    if not task_ids:
        return {}
    rows = (
        db.query(DispatchRecord.trip_id, DispatchRecord.accepted_at)
        .filter(
            DispatchRecord.task_id.in_(sorted(set(task_ids))),
            DispatchRecord.accepted_at.isnot(None),
        )
        .all()
    )
    return {trip_id: accepted_at for trip_id, accepted_at in rows}


def _accepted_at_for(db: Session, trip_key: str) -> datetime | None:
    """单个趟次的首次确认时间（没有记录或未确认都返回 None）。"""
    return _acceptance_map(db, [parse_trip_key(trip_key)[0]]).get(trip_key)


def _dispatched_vehicle_ids(db: Session) -> set[int]:
    """已下发过任务的车队（dispatch_record 是「真的派下去了」的凭据）。"""
    return {row[0] for row in db.query(DispatchRecord.vehicle_id).distinct().all()}


def _dispatcher_user_ids(db: Session) -> list[int]:
    """「该车所属调度相关角色」的账号列表 —— 司机确认接单时的收件人。

    ★ 判定口径：**持有调度查看权限（scheduling:read）的启用账号**，
      而不是写死角色码。这样 admin（`*` 拥有全部权限）、dispatcher、
      multi（调度员+只读观察者）都能收到，而司机、基础数据管理员、
      只读财务观察者（viewer 也有 scheduling:read，属于「调度相关」）不会漏，
      将来新增调度角色也不需要改这里。
    ★ 不给自己发：确认人自己的账号从收件人里剔除（司机一般没有该权限，
      但多角色账号确实可能既有 mobile:use 又有 scheduling:read）。
    """
    rows = (
        db.query(SysUser.id)
        .distinct()
        .join(SysUser.roles)
        .join(SysRole.permissions)
        .filter(
            SysUser.is_active.is_(True),
            SysRole.is_active.is_(True),
            SysPermission.is_active.is_(True),
            SysPermission.code == DISPATCH_VIEW_PERMISSION,
        )
        .all()
    )
    return sorted({int(row[0]) for row in rows})


def accept_trip(db: Session, user: SysUser, trip_key: str) -> MobileTripAcceptResult:
    """司机确认收到某趟任务。

    三条硬约束（对应需求「司机确认接单」）：

    1. **只能确认自己名下车辆的趟次**：车辆 → md_vehicle.driver_id → md_driver.user_id
       必须命中当前登录人，否则 403（与 trip_detail 的越权处理同一套口径）。
    2. **幂等**：重复确认返回 200，`already_accepted=True`，
       并且**不覆盖首次确认时间** —— 确认时间是调度考核「司机多久响应」的依据，
       被后来的重复点击刷新掉就失去意义了。
    3. **站内消息**：写入成功后给「调度相关角色」的账号各发一条消息，
       复用 `create_notification()`（落库 + WebSocket 实时推送），
       标题形如「钱师傅已确认接单：T20261011-001（沪C1002）」。
       （同一司机在同一任务下多趟确认只发一条，见 notify_trip_accepted 的说明）

    ★ 只写 dispatch_record 的两个确认列，**不动**计划快照
      （scheduling_plan_detail）与任务状态：确认是执行层事实，
      不影响「方案比选 / 下发幂等 / 异常重排」依赖的计划基准。
    """
    driver = require_driver(db, user)
    task_id, plan_id, vehicle_id, trip_no = parse_trip_key(trip_key)

    # 越权检查：这一趟必须是当前司机名下车辆的任务
    if vehicle_id not in {v.id for v in get_driver_vehicles(db, driver)}:
        raise ForbiddenError("该趟次不属于你名下的车辆")

    task = db.get(SchedulingTask, task_id)
    if task is None:
        raise NotFoundError("调度任务不存在")
    plan = db.get(SchedulingPlan, plan_id)
    if plan is None or plan.task_id != task_id:
        raise NotFoundError("调度方案不存在或不属于该任务")

    # 下发记录是「这趟真的派给这辆车」的凭据，也是确认事实的载体
    record = (
        db.query(DispatchRecord)
        .filter(
            DispatchRecord.task_id == task_id,
            DispatchRecord.plan_id == plan_id,
            DispatchRecord.vehicle_id == vehicle_id,
            DispatchRecord.trip_id == trip_key,
        )
        .one_or_none()
    )
    if record is None:
        raise NotFoundError("该趟次尚未下发，无法确认接单")

    vehicle = db.get(Vehicle, vehicle_id)
    plate_no = vehicle.plate_no if vehicle else ""

    # ---- 幂等分支：已确认过就原样返回首次确认时间，不重复写库、不重复发消息 ----
    if record.accepted_at is not None:
        logger.info("重复确认接单（幂等返回）：%s / %s", user.username, trip_key)
        return MobileTripAcceptResult(
            trip_key=trip_key,
            task_id=task_id,
            task_code=task.code,
            vehicle_id=vehicle_id,
            plate_no=plate_no,
            accepted=True,
            accepted_at=record.accepted_at,
            already_accepted=True,
            notified=0,
            message=f"该趟次已于 {record.accepted_at:%Y-%m-%d %H:%M} 确认过接单",
        )

    record.accepted_at = datetime.now()
    record.accepted_by = user.id
    db.commit()
    db.refresh(record)

    # ---- 站内消息：通知调度相关角色（落库即推送，推不到不影响确认结果）----
    notified = notify_trip_accepted(
        db, task=task, driver=driver, plate_no=plate_no, trip_key=trip_key, trip_no=trip_no
    )

    return MobileTripAcceptResult(
        trip_key=trip_key,
        task_id=task_id,
        task_code=task.code,
        vehicle_id=vehicle_id,
        plate_no=plate_no,
        accepted=True,
        accepted_at=record.accepted_at,
        already_accepted=False,
        notified=notified,
        message=f"已确认接单（{plate_no} 第 {trip_no} 趟），调度中心已收到通知",
    )


def notify_trip_accepted(
    db: Session,
    *,
    task: SchedulingTask,
    driver: Driver,
    plate_no: str,
    trip_key: str,
    trip_no: int,
) -> int:
    """司机确认接单 → 给调度相关角色各写一条站内消息，返回写入条数。

    ★ 与 `notify_dispatch` 的分工：那个是「调度 → 司机」（下发给司机发消息），
      这个是「司机 → 调度」（确认给调度发消息），方向相反但都走
      `create_notification()`，因此入库与 WebSocket 推送的行为完全一致。

    ★ 异常一律吞掉：确认接单本身已经成功落库了，
      通知发不出去（收件人查询失败等）不该让司机看到「确认失败」。

    ★ 同一司机在同一任务下的多趟确认只发**一条**消息（按标题去重）：
      一个司机名下常有多趟（演示库 driver2 有 22 趟），逐趟发会把调度员的
      消息中心刷满同一句话；确认事实本身在 dispatch_record.accepted_at 上，
      消息只是提醒。首次确认的 WebSocket 推送不受影响（仍是即时一条）。
    """
    try:
        recipients = [uid for uid in _dispatcher_user_ids(db) if uid != driver.user_id]
        if not recipients:
            logger.info("确认接单通知跳过：没有调度相关账号（%s）", trip_key)
            return 0
        title = f"{driver.name}已确认接单：{task.code}（{plate_no}）"
        content = (
            f"{driver.name}（工号 {driver.code}，电话 {driver.phone or '未登记'}）"
            f"已确认接单：{task.schedule_date} {task.time_window} 时段 "
            f"车牌 {plate_no} 第 {trip_no} 趟（趟次 {trip_key}）。"
        )
        created = 0
        for user_id in recipients:
            # 幂等：同一任务 + 同一司机 + 同一车牌 已经发过就跳过
            exists = (
                db.query(MobileNotification)
                .filter(
                    MobileNotification.user_id == user_id,
                    MobileNotification.biz_type == BIZ_ACCEPT,
                    MobileNotification.biz_id == task.id,
                    MobileNotification.title == title,
                )
                .one_or_none()
            )
            if exists is not None:
                continue
            create_notification(
                db,
                user_id=user_id,
                title=title,
                content=content,
                biz_type=BIZ_ACCEPT,
                biz_id=task.id,
            )
            created += 1
        logger.info("确认接单通知已发送：%s → %d 个账号", trip_key, created)
        return created
    except Exception as exc:  # noqa: BLE001 —— 通知失败绝不影响确认接单
        logger.warning("确认接单通知发送失败（不影响确认）：%s", exc)
        return 0


def trip_detail(db: Session, user: SysUser, trip_key: str) -> MobileTripDetailOut:
    """趟次详情：门店序列 + 每店货量 + 地址/电话/坐标 + 已有执行记录与状态。"""
    driver = require_driver(db, user)
    task_id, plan_id, vehicle_id, trip_no = parse_trip_key(trip_key)

    # 越权检查：这一趟必须是当前司机名下车辆的任务，否则拒绝
    if vehicle_id not in {v.id for v in get_driver_vehicles(db, driver)}:
        raise ForbiddenError("该趟次不属于你名下的车辆")

    task = db.get(SchedulingTask, task_id)
    if task is None:
        raise NotFoundError("调度任务不存在")
    plan = db.get(SchedulingPlan, plan_id)
    if plan is None or plan.task_id != task_id:
        raise NotFoundError("调度方案不存在或不属于该任务")
    vehicle = db.get(Vehicle, vehicle_id)

    rows = db.execute(
        select(SchedulingPlanDetail, Store)
        .join(Store, Store.id == SchedulingPlanDetail.store_id)
        .where(
            SchedulingPlanDetail.plan_id == plan_id,
            SchedulingPlanDetail.vehicle_id == vehicle_id,
            SchedulingPlanDetail.trip_no == trip_no,
        )
        .order_by(SchedulingPlanDetail.sequence, SchedulingPlanDetail.id)
    ).all()
    if not rows:
        raise NotFoundError("该趟次没有门店明细")

    # 执行记录：一次取回本趟所有明细的记录，按时间排序，取每行的最后一条
    detail_ids = [d.id for d, _ in rows]
    records = (
        db.query(TripStopRecord)
        .filter(TripStopRecord.plan_detail_id.in_(detail_ids))
        .order_by(TripStopRecord.id)
        .all()
    )
    last_record: dict[int, TripStopRecord] = {}
    for record in records:
        last_record[record.plan_detail_id] = record

    stops: list[MobileTripStopOut] = []
    for detail, store in rows:
        # 注意：这里只用到了元组的两个分量，下面统计 done/arrived 时同样要按元组解包
        record = last_record.get(detail.id)
        stops.append(
            MobileTripStopOut(
                plan_detail_id=detail.id,
                store_id=store.id,
                store_code=store.code,
                store_name=store.name,
                address=store.address,
                contact=store.contact,
                phone=store.phone,
                latitude=_f(store.latitude),
                longitude=_f(store.longitude),
                load_amount=float(detail.load_amount),
                sequence=detail.sequence,
                status=detail.status,
                last_action=record.action if record else "",
                last_action_at=record.occurred_at if record else None,
                photo_attachment_ids=parse_photo_ids(
                    record.photo_attachment_ids if record else None
                ),
            )
        )

    # ★ rows 是 (SchedulingPlanDetail, Store) 的元组序列，统计时必须解包
    done = sum(1 for row in rows if _is_detail_done(row[0].status))
    arrived = sum(1 for row in rows if row[0].status == DETAIL_ARRIVED)

    # 下发状态：dispatch_record 是下发的凭据（明细的 dispatched 只是结果标记）
    dispatch = (
        db.query(DispatchRecord)
        .filter(
            DispatchRecord.task_id == task_id,
            DispatchRecord.plan_id == plan_id,
            DispatchRecord.vehicle_id == vehicle_id,
            DispatchRecord.trip_id == build_trip_key(task_id, plan_id, vehicle_id, trip_no),
        )
        .one_or_none()
    )

    # 趟次级的公共字段取第一行的值：同一 (plan, vehicle, trip_no) 下
    # 时段与车型必然一致（求解器就是这么装的），取首行即可。
    head = rows[0][0]
    return MobileTripDetailOut(
        trip_key=build_trip_key(task_id, plan_id, vehicle_id, trip_no),
        task_id=task_id,
        task_code=task.code,
        plan_id=plan_id,
        plan_code=plan.plan_code,
        schedule_date=task.schedule_date,
        time_window=head.time_window or task.time_window,
        trip_no=trip_no,
        vehicle_id=vehicle_id,
        plate_no=vehicle.plate_no if vehicle else "",
        vehicle_type=head.vehicle_type,
        vehicle_type_name=_vehicle_type_names(db).get(head.vehicle_type, ""),
        store_count=len(rows),
        total_load=round(sum(float(d.load_amount) for d, _ in rows), 2),
        done_stores=done,
        arrived_stores=arrived,
        trip_status=_trip_status(len(rows), done, arrived),
        accepted=dispatch.accepted_at is not None if dispatch else False,
        accepted_at=dispatch.accepted_at if dispatch else None,
        driver_name=driver.name,
        driver_phone=driver.phone,
        dispatch_status=dispatch.status if dispatch else "",
        stops=stops,
    )


# ---------------------------------------------------------------------------
# 现场打卡
# ---------------------------------------------------------------------------
def checkin(
    db: Session,
    user: SysUser,
    payload: MobileCheckinRequest,
) -> MobileCheckinResult:
    """写一条 trip_stop_record，并推进计划明细状态。

    状态推进规则（与现有代码的取值保持一致）：

        到店 arrive   → scheduling_plan_detail.status: dispatched → arrived
        离店 depart   → arrived → done
        完成 complete → arrived → done

    ★ 为什么离店/完成统一落 `done` 而不是再引入一个 `departed`：
      现有代码（replan 的「锁定已执行趟次」）只认 dispatched/completed，
      下游报表也按 done 口径统计；多造一个状态会到处漏改。
      所以「离店」与「完成」的**业务差异**记录在 trip_stop_record.action 里。

    动作序列：到店 →（离店 | 完成）。两个终态动作是平的，不能串行
    （串行的话第二步会被「已完成」拦掉）。

    幂等保护：同一门店不允许连着打两次同样的卡（重复点击/弱网重发）。
    """
    driver = require_driver(db, user)

    detail = db.get(SchedulingPlanDetail, payload.plan_detail_id)
    if detail is None:
        raise NotFoundError("计划明细不存在")

    # 只能给自己的车打卡（越权直接 403，不泄露别人的趟次信息）
    vehicle = db.get(Vehicle, detail.vehicle_id)
    if vehicle is None or vehicle.driver_id != driver.id:
        raise ForbiddenError("该门店不属于你名下的车辆")

    if detail.status == DETAIL_PLANNED:
        # 计划还没下发就打卡，说明这不是司机该看到的数据
        raise ConflictError("该趟次尚未下发，无法打卡")

    if _is_detail_done(detail.status) and payload.action != ACTION_COMPLETE:
        raise ConflictError("该门店已完成，无需重复操作")

    last = (
        db.query(TripStopRecord)
        .filter(
            TripStopRecord.plan_detail_id == detail.id,
            TripStopRecord.driver_id == driver.id,
        )
        .order_by(TripStopRecord.id.desc())
        .first()
    )
    last_action = last.action if last else ""

    # 动作顺序校验：到店 → （离店 | 完成）
    # ★ 「离店」和「完成」是**平的**两个终态动作，不是串行的两步：
    #   · 离店 depart   —— 卸完货走人，这一店算做完（最常见的终态）
    #   · 完成 complete —— 一次性交付/无需单独离店登记，直接收尾
    #   两者都把明细推进到 done，差异只记录在 trip_stop_record.action 里。
    #   如果要求「先离店再完成」，第二步必然被上面的「已完成」拦掉（死路）。
    if payload.action == ACTION_ARRIVE and last_action == ACTION_ARRIVE:
        raise ConflictError("该门店已打过到店卡，请勿重复打卡")
    if payload.action in (ACTION_DEPART, ACTION_COMPLETE) and last_action != ACTION_ARRIVE:
        raise ConflictError(f"请先打「到店」卡再{ACTION_LABELS[payload.action]}")

    record = TripStopRecord(
        plan_detail_id=detail.id,
        driver_id=driver.id,
        store_id=detail.store_id,
        action=payload.action,
        latitude=payload.latitude,
        longitude=payload.longitude,
        remark=payload.remark,
        photo_attachment_ids=dump_photo_ids(payload.photo_attachment_ids),
    )
    db.add(record)

    # 推进计划明细状态（只动 status，计划内容保持不可变）
    detail.status = DETAIL_ARRIVED if payload.action == ACTION_ARRIVE else DETAIL_DONE

    db.commit()
    db.refresh(record)

    # 本趟整体进度（打卡结果里返回，司机端不必再查一次）
    siblings = (
        db.query(SchedulingPlanDetail)
        .filter(
            SchedulingPlanDetail.plan_id == detail.plan_id,
            SchedulingPlanDetail.vehicle_id == detail.vehicle_id,
            SchedulingPlanDetail.trip_no == detail.trip_no,
        )
        .all()
    )
    done = sum(1 for s in siblings if _is_detail_done(s.status))
    arrived = sum(1 for s in siblings if s.status == DETAIL_ARRIVED)
    plan = db.get(SchedulingPlan, detail.plan_id)

    return MobileCheckinResult(
        record_id=record.id,
        plan_detail_id=detail.id,
        trip_key=build_trip_key(
            plan.task_id if plan else 0, detail.plan_id, detail.vehicle_id, detail.trip_no
        ),
        action=payload.action,
        occurred_at=record.occurred_at,
        plan_detail_status=detail.status,
        trip_status=_trip_status(len(siblings), done, arrived),
        message=f"已记录{ACTION_LABELS[payload.action]}（{len(siblings) - done} 个门店待完成）",
    )


# ---------------------------------------------------------------------------
# 异常上报（复用现有 exception_event 表）
# ---------------------------------------------------------------------------
def report_exception(
    db: Session, user: SysUser, payload: MobileExceptionCreate
) -> MobileExceptionOut:
    """司机异常上报。

    ★ 刻意复用 `exception_event` 而**不新建表**：
      调度员侧的 `POST /api/scheduling/exceptions` 已经在写这张表，
      并且「异常重排」页面读的也是它。司机上报只是同一个业务事实的另一个来源，
      另建一张表会让重排页面必须同时读两处，得不偿失。

      差异体现在字段上（不动调度员接口）：
        · source  = `driver:<工号>`（调度员接口用 actor.username）
        · status  = `pending`（等待调度员处理，与现有默认值一致）
        · payload = 门店 / 趟次 / 照片 / 经纬度 / 上报人等司机端字段的 JSON

      同时**不改** `POST /api/scheduling/exceptions` 的任何行为。
    """
    driver = require_driver(db, user)

    task = db.get(SchedulingTask, payload.task_id)
    if task is None:
        raise NotFoundError("调度任务不存在")

    # 门店坐标等只作记录，不参与判断；但明确关掉「乱传门店 id」
    if payload.store_id is not None and db.get(Store, payload.store_id) is None:
        raise NotFoundError("门店不存在")

    detail_payload: dict[str, Any] = {
        "来源": "司机端",
        "上报人": user.username,
        "司机工号": driver.code,
        "司机姓名": driver.name,
        "司机电话": driver.phone,
        "门店ID": payload.store_id,
        "趟次": payload.trip_key,
        "计划明细ID": payload.plan_detail_id,
        "经度": payload.longitude,
        "纬度": payload.latitude,
        "照片附件": payload.photo_attachment_ids,
        "备注": payload.remark,
        "上报时间": datetime.now().isoformat(timespec="seconds"),
    }

    event = ExceptionEvent(
        task_id=task.id,
        event_type=payload.event_type,
        source=f"driver:{driver.code}",
        payload=json.dumps(detail_payload, ensure_ascii=False),
        status="pending",
    )
    db.add(event)
    db.commit()
    db.refresh(event)

    return MobileExceptionOut(
        id=event.id,
        task_id=event.task_id,
        event_type=event.event_type,
        source=event.source,
        status=event.status,
        occurred_at=event.occurred_at,
        message="异常已上报，调度员可在「异常重排」页面处理",
    )


# ---------------------------------------------------------------------------
# 文件上传（真正的 multipart 落盘）
# ---------------------------------------------------------------------------
def upload_dir() -> Path:
    """上传根目录（绝对路径），不存在则创建。"""
    path = settings.upload_dir
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe_extension(filename: str) -> str:
    """取扩展名并校验白名单。返回小写扩展名（含点）。"""
    ext = Path(filename or "").suffix.lower()
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        allowed = " / ".join(sorted(e.lstrip(".") for e in ALLOWED_IMAGE_EXTENSIONS))
        raise AppError(f"只允许上传 {allowed} 格式的图片，收到 {ext or '（无扩展名）'}")
    return ext


def _unique_name(directory: Path, base: str, ext: str) -> str:
    """同名冲突自动改名：原名被占用时追加短随机串，最多试几次。

    ★ 不用「覆盖」也不用「时间戳」：
      覆盖会丢文件；纯时间戳在并发上传时仍可能撞名。短随机串最省事且可读。
    """
    candidate = f"{base}{ext}"
    if not (directory / candidate).exists():
        return candidate
    for _ in range(5):
        candidate = f"{base}-{uuid.uuid4().hex[:8]}{ext}"
        if not (directory / candidate).exists():
            return candidate
    raise ConflictError("同名文件过多，请稍后重试或重命名后上传")


def _unique_attachment_name(db: Session, name: str, ext: str) -> str:
    """sys_attachment.name 在库里必须唯一（见 attachments 接口的冲突校验）。

    ★ 这里不能改现有表结构（不加唯一约束也不改口径），
      所以：落盘文件名保证不冲突（用户看不出差别）；
      登记名若已存在，在扩展名前追加短随机串，保证登记也能成功。
    """
    exists = db.query(SysAttachment).filter(SysAttachment.name == name).one_or_none()
    if exists is None:
        return name
    stem = Path(name).stem
    for _ in range(5):
        candidate = f"{stem}-{uuid.uuid4().hex[:8]}{ext}"
        if (
            db.query(SysAttachment).filter(SysAttachment.name == candidate).one_or_none()
            is None
        ):
            return candidate
    raise ConflictError("同名附件过多，请稍后重试")


def save_upload(db: Session, user: SysUser, file: UploadFile, biz_type: str = "司机端") -> MobileFileOut:
    """保存上传的图片：落盘 + 在 sys_attachment 登记一条记录。

    ★ 这是本项目第一个**真正落盘**的上传接口：
      `app/routers/attachments.py` 只登记元信息（storage_path 留空），
      不能把照片存下来，所以司机端现场拍照必须另开这一个。

    安全约束：
      · 扩展名白名单 jpg/jpeg/png/webp
      · 落盘文件名由服务端生成（uuid + 白名单扩展名），**不使用**客户端文件名，
        避免 `../../` 之类的路径穿越
      · 大小上限 10MB，超限即删除已写入的分片并报错
    """
    original = (file.filename or "").strip()
    ext = _safe_extension(original)
    directory = upload_dir()
    # 原文件名仅用于生成可读的落盘名前缀，且做一次安全清洗
    raw_stem = Path(original).stem
    safe_stem = re.sub(r"[^0-9A-Za-z_\u4e00-\u9fff-]", "_", raw_stem)[:40] or "photo"
    stored_name = _unique_name(directory, f"{safe_stem}-{uuid.uuid4().hex[:8]}", ext)
    target = directory / stored_name

    size = 0
    try:
        with target.open("wb") as fh:
            while True:
                chunk = file.file.read(UPLOAD_CHUNK_BYTES)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise AppError(
                        f"文件超过 {MAX_UPLOAD_BYTES // 1024 // 1024}MB 上限，已拒绝"
                    )
                fh.write(chunk)
    except AppError:
        target.unlink(missing_ok=True)
        raise
    except OSError as exc:  # noqa: BLE001
        target.unlink(missing_ok=True)
        logger.exception("上传文件写入失败：%s", exc)
        raise AppError(f"文件保存失败：{exc}") from exc

    if size == 0:
        target.unlink(missing_ok=True)
        raise AppError("上传的文件是空的")

    # 登记元信息。name 沿用客户端原文件名（附件管理页面看到的还是原名）
    record_name = _unique_attachment_name(db, original or stored_name, ext)
    relative_path = f"{settings.UPLOAD_DIR}/{stored_name}"
    item = SysAttachment(
        name=record_name,
        biz_type=biz_type or "司机端",
        size=size,
        storage_path=relative_path,
        uploader=user.username,
    )
    db.add(item)
    db.commit()
    db.refresh(item)

    return MobileFileOut(
        attachment_id=item.id,
        name=item.name,
        size=item.size,
        content_type=file.content_type or "",
        storage_path=item.storage_path,
        url=attachment_url(item.storage_path),
    )


def attachment_url(storage_path: str) -> str:
    """附件访问地址。已挂载 /uploads 静态目录，可直接 GET。"""
    if not storage_path:
        return ""
    return f"{settings.UPLOAD_URL_PREFIX.rstrip('/')}/{Path(storage_path).name}"


# ---------------------------------------------------------------------------
# 站内消息
# ---------------------------------------------------------------------------
def notification_payload(row: MobileNotification) -> dict[str, Any]:
    """站内消息 → 推送报文里的 notification 对象。

    ★ 字段刻意与 `MobileNotificationOut` 完全一致：
      这样小程序「收到推送直接插进列表」和「重新拉一次列表」
      拿到的是同一种对象，页面不需要为两条路径各写一套渲染。
    """
    return {
        "id": row.id,
        "title": row.title,
        "content": row.content,
        "biz_type": row.biz_type,
        "biz_id": row.biz_id,
        "is_read": bool(row.is_read),
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def push_notification(db: Session, row: MobileNotification) -> None:
    """把一条刚落库的站内消息实时推给收件人。

    ★ 只在 `db.commit()` **之后**调用：先让消息查得到，再告诉司机「有新消息」。
      顺序反了就会出现「收到推送，点进去列表是空的」。

    ★ 推送失败（司机离线、连接已断）只记日志，不抛异常 ——
      调用链上游是「下发执行」，通知不能反过来把下发搞失败。
    """
    try:
        unread = unread_count_for_user(db, row.user_id)
        realtime.publish_notification(
            notification=notification_payload(row),
            user_id=row.user_id,
            unread=unread,
        )
        logger.info(
            "站内消息已推送：user_id=%s / %s（未读 %d）", row.user_id, row.title, unread
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("站内消息推送失败（不影响入库）：%s", exc)


def create_notification(
    db: Session,
    *,
    user_id: int,
    title: str,
    content: str = "",
    biz_type: str = BIZ_SYSTEM,
    biz_id: int | None = None,
) -> MobileNotification:
    """新建一条站内消息并**立即实时推送**，返回落库后的记录。

    ★ 这是「通知创建处」的唯一入口：站内消息的写入与推送绑在一起，
      避免将来某处直接 `db.add(MobileNotification(...))` 而漏掉推送
      （那样司机会遇到「切回页面才看到」，也就是本次要修的体验缺陷）。

    ★ `notify_dispatch` 不用这个函数：它在一次下发里要批量写入多条，
      希望只 commit 一次，所以共用下面的 `push_notification`。
    """
    row = MobileNotification(
        user_id=user_id,
        title=title,
        content=content,
        biz_type=biz_type or BIZ_SYSTEM,
        biz_id=biz_id,
        is_read=False,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    push_notification(db, row)
    return row


def notify_dispatch(db: Session, task_id: int) -> int:
    """下发成功后给相关司机各写一条站内消息，返回写入条数。

    ★ 由 `dispatch_task` 在下发成功之后调用，但它**绝不能影响下发本身**：
      调用方已经用 try/except 包住，这里再保证「没有账号就跳过」而不是抛错。

    收件人 = 该方案涉及车辆对应的司机 → 该司机的登录账号（md_driver.user_id）。
    没有账号的司机拿不到站内消息（本项目不做微信订阅消息，所以也没有别的通道），
    这种情况只记日志，不报错。

    ★ 每写一条就实时推一条（WebSocket）：管理员点完「下发执行」，
      在线的司机端当场收到，不用等切页面。推不到（司机离线）不影响下发。
    """
    task = db.get(SchedulingTask, task_id)
    if task is None:
        logger.warning("通知跳过：调度任务 %s 不存在", task_id)
        return 0

    # 该任务已下发的趟次（按车辆归并），用 dispatch_record 作为「真的发下去了」的依据
    dispatches = (
        db.query(DispatchRecord)
        .filter(DispatchRecord.task_id == task_id)
        .order_by(DispatchRecord.id)
        .all()
    )
    if not dispatches:
        return 0

    trips_by_vehicle: dict[int, set[int]] = {}
    for record in dispatches:
        # trip_id 形如 task:plan:vehicle:trip
        parts = record.trip_id.split(":")
        trip_no = int(parts[3]) if len(parts) == 4 and parts[3].isdigit() else 0
        trips_by_vehicle.setdefault(record.vehicle_id, set()).add(trip_no)

    created = 0
    # 本次真正新增（未命中幂等去重）的消息：commit 之后统一推送
    fresh: list[MobileNotification] = []
    for vehicle_id, trip_nos in trips_by_vehicle.items():
        vehicle = db.get(Vehicle, vehicle_id)
        if vehicle is None or not vehicle.driver_id:
            continue
        driver = db.get(Driver, vehicle.driver_id)
        if driver is None or not driver.user_id:
            logger.info(
                "通知跳过：车辆 %s 的司机未绑定登录账号（任务 %s）", vehicle.plate_no, task.code
            )
            continue

        # 标题带上车牌：一个司机名下可能有多台车，不带车牌会生成多条
        # 标题完全相同、无法区分的消息。
        title = f"新任务下发：{task.code}（{vehicle.plate_no}）"
        content = (
            f"{task.schedule_date} {task.time_window} 时段，"
            f"车牌 {vehicle.plate_no} 共 {len(trip_nos)} 个趟次"
            f"（趟次号 {('、'.join(str(n) for n in sorted(trip_nos)))}），"
            f"请在小程序「我的趟次」中查看并按时打卡。"
        )
        # 幂等：同一次下发重复调用不会给司机刷出一堆重复消息
        exists = (
            db.query(MobileNotification)
            .filter(
                MobileNotification.user_id == driver.user_id,
                MobileNotification.biz_type == BIZ_DISPATCH,
                MobileNotification.biz_id == task.id,
                MobileNotification.title == title,
            )
            .one_or_none()
        )
        if exists is not None:
            continue

        row = MobileNotification(
            user_id=driver.user_id,
            title=title,
            content=content,
            biz_type=BIZ_DISPATCH,
            biz_id=task.id,
            is_read=False,
        )
        db.add(row)
        fresh.append(row)
        created += 1

    if fresh:
        db.commit()
        # ★ 先落库、再推送（顺序见 push_notification 的说明）。
        #   推送本身不会抛异常，所以这里不需要 try/except 兜底。
        for row in fresh:
            push_notification(db, row)
    return created


def list_notifications(
    db: Session, user: SysUser, only_unread: bool = False, limit: int = 50
) -> list[MobileNotificationOut]:
    """当前登录人的站内消息（最新的在前）。"""
    query = db.query(MobileNotification).filter(MobileNotification.user_id == user.id)
    if only_unread:
        query = query.filter(MobileNotification.is_read.is_(False))
    rows = query.order_by(MobileNotification.id.desc()).limit(max(1, min(limit, 200))).all()
    return [MobileNotificationOut.model_validate(row) for row in rows]


def mark_read(db: Session, user: SysUser, notification_id: int) -> MobileNotificationOut:
    """标记单条已读。★ 只能读自己的消息（按 user_id 过滤，越权即 404）。"""
    row = (
        db.query(MobileNotification)
        .filter(
            MobileNotification.id == notification_id,
            MobileNotification.user_id == user.id,
        )
        .one_or_none()
    )
    if row is None:
        raise NotFoundError("消息不存在")
    if not row.is_read:
        row.is_read = True
        db.commit()
        db.refresh(row)
    return MobileNotificationOut.model_validate(row)


def unread_count_for_user(db: Session, user_id: int) -> int:
    """按 user_id 统计未读（实时推送需要在没有 SysUser 对象时也算一次）。"""
    return (
        db.query(func.count(MobileNotification.id))
        .filter(
            MobileNotification.user_id == user_id,
            MobileNotification.is_read.is_(False),
        )
        .scalar()
        or 0
    )


def unread_count(db: Session, user: SysUser) -> int:
    return unread_count_for_user(db, user.id)


# ---------------------------------------------------------------------------
# 管理端只读首页（小程序「今日看板」）
# ---------------------------------------------------------------------------
# 为什么在后端聚合一次：
#   小程序端弱网下打 4 个接口（任务/趟次/异常/监控）既慢又容易出现
#   「几个数字来自不同时刻」的不一致。看板是只读快照，一次算清最稳。
#   本组函数**只读**：不改任何业务表，也不写审计（避免刷日志）。

# 看板上展示的最近异常条数
RECENT_EXCEPTION_LIMIT = 5


def _payload_summary(raw: str | None, limit: int = 60) -> str:
    """异常 payload 的摘要（JSON 文本 → 一行可读文本）。

    ★ 坏数据（空串、半截 JSON）一律退化为原文截断：
      看板不能因为一条脏记录整个接口 500。
    """
    text = (raw or "").strip()
    if not text or text == "{}":
        return ""
    try:
        value = json.loads(text)
    except (ValueError, TypeError):
        return text[:limit]
    if not isinstance(value, dict):
        return str(value)[:limit]
    # 优先挑对调度最有信息量的键，其余键拼在后面
    preferred = ["备注", "上报人", "司机姓名", "趟次", "门店ID", "计划明细ID", "原因", "说明"]
    parts: list[str] = []
    for key in preferred:
        if key in value and value[key] not in (None, "", []):
            parts.append(f"{key}={value[key]}")
    if not parts:
        for key, item in list(value.items())[:4]:
            if item in (None, "", [], {}):
                continue
            parts.append(f"{key}={item}")
    return "；".join(parts)[:limit]


def manager_overview(db: Session, schedule_date: date | None = None) -> MobileManagerOverviewOut:
    """管理端只读首页的聚合数据。

    口径逐项说明（都能回溯到具体表）：

    · **今日任务数与各状态计数**：`scheduling_task.schedule_date = 今天`，
      按 status 归并（本项目实际取值 created/running/pending_confirm/dispatched/completed/failed）。
    · **趟次总数 / 已接单 / 未接单**：`dispatch_record` 的条数就是「已下发的趟次数」
      （一行 = 任务·方案·车·趟）。`accepted_at` 非空即已接单，因此
      未接单数 = 总趟次数 − 已接单数，三者永远自洽（不依赖任何推算）。
    · **在途车辆数**：名下车辆中有趟次**已下发但尚未全部完成**的车辆数
      （即「今天还有活在车上」的车）。本项目没有 GPS 回传，
      所以不用「车辆状态字段」凑数 —— `md_vehicle.status` 在演示库恒为 idle，
      拿它统计会得到一个永远为 0 的假指标。
    · **待处理异常数**：`exception_event.status = 'pending'` 全量计数
      （异常是跨天滚动的待办，不做「仅今日」过滤，否则昨天的未处理异常会消失）。
    · **最近异常摘要**：按 id 倒序取若干条，payload 压成一行可读文本。
    """
    target_date = schedule_date or date.today()

    # --- 今日任务 ---
    task_rows = (
        db.query(SchedulingTask.status, func.count(SchedulingTask.id))
        .filter(SchedulingTask.schedule_date == target_date)
        .group_by(SchedulingTask.status)
        .all()
    )
    by_status = {str(status): int(count) for status, count in task_rows}
    tasks = MobileTaskStatOut(total=sum(by_status.values()), by_status=by_status)
    # 当日任务 id：下面「趟次/接单」「执行完成情况」「在途车辆」都要按日期限定范围，
    # 所以在这里先算一次，避免每组各查一遍（也避免漏掉某一组）。
    day_task_ids = [
        row[0]
        for row in db.query(SchedulingTask.id)
        .filter(SchedulingTask.schedule_date == target_date)
        .all()
    ]

    # --- 趟次（下发记录）与接单情况 ---
    # ★ 拆成两个数（老代码只有一个全表 total，导致「换日期看，趟次数永远一样」）：
    #   · day_dispatch_total  —— 当日任务的已下发趟次，**看板各卡片都用它**；
    #   · all_dispatch_total  —— 全表累计，只作为「累计」参考展示。
    all_dispatch_total = db.query(func.count(DispatchRecord.id)).scalar() or 0
    day_dispatch_total = (
        db.query(func.count(DispatchRecord.id))
        .filter(DispatchRecord.task_id.in_(day_task_ids))
        .scalar()
        or 0
    )
    day_accepted_total = (
        db.query(func.count(DispatchRecord.id))
        .filter(
            DispatchRecord.task_id.in_(day_task_ids),
            DispatchRecord.accepted_at.isnot(None),
        )
        .scalar()
        or 0
    )
    trips = MobileTripStatOut(
        total=int(day_dispatch_total),
        accepted=int(day_accepted_total),
        pending=int(day_dispatch_total) - int(day_accepted_total),
        dispatch_records=int(day_dispatch_total),
        all_time= int(all_dispatch_total),
    )

    # --- 执行完成情况（今天跑完了多少趟）---
    # ★ 只统计**真正下发过的趟次**（有 dispatch_record 的那些），两个原因：
    #   ① 一次调度产出 A/B/C/D 多套方案，它们共用同一批车与趟次号；
    #      按全部方案统计会把活算成 4 倍（实测：4 套方案 83 趟 vs 实际下发 47 趟）。
    #   ② dispatch_record 的条数就是「下发的趟次数」，和同一张看板上
    #      trips.total 口径一致，两个数字能对上，不会自相矛盾。
    #   ★ 范围严格限定在**当日任务**：老实现里 dispatch_total 是全表计数
    #   （不带日期），换个日期看会把别的天的活算进来。
    #   ★ 没有 `if task_ids` 兜底：`in_([])` 在 SQLAlchemy 里编译成
    #   「不匹配任何行」的假条件，正是我们要的语义（当天没任务 → 无完成情况）。
    completion = MobileCompletionStatOut()
    trip_briefs: list[MobileTripBriefOut] = []
    dispatched_keys = set()
    # trip_id 形如 task:plan:vehicle:trip，这里只需要它的 trip_no 段；
    # plan_id / vehicle_id 直接取 dispatch_record 自己的列，不重复解析。
    # 顺带记下「这一趟司机接单了没、是哪个任务、哪个方案」——
    # 趟次明细卡要展示这些，免得再查一遍 dispatch_record。
    dispatch_meta: dict[tuple[int, int, int], tuple[bool, int, int]] = {}
    for plan_id, trip_id, vehicle_id, accepted_at, task_id in (
        db.query(
            DispatchRecord.plan_id,
            DispatchRecord.trip_id,
            DispatchRecord.vehicle_id,
            DispatchRecord.accepted_at,
            DispatchRecord.task_id,
        )
        .filter(DispatchRecord.task_id.in_(day_task_ids))
        .all()
    ):
        parts = str(trip_id).split(":")
        trip_no = int(parts[3]) if len(parts) == 4 and parts[3].isdigit() else 0
        key = (plan_id, vehicle_id, trip_no)
        dispatched_keys.add(key)
        dispatch_meta[key] = (accepted_at is not None, task_id, plan_id)

    if day_task_ids and dispatched_keys:
        detail_rows = (
            db.query(
                SchedulingPlanDetail.plan_id,
                SchedulingPlanDetail.vehicle_id,
                SchedulingPlanDetail.trip_no,
                SchedulingPlanDetail.time_window,
                SchedulingPlanDetail.status,
                func.count(SchedulingPlanDetail.id),
            )
            .filter(
                SchedulingPlanDetail.plan_id.in_({k[0] for k in dispatched_keys}),
                SchedulingPlanDetail.status.in_(
                    [DETAIL_DISPATCHED, DETAIL_ARRIVED, DETAIL_DONE]
                ),
            )
            .group_by(
                SchedulingPlanDetail.plan_id,
                SchedulingPlanDetail.vehicle_id,
                SchedulingPlanDetail.trip_no,
                SchedulingPlanDetail.time_window,
                SchedulingPlanDetail.status,
            )
            .all()
        )
        # 先把「明细行」聚合到「趟次」：一趟完成 = 该趟所有门店都 done。
        # per_trip 顺便承载下面趟次明细卡要用的门店数/时段，一次查询两用。
        per_trip: dict[tuple[int, int, int], dict[str, Any]] = {}
        for plan_id, vehicle_id, trip_no, time_window, status, count in detail_rows:
            key = (plan_id, vehicle_id, trip_no)
            if key not in dispatched_keys:
                continue  # 只在真正下发过的趟次里统计
            bucket = per_trip.setdefault(
                key, {"status": {}, "time_window": str(time_window)}
            )
            bucket["status"][str(status)] = int(count)

        # 车辆 / 司机 / 任务号：明细卡要显示「哪台车、谁开、哪个任务」
        vehicle_ids = {k[1] for k in per_trip}
        vehicles = {
            v.id: v
            for v in db.query(Vehicle).filter(Vehicle.id.in_(vehicle_ids)).all()
        } if vehicle_ids else {}
        driver_ids = {v.driver_id for v in vehicles.values() if v.driver_id}
        drivers = {
            d.id: d.name
            for d in db.query(Driver).filter(Driver.id.in_(driver_ids)).all()
        } if driver_ids else {}
        # 任务号只有当日任务，取一次给明细卡用（下面「最近异常」另有一份，避免重名）
        trip_task_codes = {
            t.id: t.code
            for t in db.query(SchedulingTask)
            .filter(SchedulingTask.id.in_(day_task_ids))
            .all()
        }

        for key, bucket in per_trip.items():
            counts = bucket["status"]
            total_stores = sum(counts.values())
            done_stores = sum(n for s, n in counts.items() if s in DETAIL_DONE_ALIASES)
            arrived_stores = counts.get(DETAIL_ARRIVED, 0)
            completion.trips_total += 1
            completion.stores_total += total_stores
            completion.stores_done += done_stores
            if total_stores and done_stores >= total_stores:
                completion.finished += 1
            elif done_stores or arrived_stores:
                completion.running += 1
            else:
                completion.not_started += 1

            # 「趟次明细」：看板最上面那块要逐趟显示，所以在这里顺手拼好。
            # ★ 一趟一条（不是一店一条）—— 47 趟 / 61 店，逐店列会把看板撑爆。
            plan_id, vehicle_id, trip_no = key
            accepted, task_id, _plan = dispatch_meta.get(key, (False, 0, plan_id))
            vehicle = vehicles.get(vehicle_id)
            driver_id = vehicle.driver_id if vehicle else None
            if total_stores and done_stores >= total_stores:
                state = "done"
            elif done_stores or arrived_stores:
                state = "running"
            elif accepted:
                # 已接单但一个门店都没打卡 —— 司机接了活正在路上/还没出发
                state = "accepted"
            else:
                state = "pending"
            trip_briefs.append(
                MobileTripBriefOut(
                    trip_key=f"{task_id}:{plan_id}:{vehicle_id}:{trip_no}",
                    task_id=task_id,
                    task_code=trip_task_codes.get(task_id, ""),
                    plan_id=plan_id,
                    trip_no=trip_no,
                    time_window=bucket["time_window"],
                    vehicle_id=vehicle_id,
                    plate_no=vehicle.plate_no if vehicle else "",
                    driver_name=drivers.get(driver_id, "") if driver_id else "",
                    store_count=total_stores,
                    done_stores=done_stores,
                    arrived_stores=arrived_stores,
                    accepted=accepted,
                    state=state,
                )
            )

        # 排序：**要盯的排前面** —— 正在跑 → 已接单未出车 → 未确认 → 已完成。
        # 同一状态里按车牌 + 趟次号，方便按车核对（与司机端「三色」语义一致：
        # 红/黄在上面，绿沉底，只是这里把「已接单」和「未接单」分得更细）。
        state_rank = {"running": 0, "accepted": 1, "pending": 2, "done": 3}
        trip_briefs.sort(
            key=lambda t: (
                state_rank.get(t.state, 9),
                t.plate_no,
                t.trip_no,
            )
        )

    # --- 在途车辆 ---
    # 「在途」= 有趟次已下发、但该趟还有门店没跑完（kpi：现在路上有几台车在干活）。
    # 一旦某趟所有门店都是 done，这台车这一趟就结束了，不再计入在途。
    vehicle_total = db.query(func.count(Vehicle.id)).filter(Vehicle.is_active.is_(True)).scalar() or 0
    in_transit = (
        db.query(func.count(func.distinct(SchedulingPlanDetail.vehicle_id)))
        .join(SchedulingPlan, SchedulingPlan.id == SchedulingPlanDetail.plan_id)
        .join(SchedulingTask, SchedulingTask.id == SchedulingPlan.task_id)
        .filter(
            SchedulingTask.status.in_(["dispatched", "completed"]),
            SchedulingPlanDetail.status.in_([DETAIL_DISPATCHED, DETAIL_ARRIVED]),
        )
        .scalar()
        or 0
    )
    vehicles = MobileVehicleStatOut(total=int(vehicle_total), in_transit=int(in_transit))

    # --- 异常 ---
    pending_exceptions = (
        db.query(func.count(ExceptionEvent.id))
        .filter(ExceptionEvent.status == "pending")
        .scalar()
        or 0
    )
    total_exceptions = db.query(func.count(ExceptionEvent.id)).scalar() or 0
    exceptions = MobileExceptionStatOut(
        pending=int(pending_exceptions), total=int(total_exceptions)
    )

    # --- 最近异常摘要 ---
    recent_rows = (
        db.query(ExceptionEvent)
        .order_by(ExceptionEvent.id.desc())
        .limit(RECENT_EXCEPTION_LIMIT)
        .all()
    )
    task_codes = {
        t.id: t.code
        for t in db.query(SchedulingTask)
        .filter(SchedulingTask.id.in_({e.task_id for e in recent_rows} or {0}))
        .all()
    }
    recent = [
        MobileExceptionBriefOut(
            id=e.id,
            task_id=e.task_id,
            task_code=task_codes.get(e.task_id, ""),
            event_type=e.event_type,
            source=e.source,
            status=e.status,
            occurred_at=e.occurred_at,
            summary=_payload_summary(e.payload),
        )
        for e in recent_rows
    ]

    return MobileManagerOverviewOut(
        schedule_date=target_date,
        generated_at=datetime.now(),
        tasks=tasks,
        trips=trips,
        completion=completion,
        trip_briefs=trip_briefs,
        vehicles=vehicles,
        exceptions=exceptions,
        recent_exceptions=recent,
    )


# ---------------------------------------------------------------------------
# 司机档案
# ---------------------------------------------------------------------------
def profile(db: Session, user: SysUser) -> MobileProfileOut:
    """当前账号的司机档案 + 名下车辆。

    管理员/调度员没有司机档案时不报错，返回 is_driver=False 的空档案 ——
    这样同一个接口可以被小程序和管理端复用，也方便排查「为什么我什么都看不到」。
    """
    driver = get_driver(db, user)
    if driver is None:
        return MobileProfileOut(
            username=user.username,
            nickname=user.nickname,
            phone=user.phone,
            is_driver=False,
        )

    names = _vehicle_type_names(db)
    vehicles = get_driver_vehicles(db, driver)
    return MobileProfileOut(
        username=user.username,
        nickname=user.nickname,
        phone=user.phone or driver.phone,
        is_driver=True,
        driver_id=driver.id,
        driver_code=driver.code,
        driver_name=driver.name,
        driver_phone=driver.phone,
        shift=driver.shift,
        driver_status=driver.status,
        vehicle_count=len(vehicles),
        vehicles=[
            MobileVehicleOut(
                id=v.id,
                plate_no=v.plate_no,
                vehicle_type_code=v.vehicle_type_code,
                vehicle_type_name=names.get(v.vehicle_type_code, ""),
                terrain_capability=v.terrain_capability,
                status=v.status,
            )
            for v in vehicles
        ],
    )
