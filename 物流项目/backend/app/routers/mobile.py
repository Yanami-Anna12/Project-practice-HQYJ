"""司机端（小程序）接口。

对应需求文档 二.7「移动端/司机端」。本模块是司机端**执行层**的入口，
业务逻辑全部在 `app/services/mobile.py`，这里只负责参数接收、权限依赖与响应组装。

接口清单（前缀 /api/mobile）：

    GET  /api/mobile/my-trips                     我的趟次列表
    GET  /api/mobile/trips/{trip_key}             趟次详情（门店序列 + 执行状态）
    POST /api/mobile/trips/{trip_key}/accept      司机确认接单（幂等）
    POST /api/mobile/checkin                      现场打卡（到店 / 离店 / 完成）
    POST /api/mobile/exceptions                   异常上报（复用 exception_event）
    POST /api/mobile/files                        图片上传（真正的 multipart 落盘）
    GET  /api/mobile/notifications                站内消息列表
    GET  /api/mobile/notifications/unread-count   未读数
    POST /api/mobile/notifications/{id}/read      标记已读
    GET  /api/mobile/profile                      当前司机档案 + 名下车辆
    GET  /api/mobile/manager/overview             管理端只读首页聚合（看板）

★ 权限：`/api/mobile/*` 统一使用 `require_mobile_access`（见 app/deps.py）——
  司机角色持有 `mobile:use` 即可调用；管理员角色是 `*`，调度员按需授权，
  两者调用都不会报错。**执行类**接口（确认接单/打卡/异常/档案）另外要求账号已绑定
  司机档案，否则无法确认「你是谁的车」，会返回 403 而不是静默写脏数据。

  ★ 例外一：`/api/mobile/manager/overview` 是**看板只读**接口，走
    `require_permission("scheduling:read")`（scheduling 路由的同一口径）：
    admin / dispatcher / viewer / multi 均可用，司机账号 403。
    这样「谁能看看板」与网页端「谁能看调度任务」永远一致，不会两套标准。

  ★ 例外二：站内消息三个接口（列表 / 未读数 / 标记已读）走 `CurrentUser`，
    **只要求已登录**，不再要 `mobile:use`。原因：消息是**双向**触达通道 ——
    「司机已确认接单」这类通知正是发给调度相关角色的（见 services/mobile.py 的
    notify_acceptance），而 dispatcher / viewer 默认没有 `mobile:use`，
    原先会 403，等于消息发出去没人能看。
    安全性不靠这个依赖：查询与标记已读在 service 层一律按 `user_id` 过滤
    （mark_read 越权返回 404），任何账号都只能看到自己的消息。

★ 登录复用 POST /api/auth/login（账号密码），不做微信登录。
"""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, File, Query, UploadFile

from app.deps import (
    DbSession,
    get_current_user,
    require_mobile_access,
    require_permission,
)
from app.models import SysUser
from app.schemas import (
    MobileCheckinRequest,
    MobileCheckinResult,
    MobileExceptionCreate,
    MobileExceptionOut,
    MobileFileOut,
    MobileManagerOverviewOut,
    MobileNotificationOut,
    MobileNotificationReadOut,
    MobileProfileOut,
    MobileTripAcceptResult,
    MobileTripDetailOut,
    MobileTripOut,
    MobileUnreadCountOut,
)
from app.services import mobile as mobile_service
from app.services.audit import append_audit

router = APIRouter(prefix="/mobile", tags=["司机端"])

# 司机端准入：持有 mobile:use 权限，或账号已绑定司机档案
MobileUser = Annotated[SysUser, Depends(require_mobile_access)]
# 管理端看板准入：与网页端 /api/scheduling/* 完全同一套权限点
ManagerUser = Annotated[SysUser, Depends(require_permission("scheduling:read"))]
# 站内消息准入：仅需登录（数据在 service 层按 user_id 隔离，见模块注释「例外二」）
NotificationUser = Annotated[SysUser, Depends(get_current_user)]


# ---------------------------------------------------------------------------
# 我的趟次
# ---------------------------------------------------------------------------
@router.get("/my-trips", response_model=list[MobileTripOut], summary="我的趟次列表")
def my_trips(
    db: DbSession,
    actor: MobileUser,
    schedule_date: date | None = Query(
        default=None, description="调度日期，留空表示全部已下发趟次"
    ),
) -> list[MobileTripOut]:
    """当前司机名下车辆已被下发的趟次。

    数据来源全是既有表：md_driver.user_id 认人 → md_vehicle.driver_id 认车
    → scheduling_plan_detail(status=dispatched) 认趟次，没有新增任何关联字段。
    """
    return mobile_service.my_trips(db, actor, schedule_date)


