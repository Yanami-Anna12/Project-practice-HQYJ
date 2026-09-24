"""调度规则配置与版本治理服务。

「规则」在本项目里分散在几张强类型表上：
    md_vehicle_type       装载量区间、每车日趟次（硬约束 5、6、7）
    md_terrain_matrix     地形-车辆能力通行矩阵（硬约束 3）
    md_store_route        门店线路映射与优先级（硬约束 4）
    sys_param             调度行为开关（求解超时、重排上限、幂等键等）

本模块负责：
    1. 汇总展示当前生效的全部规则（rules_overview）
    2. 做规则冲突检测（conflict_check）—— 需求 2.2.7 明确要求
    3. 规则版本快照的发布、对比与回滚
"""

from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy.orm import Session

from app.models import (
    Route,
    RuleVersion,
    Store,
    StoreDemand,
    StoreRouteMapping,
    SysParam,
    Vehicle,
    VehicleTerrainCapability,
    VehicleType,
)
from app.services.solver import CAPABILITY_TERRAINS


def _vehicle_types(db: Session) -> list[dict]:
    vt_rows = db.query(VehicleType).order_by(VehicleType.id).all()
    counts: dict[str, int] = {}
    for v in db.query(Vehicle).filter(Vehicle.is_active.is_(True)).all():
        counts[v.vehicle_type_code] = counts.get(v.vehicle_type_code, 0) + 1
    return [
        {
            "code": t.code,
            "name": t.name,
            "min_load": t.min_load,
            "max_load": t.max_load,
            "trips_per_day": t.trips_per_day,
            "am_trips": t.am_trips,
            "pm_trips": t.pm_trips,
            "planned_count": t.planned_count,
            "vehicle_count": counts.get(t.code, 0),
            "is_active": t.is_active,
            "remark": t.remark,
        }
        for t in vt_rows
    ]


def _terrain_matrix(db: Session) -> list[dict]:
    rows = (
        db.query(VehicleTerrainCapability)
        .order_by(VehicleTerrainCapability.terrain_type, VehicleTerrainCapability.capability)
        .all()
    )
    return [
        {
            "terrain_type": r.terrain_type,
            "capability": r.capability,
            "allowed": r.allowed,
            "remark": r.remark,
        }
        for r in rows
    ]


def _params(db: Session) -> list[dict]:
    rows = db.query(SysParam).order_by(SysParam.group, SysParam.id).all()
    return [
        {
            "key": p.key,
            "name": p.name,
            "value": p.value,
            "type": p.type,
            "group": p.group,
            "is_active": p.is_active,
            "remark": p.remark,
        }
        for p in rows
    ]


def _route_strategy(db: Session) -> list[dict]:
    """门店线路映射的优先级与主线路设置。"""
    stores = {s.id: s for s in db.query(Store).all()}
    routes = {r.id: r for r in db.query(Route).all()}
    rows = (
        db.query(StoreRouteMapping)
        .order_by(StoreRouteMapping.store_id, StoreRouteMapping.priority)
        .all()
    )
    out = []
    for m in rows:
        s = stores.get(m.store_id)
        r = routes.get(m.route_id)
        if s is None or r is None:
            continue
        out.append(
            {
                "store_code": s.code,
                "store_name": s.name,
                "terrain_type": s.terrain_type,
                "delivery_window": s.delivery_window,
                "route_code": r.code,
                "route_name": r.name,
                "priority": m.priority,
                "is_primary": m.is_primary,
                "is_intersection": s.is_intersection,
            }
        )
    return out


def rules_overview(db: Session) -> dict:
    """当前生效的全部规则（供「调度策略与评分」页展示）。"""
    params = _params(db)
    return {
        "vehicle_types": _vehicle_types(db),
        "terrain_matrix": _terrain_matrix(db),
        "params": params,
        "route_strategy": _route_strategy(db),
        "current_version": next(
            (p["value"] for p in params if p["key"] == "rule.version.current"), "v1.0.0"
        ),
        # 硬约束清单：把求解器实际执行的约束原样列出，避免文档与代码脱节
        "hard_constraints": [
            {"code": "C1", "name": "门店货量必须全部满足", "source": "需求 一.5.3"},
            {"code": "C2", "name": "上午门店只能排上午趟，下午门店只能排下午趟", "source": "需求 一.5.2"},
            {"code": "C3", "name": "车辆地形能力必须覆盖门店地形", "source": "需求 一.5.7"},
            {"code": "C4", "name": "门店必须属于车辆可跑线路", "source": "需求 一.5.6"},
            {"code": "C5", "name": "发车必须达到最低装载量", "source": "需求 一.5.3"},
            {"code": "C6", "name": "不能超过最高装载量", "source": "需求 一.3"},
            {"code": "C7", "name": "四米二≤2趟、大包≤2趟、小包≤4趟", "source": "需求 一.3"},
        ],
        "soft_constraints": [
            {"code": "S1", "name": "优先保障大包、小包日出车次数", "source": "需求 一.5.1"},
            {"code": "S2", "name": "多种派车方案优先用四米二", "source": "需求 一.5.4"},
            {"code": "S3", "name": "不保障每天 28/3/9 台满勤，可动态调节", "source": "需求 一.5.5"},
        ],
        "score_function": {
            "formula": "score = 货量满足率×100 + 四米二使用率×0.30 + 装载率×0.40 "
                       "+ 趟次保障度×0.30 + 相对成本×(-0.20) + 缺口货量占比×(-50)",
            "note": "权重定义在 app/services/solver.py 的 SCORE_WEIGHTS，推荐方案按此评分选出",
        },
    }


