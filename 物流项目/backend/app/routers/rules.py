"""调度规则配置接口。

    GET  /api/rules/overview      当前生效的全部规则（含硬/软约束清单与评分公式）
    GET  /api/rules/conflicts     规则冲突检测
    GET  /api/rules/versions      规则版本列表
    POST /api/rules/versions      发布新版本（快照 + 与上一版对比）
    GET  /api/rules/versions/{id} 版本详情（含快照与变更）
    POST /api/rules/versions/{id}/rollback  回滚到指定版本
"""

from __future__ import annotations

import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.deps import DbSession, require_permission
from app.errors import AppError, NotFoundError
from app.models import RuleVersion, SysParam, SysUser, VehicleTerrainCapability, VehicleType
from app.services import rules as rule_service
from app.services.audit import append_audit

router = APIRouter(prefix="/rules", tags=["调度规则配置"])

Reader = Annotated[SysUser, Depends(require_permission("scheduling:read"))]
Manager = Annotated[SysUser, Depends(require_permission("scheduling:create"))]


class VersionCreate(BaseModel):
    version: str | None = Field(default=None, max_length=32, description="留空自动递增")
    description: str = Field(default="", max_length=255)


@router.get("/overview", summary="当前生效的规则总览")
def overview(db: DbSession, actor: Reader) -> dict[str, Any]:
    return rule_service.rules_overview(db)


@router.get("/conflicts", summary="规则冲突检测")
def conflicts(db: DbSession, actor: Reader) -> list[dict[str, Any]]:
    return rule_service.conflict_check(db)


@router.get("/versions", summary="规则版本列表")
def list_versions(db: DbSession, actor: Reader) -> list[dict[str, Any]]:
    rows = db.query(RuleVersion).order_by(RuleVersion.id.desc()).limit(50).all()
    return [
        {
            "id": r.id,
            "version": r.version,
            "description": r.description,
            "change_summary": r.change_summary,
            "is_active": r.is_active,
            "published_by": r.published_by,
            "published_at": r.published_at,
        }
        for r in rows
    ]


@router.get("/versions/{version_id}", summary="版本详情")
def get_version(version_id: int, db: DbSession, actor: Reader) -> dict[str, Any]:
    r = db.get(RuleVersion, version_id)
    if r is None:
        raise NotFoundError("版本不存在")
    try:
        snapshot = json.loads(r.snapshot_json)
    except (ValueError, TypeError):
        snapshot = {}
    return {
        "id": r.id,
        "version": r.version,
        "description": r.description,
        "change_summary": r.change_summary,
        "published_by": r.published_by,
        "published_at": r.published_at,
        "snapshot": snapshot,
    }


@router.post("/versions", summary="发布新版本")
def publish_version(
    payload: VersionCreate, db: DbSession, actor: Manager
) -> dict[str, Any]:
    version = payload.version or rule_service.next_version(db)
    exists = db.query(RuleVersion).filter(RuleVersion.version == version).one_or_none()
    if exists is not None:
        raise AppError(f"版本 {version} 已存在")

    record, changes = rule_service.publish_version(
        db,
        version=version,
        description=payload.description,
        operator=actor.username,
    )

    append_audit(
        db,
        actor=actor,
        action="rule.publish",
        target_type="rule",
        target_name=record.version,
        detail={
            "说明": record.description,
            "变更项数": len(changes),
            "变更摘要": record.change_summary[:200],
        },
    )
    return {
        "id": record.id,
        "version": record.version,
        "change_count": len(changes),
        "changes": changes,
        "change_summary": record.change_summary,
    }


@router.post("/versions/{version_id}/rollback", summary="回滚到指定版本")
def rollback_version(
    version_id: int, db: DbSession, actor: Manager
) -> dict[str, Any]:
    """回滚：把历史快照里的规则写回各自的表。

    ★ 回滚本身也会生成一个新版本记录（而不是删除历史），
      这样「回滚」这个动作也在版本链里可追溯。
    """
    target = db.get(RuleVersion, version_id)
    if target is None:
        raise NotFoundError("版本不存在")

    try:
        snapshot = json.loads(target.snapshot_json)
    except (ValueError, TypeError):
        raise AppError("该版本的快照已损坏，无法回滚")

    restored = {"vehicle_types": 0, "terrain_matrix": 0, "params": 0}

    # --- 车辆类型 ---
    for item in snapshot.get("vehicle_types", []):
        vt = db.query(VehicleType).filter(VehicleType.code == item["code"]).one_or_none()
        if vt is None:
            continue
        vt.min_load = item["min_load"]
        vt.max_load = item["max_load"]
        vt.trips_per_day = item["trips_per_day"]
        vt.am_trips = item["am_trips"]
        vt.pm_trips = item["pm_trips"]
        vt.planned_count = item["planned_count"]
        restored["vehicle_types"] += 1

    # --- 地形通行矩阵 ---
    for item in snapshot.get("terrain_matrix", []):
        cell = (
            db.query(VehicleTerrainCapability)
            .filter(
                VehicleTerrainCapability.terrain_type == item["terrain_type"],
                VehicleTerrainCapability.capability == item["capability"],
            )
            .one_or_none()
        )
        if cell is None:
            continue
        cell.allowed = bool(item["allowed"])
        restored["terrain_matrix"] += 1

    # --- 参数 ---
    for item in snapshot.get("params", []):
        param = db.query(SysParam).filter(SysParam.key == item["key"]).one_or_none()
        if param is None:
            continue
        # 不回滚 rule.version.current，它由发布流程自己维护
        if param.key == "rule.version.current":
            continue
        param.value = str(item["value"])
        restored["params"] += 1

    db.commit()

    # 生成回滚后的新版本记录
    new_version = rule_service.next_version(db)
    record, changes = rule_service.publish_version(
        db,
        version=new_version,
        description=f"回滚到 {target.version}（{target.description or '无说明'}）",
        operator=actor.username,
    )

    append_audit(
        db,
        actor=actor,
        action="rule.rollback",
        target_type="rule",
        target_name=target.version,
        detail={
            "回滚到": target.version,
            "新版本": new_version,
            "恢复项": restored,
            "产生的变更数": len(changes),
        },
    )

    return {
        "rolled_back_to": target.version,
        "new_version": new_version,
        "restored": restored,
        "changes": changes,
        "message": (
            f"已回滚到 {target.version}，恢复 车辆类型 {restored['vehicle_types']} 条、"
            f"通行矩阵 {restored['terrain_matrix']} 格、参数 {restored['params']} 项；"
            f"并生成新版本 {new_version} 以保留回滚痕迹"
        ),
    }