@router.get("/trips/{trip_key}", response_model=MobileTripDetailOut, summary="趟次详情")
def trip_detail(trip_key: str, db: DbSession, actor: MobileUser) -> MobileTripDetailOut:
    """trip_key 形如 `3:5:12:1`（任务:方案:车辆:趟次），与 dispatch_record.trip_id 同规则。

    返回按 sequence 排序的门店序列、每店货量、地址/电话/坐标，
    以及该店已有的执行记录与状态（供小程序渲染打卡按钮），
    并带上趟次级的 `accepted` / `accepted_at`（司机是否已确认接单）。
    """
    return mobile_service.trip_detail(db, actor, trip_key)


@router.post(
    "/trips/{trip_key}/accept",
    response_model=MobileTripAcceptResult,
    summary="司机确认接单",
)
def accept_trip(trip_key: str, db: DbSession, actor: MobileUser) -> MobileTripAcceptResult:
    """司机确认收到该趟任务。

    三条行为约定（详见 app/services/mobile.py 的 accept_trip）：

    1. 只能确认**自己名下车辆**的趟次，否则 403（越权不泄露别人的趟次信息）；
    2. **幂等**：重复确认返回 200 且 `accepted_at` 仍是**首次**确认时间，
       并用 `already_accepted=True` 区分「刚刚确认」与「早就确认过」；
    3. 首次确认后给调度相关角色各发一条站内消息（落库 + WebSocket 实时推送）。

    ★ 只写 dispatch_record 的 accepted_at / accepted_by，
      计划快照（scheduling_plan_detail）与任务状态一个都不动。
    """
    result = mobile_service.accept_trip(db, actor, trip_key)
    append_audit(
        db,
        actor=actor,
        action="mobile.accept_trip",
        target_type="plan_detail",
        target_name=result.trip_key,
        detail={
            "动作": "重复确认（幂等）" if result.already_accepted else "确认接单",
            "任务": result.task_code,
            "车牌": result.plate_no,
            "确认时间": result.accepted_at.isoformat(timespec="seconds"),
            "通知账号数": result.notified,
        },
    )
    return result


# ---------------------------------------------------------------------------
# 现场执行
# ---------------------------------------------------------------------------
@router.post("/checkin", response_model=MobileCheckinResult, summary="现场打卡")
def checkin(
    payload: MobileCheckinRequest, db: DbSession, actor: MobileUser
) -> MobileCheckinResult:
    """到店 / 离店 / 完成打卡。

    写 `trip_stop_record`（现场事实），并把 `scheduling_plan_detail.status`
    推进为 arrived / done。计划快照本身的门店、货量、顺序一个都不改。
    """
    result = mobile_service.checkin(db, actor, payload)
    append_audit(
        db,
        actor=actor,
        action="mobile.checkin",
        target_type="plan_detail",
        target_name=str(payload.plan_detail_id),
        detail={
            "动作": payload.action,
            "趟次": result.trip_key,
            "明细状态": result.plan_detail_status,
            "打卡定位": f"{payload.latitude},{payload.longitude}"
            if payload.latitude is not None and payload.longitude is not None
            else "（未上报）",
            "照片数": len(payload.photo_attachment_ids),
        },
    )
    return result


@router.post("/exceptions", response_model=MobileExceptionOut, summary="异常上报")
def report_exception(
    payload: MobileExceptionCreate, db: DbSession, actor: MobileUser
) -> MobileExceptionOut:
    """司机异常上报。

    ★ 复用现有 `exception_event` 表（不新建表），`source` 记为 `driver:<工号>`，
    `status` 用 pending，门店/趟次/照片/经纬度/上报人放进 payload JSON。
    调度员侧的 `POST /api/scheduling/exceptions` 行为完全不变。
    """
    result = mobile_service.report_exception(db, actor, payload)
    append_audit(
        db,
        actor=actor,
        action="mobile.exception",
        target_type="task",
        target_name=str(payload.task_id),
        detail={"类型": payload.event_type, "门店": payload.store_id, "趟次": payload.trip_key},
    )
    return result