def conflict_check(db: Session) -> list[dict]:
    """规则冲突检测（需求 2.2.7 明确要求）。

    检查的是「规则组合起来是否会导致无解或明显不合理」，
    而不是语法校验 —— 后者由各接口的 Pydantic 校验负责。
    """
    issues: list[dict] = []

    # 1. 某地形完全没有可通行的车辆能力 → 该地形的门店无法被覆盖
    matrix = _terrain_matrix(db)
    by_terrain: dict[str, list[dict]] = {}
    for m in matrix:
        by_terrain.setdefault(m["terrain_type"], []).append(m)
    for terrain, cells in by_terrain.items():
        if not any(c["allowed"] for c in cells):
            issues.append(
                {
                    "level": "error",
                    "type": "地形无可用能力",
                    "message": f"地形 {terrain} 的通行矩阵全部为禁止，该地形的门店无法被任何方案覆盖",
                    "suggestion": "至少允许一种车辆地形能力",
                }
            )

    # 2. 存在门店，但其地形没有任何启用车辆能进
    stores = db.query(Store).filter(Store.is_active.is_(True)).all()
    vehicles = db.query(Vehicle).filter(Vehicle.is_active.is_(True)).all()
    capabilities = {v.terrain_capability for v in vehicles}
    covered_terrains = set()
    for cap in capabilities:
        covered_terrains |= CAPABILITY_TERRAINS.get(cap, set())
    for s in stores:
        if s.terrain_type not in covered_terrains:
            issues.append(
                {
                    "level": "error",
                    "type": "门店地形无车可服务",
                    "message": f"门店 {s.code} {s.name} 地形为 {s.terrain_type}，"
                               f"但现有车辆的地形能力都不覆盖它",
                    "suggestion": "给车辆增加地形能力，或调整该门店的地形限制",
                }
            )

    # 3. 车辆类型规则自相矛盾
    for t in _vehicle_types(db):
        if t["min_load"] > t["max_load"]:
            issues.append(
                {
                    "level": "error",
                    "type": "装载量区间颠倒",
                    "message": f"{t['name']} 最低装载量 {t['min_load']} 大于最高 {t['max_load']}",
                    "suggestion": "修正装载量区间",
                }
            )
        if t["am_trips"] + t["pm_trips"] != t["trips_per_day"]:
            issues.append(
                {
                    "level": "warning",
                    "type": "趟次拆分不一致",
                    "message": f"{t['name']} 上午 {t['am_trips']} + 下午 {t['pm_trips']} "
                               f"≠ 每日 {t['trips_per_day']}",
                    "suggestion": "调整上午/下午趟次，使两者之和等于每日趟次",
                }
            )

    # 4. 单店货量超过所有车型上限 → 该店只能靠拆单，且运力可能不够
    if stores:
        max_cap = max((t["max_load"] for t in _vehicle_types(db)), default=0)
        for s in stores:
            demand = (
                db.query(StoreDemand)
                .filter(StoreDemand.store_id == s.id)
                .order_by(StoreDemand.schedule_date.desc())
                .first()
            )
            if demand and max_cap and float(demand.quantity) > max_cap:
                issues.append(
                    {
                        "level": "info",
                        "type": "需要拆单配送",
                        "message": f"门店 {s.code} {s.name} 最新货量 {float(demand.quantity):.0f} "
                                   f"超过单车最大装载量 {max_cap}，将被拆分到多个趟次",
                        "suggestion": "属正常情况；若希望一车一店，需提高车型上限或减小配送批量",
                    }
                )

    # 5. 没有可出勤车辆
    if not vehicles:
        issues.append(
            {
                "level": "error",
                "type": "无可用车辆",
                "message": "当前没有任何启用车辆，调度无法生成方案",
                "suggestion": "在「车辆档案」中启用车辆",
            }
        )

    # 6. 门店未映射线路
    unmapped = [
        s for s in stores if not db.query(StoreRouteMapping)
        .filter(StoreRouteMapping.store_id == s.id)
        .first()
    ]
    if unmapped:
        issues.append(
            {
                "level": "warning",
                "type": "门店未映射线路",
                "message": f"{len(unmapped)} 个门店未映射任何线路："
                           + "、".join(s.code for s in unmapped[:8]),
                "suggestion": "这些门店在调度中仍可被服务（线路无限的车辆可跑），但无法做线路匹配校验",
            }
        )

    return issues


# ---------------------------------------------------------------------------
# 规则版本
# ---------------------------------------------------------------------------
def build_snapshot(db: Session) -> dict:
    """生成当前规则的完整快照。"""
    return {
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "vehicle_types": _vehicle_types(db),
        "terrain_matrix": _terrain_matrix(db),
        "params": _params(db),
        "route_strategy": _route_strategy(db),
    }


