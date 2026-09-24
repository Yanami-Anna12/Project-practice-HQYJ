# -*- coding: utf-8 -*-
"""诊断报表服务的方案选取逻辑。"""

from __future__ import annotations

from datetime import date

from sqlalchemy import func

from app.database import SessionLocal
from app.models import SchedulingPlan, SchedulingPlanDetail, SchedulingTask
from app.services.reports import _plans_of, _selected_plans

db = SessionLocal()
try:
    dates = [
        r[0]
        for r in db.query(SchedulingTask.schedule_date)
        .distinct()
        .order_by(SchedulingTask.schedule_date.desc())
        .all()
    ]
    print('有数据的日期：', [str(d) for d in dates])

    for d in dates[:3]:
        plans = _plans_of(db, d)
        selected = _selected_plans(db, d)
        tasks = db.query(SchedulingTask).filter(SchedulingTask.schedule_date == d).all()
        print('=' * 70)
        print(f'日期 {d}')
        print(f'  任务 {len(tasks)} 个：' + ', '.join(f'{t.code}({t.status})' for t in tasks))
        print(f'  _plans_of 返回 {len(plans)} 套方案')
        for p in plans:
            print(f'     task={p.task_id} {p.plan_code} rec={p.is_recommended} score={p.score} trips={p.trip_count}')
        print(f'  _selected_plans 返回 {len(selected)} 套：')
        for p in selected:
            detail_count = (
                db.query(func.count(SchedulingPlanDetail.id))
                .filter(SchedulingPlanDetail.plan_id == p.id)
                .scalar()
            )
            trip_count = (
                db.query(func.count(func.distinct(func.concat(
                    SchedulingPlanDetail.vehicle_id, '-', SchedulingPlanDetail.trip_no
                ))))
                .filter(SchedulingPlanDetail.plan_id == p.id)
                .scalar()
            )
            print(f'     task={p.task_id} {p.plan_code} 明细 {detail_count} 条 / 趟次 {trip_count}')

        # 实际参与统计的明细
        detail_ids = [p.id for p in selected]
        total = (
            db.query(func.count(SchedulingPlanDetail.id))
            .filter(SchedulingPlanDetail.plan_id.in_(detail_ids))
            .scalar()
        )
        print(f'  参与统计的明细总数：{total}')
finally:
    db.close()