@router.post("/files", response_model=MobileFileOut, summary="图片上传")
def upload_file(
    db: DbSession,
    actor: MobileUser,
    file: UploadFile = File(..., description="jpg / jpeg / png / webp，≤10MB"),
    biz_type: str = Query(default="司机端", max_length=32),
) -> MobileFileOut:
    """真正的 multipart 文件上传：落盘 backend/uploads/ 并在 sys_attachment 登记。

    ★ 与 `app/routers/attachments.py` 的区别：那个接口只登记元信息（演示模式，
    storage_path 留空），**不能把照片存下来**；司机端现场拍照必须有真实文件，
    所以单独开了这一个。落盘文件名由服务端生成（uuid），同名自动改名，
    客户端文件名只用于登记展示。
    """
    result = mobile_service.save_upload(db, actor, file, biz_type)
    append_audit(
        db,
        actor=actor,
        action="mobile.upload",
        target_type="attachment",
        target_name=result.name,
        detail={"类型": biz_type, "大小": result.size, "落盘": result.storage_path},
    )
    return result


# ---------------------------------------------------------------------------
# 站内消息
# ---------------------------------------------------------------------------
@router.get("/notifications", response_model=list[MobileNotificationOut], summary="消息列表")
def list_notifications(
    db: DbSession,
    actor: NotificationUser,
    only_unread: bool = Query(default=False, description="只看未读"),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[MobileNotificationOut]:
    """当前账号的站内消息。只做站内消息，不做微信订阅消息（没有 openid 做不到）。

    ★ 权限：仅需登录（见模块注释「例外二」）。返回的永远只是 `actor` 自己的消息。
    """
    return mobile_service.list_notifications(db, actor, only_unread, limit)


@router.get(
    "/notifications/unread-count",
    response_model=MobileUnreadCountOut,
    summary="未读消息数",
)
def unread_count(db: DbSession, actor: NotificationUser) -> MobileUnreadCountOut:
    """小程序未读角标用。★ 仅需登录，按登录人自己的 user_id 统计。"""
    return MobileUnreadCountOut(unread=mobile_service.unread_count(db, actor))


@router.post(
    "/notifications/{notification_id}/read",
    response_model=MobileNotificationReadOut,
    summary="标记消息已读",
)
def mark_read(
    notification_id: int, db: DbSession, actor: NotificationUser
) -> MobileNotificationReadOut:
    """标记单条已读。★ 仅需登录；只能读**自己**的消息，别人的消息返回 404。"""
    row = mobile_service.mark_read(db, actor, notification_id)
    return MobileNotificationReadOut(
        id=row.id, is_read=row.is_read, unread=mobile_service.unread_count(db, actor)
    )


# ---------------------------------------------------------------------------
# 管理端只读首页（小程序「今日看板」）
# ---------------------------------------------------------------------------
@router.get(
    "/manager/overview",
    response_model=MobileManagerOverviewOut,
    summary="管理端只读首页聚合",
)
def manager_overview(
    db: DbSession,
    actor: ManagerUser,
    schedule_date: date | None = Query(
        default=None, description="看板日期，留空表示今天"
    ),
) -> MobileManagerOverviewOut:
    """一次返回今日看板所需的全部数字（**只读**，不写任何业务表）。

    为什么不让小程序打 4 个接口：弱网下 4 次往返既慢，几个数字还可能来自
    不同时刻（例如「已接单数」比「趟次总数」晚拿到），页面上会自相矛盾。
    这里后端聚合一次，保证是同一时刻的一致快照。

    返回：今日任务数与各状态计数、趟次总数与**已接单/未接单数**、
    在途车辆数、待处理异常数与最近几条异常摘要。

    ★ 权限用的是 `scheduling:read`（与网页端调度任务列表同一口径）：
      admin / dispatcher / viewer / multi 可用，司机账号 403。
    """
    return mobile_service.manager_overview(db, schedule_date)


# ---------------------------------------------------------------------------
# 档案
# ---------------------------------------------------------------------------
@router.get("/profile", response_model=MobileProfileOut, summary="当前司机档案")
def profile(db: DbSession, actor: MobileUser) -> MobileProfileOut:
    """姓名、电话、班次、名下车辆车牌与车型。

    管理员/调度员没有司机档案时返回 is_driver=False 的空档案，不报错。
    """
    return mobile_service.profile(db, actor)