def diff_snapshots(old: dict, new: dict) -> list[dict]:
    """对比两个快照，返回人类可读的变更列表。

    只对比「有业务含义」的部分：车辆类型规则、地形矩阵、参数。
    线路策略数据量大且变动频繁，只统计条数变化。
    """
    changes: list[dict] = []

    # --- 车辆类型 ---
    old_vt = {x["code"]: x for x in old.get("vehicle_types", [])}
    new_vt = {x["code"]: x for x in new.get("vehicle_types", [])}
    for code in sorted(set(old_vt) | set(new_vt)):
        a, b = old_vt.get(code), new_vt.get(code)
        if a is None:
            changes.append({"target": f"车辆类型 {code}", "field": "新增", "before": "—", "after": b.get("name", "")})
            continue
        if b is None:
            changes.append({"target": f"车辆类型 {code}", "field": "删除", "before": a.get("name", ""), "after": "—"})
            continue
        for field in ("min_load", "max_load", "trips_per_day", "am_trips", "pm_trips", "planned_count", "is_active"):
            if a.get(field) != b.get(field):
                changes.append(
                    {"target": f"{b.get('name', code)}", "field": field, "before": a.get(field), "after": b.get(field)}
                )

    # --- 地形矩阵 ---
    def matrix_key(x):
        return f"{x['terrain_type']}/{x['capability']}"

    old_m = {matrix_key(x): x for x in old.get("terrain_matrix", [])}
    new_m = {matrix_key(x): x for x in new.get("terrain_matrix", [])}
    for k in sorted(set(old_m) | set(new_m)):
        a, b = old_m.get(k), new_m.get(k)
        if a is None:
            changes.append({"target": f"通行矩阵 {k}", "field": "新增", "before": "—", "after": "允许" if b["allowed"] else "禁止"})
        elif b is None:
            changes.append({"target": f"通行矩阵 {k}", "field": "删除", "before": "允许" if a["allowed"] else "禁止", "after": "—"})
        elif a["allowed"] != b["allowed"]:
            changes.append(
                {
                    "target": f"通行矩阵 {k}",
                    "field": "allowed",
                    "before": "允许" if a["allowed"] else "禁止",
                    "after": "允许" if b["allowed"] else "禁止",
                }
            )

    # --- 参数 ---
    old_p = {x["key"]: x for x in old.get("params", [])}
    new_p = {x["key"]: x for x in new.get("params", [])}
    for k in sorted(set(old_p) | set(new_p)):
        a, b = old_p.get(k), new_p.get(k)
        if a is None:
            changes.append({"target": f"参数 {k}", "field": "新增", "before": "—", "after": b.get("value")})
        elif b is None:
            changes.append({"target": f"参数 {k}", "field": "删除", "before": a.get("value"), "after": "—"})
        elif a.get("value") != b.get("value"):
            changes.append({"target": f"参数 {k}", "field": "value", "before": a.get("value"), "after": b.get("value")})

    return changes


def publish_version(
    db: Session, *, version: str, description: str, operator: str
) -> tuple[RuleVersion, list[dict]]:
    """发布一个新版本：快照当前规则 + 与上一版对比。

    同时把 sys_param 里的 rule.version.current 更新为新版本号，
    这样后续调度任务的 rule_version 会自动记录新版本。
    """
    snapshot = build_snapshot(db)

    previous = (
        db.query(RuleVersion).order_by(RuleVersion.id.desc()).first()
    )
    changes = []
    if previous is not None:
        try:
            changes = diff_snapshots(json.loads(previous.snapshot_json), snapshot)
        except (ValueError, TypeError):
            changes = []

    summary = (
        "；".join(f"{c['target']}.{c['field']}: {c['before']} → {c['after']}" for c in changes[:20])
        or "与上一版无差异"
    )

    record = RuleVersion(
        version=version,
        description=description,
        snapshot_json=json.dumps(snapshot, ensure_ascii=False),
        change_summary=summary,
        is_active=True,
        published_by=operator,
    )
    db.add(record)

    # 更新当前版本参数
    param = db.query(SysParam).filter(SysParam.key == "rule.version.current").one_or_none()
    if param is not None:
        param.value = version
    else:
        db.add(
            SysParam(
                key="rule.version.current",
                name="当前规则版本",
                value=version,
                type="string",
                group="规则",
                remark="每次调度记录该版本",
                is_active=True,
            )
        )

    db.commit()
    db.refresh(record)
    return record, changes


def next_version(db: Session) -> str:
    """推导下一个版本号，形如 v1.0.1。"""
    latest = db.query(RuleVersion).order_by(RuleVersion.id.desc()).first()
    if latest is None:
        return "v1.0.0"
    raw = latest.version.lstrip("v")
    parts = raw.split(".")
    try:
        nums = [int(x) for x in parts]
    except ValueError:
        return "v1.0.0"
    while len(nums) < 3:
        nums.append(0)
    nums[2] += 1
    return "v" + ".".join(str(n) for n in nums)
