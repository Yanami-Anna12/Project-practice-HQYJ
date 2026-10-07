"""运维分析建议报告 Agent 服务 —— PDF 3.12 模块 11 + 4.6。

报告类型：日运营简报、周运维分析、月度深度报告、即时分析运营报告
报告内容：运行概览、充放电分析、设备状态诊断、异常检测与告警、根因分析、运维建议
输出层：PDF、Markdown、Platform View
交互能力：报告推送、追问下钻、历史对比
数据更新策略：日 T+1 02:00 / 周 周一 03:00 / 月 1 日 04:00 / 即时用户触发
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.knowledge import build_context
from app.ai.llm import llm_client
from app.ai.nodes import build_suggestions, gather_report_metrics
from app.ai.state import initial_state
from app.core.config import REPORT_DIR, settings
from app.core.enums import REPORT_TYPE_LABEL, MessageType, ReportType
from app.core.errors import BizError, NotFoundError
from app.core.utils import gen_no, month_range, safe_rate, to_json_safe, week_range
from app.models import (
    AIReport,
    AIReportFollowUp,
    StatisticsDaily,
    User,
)

logger = logging.getLogger("app.ai.report")

REPORT_TITLES = {
    ReportType.DAILY.value: "日运营简报",
    ReportType.WEEKLY.value: "周运维分析报告",
    ReportType.MONTHLY.value: "月度深度报告",
    ReportType.INSTANT.value: "即时分析运营报告",
}

REPORT_SECTIONS = [
    "运行概览",
    "充放电分析",
    "设备状态诊断",
    "异常检测与告警",
    "根因分析",
    "运维建议",
]


def default_period(report_type: str, anchor: date | None = None) -> tuple[date, date]:
    """按报告类型计算默认统计周期（PDF 3.12 数据更新策略）。"""
    anchor = anchor or date.today()
    if report_type == ReportType.DAILY.value:
        target = anchor - timedelta(days=1)  # T+1
        return target, target
    if report_type == ReportType.WEEKLY.value:
        start, end = week_range(anchor - timedelta(days=7))
        return start, end
    if report_type == ReportType.MONTHLY.value:
        first = anchor.replace(day=1)
        prev_last = first - timedelta(days=1)
        return month_range(prev_last)
    return anchor, anchor


async def _period_metrics(
    db: AsyncSession, start: date, end: date, project_id: str | None
) -> dict:
    """统计周期内的 SQL 聚合指标。"""
    from app.models import ChargingPile, FaultReport, InspectionRecord, Station, WorkOrder

    start_dt = datetime.combine(start, datetime.min.time())
    end_dt = datetime.combine(end, datetime.max.time())

    def _w(stmt):
        stmt = stmt.where(WorkOrder.created_at >= start_dt, WorkOrder.created_at <= end_dt)
        if project_id:
            stmt = stmt.where(WorkOrder.project_id == project_id)
        return stmt

    total = int((await db.execute(_w(select(func.count(WorkOrder.id))))).scalar() or 0)
    done = int(
        (
            await db.execute(
                _w(
                    select(func.count(WorkOrder.id)).where(WorkOrder.status == "已完成")
                )
            )
        ).scalar()
        or 0
    )
    pending = int(
        (
            await db.execute(
                _w(
                    select(func.count(WorkOrder.id)).where(
                        WorkOrder.status.in_(["待接单", "待完成", "已退回"])
                    )
                )
            )
        ).scalar()
        or 0
    )
    overdue = int(
        (
            await db.execute(
                _w(select(func.count(WorkOrder.id)).where(WorkOrder.time_status == "逾期"))
            )
        ).scalar()
        or 0
    )
    type_rows = (
        await db.execute(
            _w(select(WorkOrder.order_type, func.count(WorkOrder.id)).group_by(WorkOrder.order_type))
        )
    ).all()

    def _f(stmt):
        stmt = stmt.where(FaultReport.created_at >= start_dt, FaultReport.created_at <= end_dt)
        if project_id:
            stmt = stmt.where(FaultReport.project_id == project_id)
        return stmt

    fault_total = int((await db.execute(_f(select(func.count(FaultReport.id))))).scalar() or 0)
    fault_critical = int(
        (
            await db.execute(
                _f(select(func.count(FaultReport.id)).where(FaultReport.fault_level == "危急"))
            )
        ).scalar()
        or 0
    )
    fault_pending = int(
        (
            await db.execute(
                _f(select(func.count(FaultReport.id)).where(FaultReport.status == "待核查"))
            )
        ).scalar()
        or 0
    )

    def _i(stmt):
        stmt = stmt.where(
            InspectionRecord.created_at >= start_dt, InspectionRecord.created_at <= end_dt
        )
        return stmt

    insp_total = int((await db.execute(_i(select(func.count(InspectionRecord.id))))).scalar() or 0)
    insp_abnormal = int(
        (
            await db.execute(
                _i(
                    select(func.count(InspectionRecord.id)).where(
                        InspectionRecord.abnormal_count > 0
                    )
                )
            )
        ).scalar()
        or 0
    )

    station_total = int((await db.execute(select(func.count(Station.id)))).scalar() or 0)
    pile_total = int((await db.execute(select(func.count(ChargingPile.id)))).scalar() or 0)
    pile_offline = int(
        (
            await db.execute(
                select(func.count(ChargingPile.id)).where(ChargingPile.online.is_(False))
            )
        ).scalar()
        or 0
    )

    return {
        "周期": f"{start} ~ {end}",
        "站点总数": station_total,
        "充电桩总数": pile_total,
        "离线充电桩": pile_offline,
        "工单总数": total,
        "待办工单": pending,
        "已办工单": done,
        "逾期工单": overdue,
        "完成率(%)": safe_rate(done, total),
        "逾期率(%)": safe_rate(overdue, total),
        "工单类型分布": [{"name": t or "未分类", "value": int(c)} for t, c in type_rows],
        "故障总数": fault_total,
        "危急故障": fault_critical,
        "待核查故障": fault_pending,
        "巡检记录数": insp_total,
        "巡检异常记录": insp_abnormal,
        "巡检异常率(%)": safe_rate(insp_abnormal, insp_total),
    }


async def generate_report(
    db: AsyncSession,
    *,
    report_type: str,
    project_id: str | None = None,
    station_id: str | None = None,
    period_start: date | None = None,
    period_end: date | None = None,
    use_llm: bool = True,
    user: User | None = None,
) -> AIReport:
    """生成一份运维分析报告（PDF 3.12 / 4.6）。"""
    if hasattr(report_type, "value"):
        report_type = report_type.value
    if report_type not in {e.value for e in ReportType}:
        raise BizError(f"非法报告类型：{report_type}")

    if period_start is None or period_end is None:
        period_start, period_end = default_period(report_type)
    if period_end < period_start:
        raise BizError("统计周期结束日期不能早于开始日期")

    metrics = await _period_metrics(db, period_start, period_end, project_id)
    label = REPORT_TITLES.get(report_type, "运维分析报告")
    title = f"{label} · {period_start} ~ {period_end}"

    state = initial_state(
        project_id=project_id or "",
        schedule_date=period_end.isoformat(),
        llm_used=False,
        degraded=False,
    )
    state["report_data"] = {"metrics": metrics}

    # 巡检异常与故障诊断数据（复用 Agent 节点能力）
    from app.ai.nodes import fault_diagnosis, inspection_processing

    insp_result = await inspection_processing(state)
    state.update(insp_result)  # type: ignore[arg-type]
    fault_result = await fault_diagnosis(state)
    state.update(fault_result)  # type: ignore[arg-type]

    from app.ai.nodes import render_report_markdown

    markdown = render_report_markdown(metrics, state, report_type, title)
    suggestions = build_suggestions(metrics, state)

    llm_used = False
    degraded = False
    llm_text = None

    if use_llm and llm_client.available:
        async with AsyncSessionLocalSafe() as kb_db:
            context, refs = await build_context(
                kb_db,
                "充电桩运维 异常处置 SOP 故障根因",
                top_k=4,
                user=user,
            )
        prompt = (
            f"报告类型：{label}\n统计周期：{period_start} ~ {period_end}\n\n"
            f"【确定性统计指标】\n{to_json_safe(metrics)}\n\n"
            f"【巡检异常】\n{to_json_safe((state.get('report_data') or {}).get('inspection_anomalies') or [])[:3000]}\n\n"
            f"【故障根因分析】\n{to_json_safe((state.get('report_data') or {}).get('fault_diagnoses') or [])[:3000]}\n\n"
            f"【知识库参考】\n{context[:3000] or '（无匹配知识条目）'}\n\n"
            "请输出运营分析解读，包含：运行概览、充放电分析、设备状态诊断、"
            "异常检测与告警、根因分析、运维建议六个部分，使用 Markdown 小节标题。"
            "运维建议需给出责任角色与建议时限。不得编造指标中不存在的数据。"
        )
        result = await llm_client.chat(
            "你是充电桩与储能电站运维分析专家，负责把确定性统计结果解读为可执行的运维结论。",
            prompt,
            max_tokens=2600,
        )
        if result.used_llm:
            llm_used = True
            llm_text = result.text
            markdown += f"\n\n## 七、智能分析解读（LLM）\n\n{result.text}\n"
        else:
            degraded = True
            markdown += (
                f"\n\n## 七、智能分析解读\n\n> LLM 调用未成功（{result.error}），"
                "已使用确定性规则引擎输出解读与建议。\n"
            )
    else:
        degraded = True
        markdown += (
            "\n\n## 七、智能分析解读\n\n> 未配置 LLM_API_KEY，"
            "已使用确定性规则引擎输出解读与建议。\n"
        )

    report_no = gen_no("RP")
    md_path = REPORT_DIR / f"{report_no}.md"
    md_path.write_text(markdown, encoding="utf-8")

    html_path = REPORT_DIR / f"{report_no}.html"
    html_path.write_text(render_report_html(title, markdown, metrics), encoding="utf-8")

    pdf_path = REPORT_DIR / f"{report_no}.pdf"
    pdf_ok = render_report_pdf(pdf_path, title, metrics, suggestions, markdown)

    report = AIReport(
        report_no=report_no,
        report_type=report_type,
        title=title,
        project_id=project_id,
        station_id=station_id,
        period_start=period_start,
        period_end=period_end,
        content=to_json_safe(
            {
                "metrics": metrics,
                "sections": REPORT_SECTIONS,
                "suggestions": suggestions,
                "llm_sections": {"analysis": llm_text} if llm_text else {},
                "period": {"start": period_start.isoformat(), "end": period_end.isoformat()},
            }
        ),
        markdown=markdown,
        summary=markdown[:400],
        suggestions=to_json_safe(suggestions),
        md_url=str(md_path),
        html_url=str(html_path),
        file_url=str(pdf_path) if pdf_ok else None,
        status="generated",
        llm_used=llm_used,
        degraded=degraded,
        generated_by=user.id if user else None,
    )
    db.add(report)
    await db.commit()
    await db.refresh(report)
    return report


class AsyncSessionLocalSafe:
    """轻量会话上下文，避免在服务内部 import 循环。"""

    async def __aenter__(self):
        from app.core.database import AsyncSessionLocal

        self._ctx = AsyncSessionLocal()
        self._db = await self._ctx.__aenter__()
        return self._db

    async def __aexit__(self, exc_type, exc, tb):
        return await self._ctx.__aexit__(exc_type, exc, tb)


# ---------------------------------------------------------------- 输出层


def render_report_html(title: str, markdown: str, metrics: dict) -> str:
    """Platform View / HTML 输出（PDF 3.12 报告输出层）。"""
    body = markdown_to_html(markdown)
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  :root {{ color-scheme: light; }}
  body {{ font-family: "Microsoft YaHei", "PingFang SC", system-ui, sans-serif;
         margin: 0; background: #f5f7fa; color: #1f2329; }}
  .wrap {{ max-width: 960px; margin: 0 auto; padding: 32px 24px 64px; }}
  .card {{ background: #fff; border-radius: 12px; padding: 32px 36px;
           box-shadow: 0 2px 12px rgba(0,0,0,.06); }}
  h1 {{ font-size: 26px; margin: 0 0 8px; color: #1f4e79; }}
  h2 {{ font-size: 19px; margin: 28px 0 12px; padding-left: 10px;
        border-left: 4px solid #2f6fb5; color: #1f4e79; }}
  h3 {{ font-size: 16px; margin: 20px 0 8px; color: #2f6fb5; }}
  table {{ border-collapse: collapse; width: 100%; margin: 12px 0; }}
  th, td {{ border: 1px solid #e5e8ef; padding: 8px 12px; text-align: left; font-size: 14px; }}
  th {{ background: #eef3fa; }}
  blockquote {{ margin: 12px 0; padding: 10px 14px; background: #fff8e6;
                border-left: 4px solid #f0b429; color: #6b5316; border-radius: 4px; }}
  li {{ line-height: 1.9; font-size: 14px; }}
  code {{ background: #f2f4f7; padding: 2px 6px; border-radius: 4px; }}
  hr {{ border: none; border-top: 1px solid #e5e8ef; margin: 28px 0; }}
  .meta {{ color: #646a73; font-size: 13px; }}
</style>
</head>
<body>
<div class="wrap">
  <div class="card">
    {body}
  </div>
</div>
</body>
</html>
"""


def markdown_to_html(markdown: str) -> str:
    """极简 Markdown -> HTML（覆盖报告用到的语法）。"""
    html: list[str] = []
    in_table = False
    in_ul = False

    def close_lists():
        nonlocal in_table, in_ul
        if in_table:
            html.append("</table>")
            in_table = False
        if in_ul:
            html.append("</ul>")
            in_ul = False

    for raw in markdown.splitlines():
        line = raw.rstrip()
        stripped = line.strip()

        if not stripped:
            close_lists()
            continue

        if stripped.startswith("|") and stripped.endswith("|"):
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
                continue
            if not in_table:
                close_lists()
                html.append("<table>")
                in_table = True
                html.append(
                    "<tr>" + "".join(f"<th>{inline(c)}</th>" for c in cells) + "</tr>"
                )
            else:
                html.append(
                    "<tr>" + "".join(f"<td>{inline(c)}</td>" for c in cells) + "</tr>"
                )
            continue

        close_lists()

        if stripped == "---":
            html.append("<hr>")
        elif stripped.startswith("#### "):
            html.append(f"<h4>{inline(stripped[5:])}</h4>")
        elif stripped.startswith("### "):
            html.append(f"<h3>{inline(stripped[4:])}</h3>")
        elif stripped.startswith("## "):
            html.append(f"<h2>{inline(stripped[3:])}</h2>")
        elif stripped.startswith("# "):
            html.append(f"<h1>{inline(stripped[2:])}</h1>")
        elif stripped.startswith("> "):
            html.append(f"<blockquote>{inline(stripped[2:])}</blockquote>")
        elif re.match(r"^[-*] ", stripped):
            if not in_ul:
                html.append("<ul>")
                in_ul = True
            html.append(f"<li>{inline(stripped[2:])}</li>")
        elif re.match(r"^\d+\.\s", stripped):
            html.append(f"<p>{inline(stripped)}</p>")
        elif stripped.startswith("- "):
            html.append(f"<li>{inline(stripped[2:])}</li>")
        else:
            html.append(f"<p>{inline(stripped)}</p>")

    close_lists()
    return "\n".join(html)


def inline(text: str) -> str:
    text = (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"`(.+?)`", r"<code>\1</code>", text)
    return text


def render_report_pdf(
    path: Path, title: str, metrics: dict, suggestions: list[dict], markdown: str
) -> bool:
    """PDF 输出（PDF 3.12 报告输出层；使用 reportlab，避免 GTK 依赖）。"""
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont
        from reportlab.platypus import (
            PageBreak,
            Paragraph,
            SimpleDocTemplate,
            Spacer,
            Table,
            TableStyle,
        )
    except Exception as exc:  # pragma: no cover
        logger.warning("reportlab 不可用：%s", exc)
        return False

    font_name = "Helvetica"
    try:
        pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
        font_name = "STSong-Light"
    except Exception:
        pass

    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Heading1"], fontName=font_name, fontSize=18, leading=26)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontName=font_name, fontSize=14, leading=22)
    body = ParagraphStyle("body", parent=styles["BodyText"], fontName=font_name, fontSize=10.5, leading=17)
    small = ParagraphStyle("small", parent=body, fontSize=9, textColor=colors.HexColor("#666666"))

    doc = SimpleDocTemplate(
        str(path),
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=title,
    )

    flow = [Paragraph(title, h1), Spacer(1, 6)]
    flow.append(
        Paragraph(
            f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}　|　"
            f"统计周期：{metrics.get('周期', '-')}",
            small,
        )
    )
    flow.append(Spacer(1, 12))

    flow.append(Paragraph("一、核心指标", h2))
    rows = [["指标", "数值"]]
    for key in (
        "工单总数",
        "已办工单",
        "逾期工单",
        "完成率(%)",
        "逾期率(%)",
        "故障总数",
        "待核查故障",
        "危急故障",
        "巡检记录数",
        "巡检异常记录",
        "巡检异常率(%)",
        "站点总数",
        "充电桩总数",
        "离线充电桩",
    ):
        rows.append([key, str(metrics.get(key, "-"))])
    table = Table(rows, colWidths=[60 * mm, 60 * mm])
    table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), font_name),
                ("FONTSIZE", (0, 0), (-1, -1), 9.5),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EEF3FA")),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#D9D9D9")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    flow.append(table)
    flow.append(Spacer(1, 14))

    flow.append(Paragraph("二、运维建议", h2))
    for i, s in enumerate(suggestions, 1):
        flow.append(
            Paragraph(
                f"{i}. <b>{s.get('title')}</b>（优先级：{s.get('priority')}）：{s.get('detail')}",
                body,
            )
        )
        flow.append(Spacer(1, 4))

    flow.append(PageBreak())
    flow.append(Paragraph("三、报告全文", h2))
    for line in markdown.splitlines():
        stripped = line.strip()
        if not stripped:
            flow.append(Spacer(1, 4))
            continue
        if stripped.startswith("### "):
            flow.append(Paragraph(inline(stripped[4:]), h2))
        elif stripped.startswith("## "):
            flow.append(Paragraph(inline(stripped[3:]), h2))
        elif stripped.startswith("# "):
            flow.append(Paragraph(inline(stripped[2:]), h1))
        elif stripped.startswith("|"):
            continue  # 表格已在第一节呈现
        elif stripped.startswith("> "):
            flow.append(Paragraph(inline(stripped[2:]), small))
        else:
            flow.append(Paragraph(inline(stripped), body))

    try:
        doc.build(flow)
        return True
    except Exception as exc:  # pragma: no cover
        logger.warning("PDF 生成失败：%s", exc)
        return False


# ---------------------------------------------------------------- 追问下钻 / 对比


async def follow_up(
    db: AsyncSession,
    *,
    report_id: str,
    question: str,
    use_llm: bool = True,
    user: User | None = None,
) -> AIReportFollowUp:
    """报告追问下钻（PDF 3.12 交互能力）。"""
    report = await db.get(AIReport, report_id)
    if report is None:
        raise NotFoundError("报告不存在")

    metrics = (report.content or {}).get("metrics") or {}
    answer: str
    refs: list[dict] = []

    if use_llm and llm_client.available:
        async with AsyncSessionLocalSafe() as kb_db:
            context, refs = await build_context(kb_db, question, top_k=4, user=user)
        prompt = (
            f"【报告标题】{report.title}\n"
            f"【统计周期】{report.period_start} ~ {report.period_end}\n\n"
            f"【报告指标数据】\n{to_json_safe(metrics)}\n\n"
            f"【报告正文节选】\n{(report.markdown or '')[:6000]}\n\n"
            f"【知识库参考】\n{context[:2500] or '（无匹配知识条目）'}\n\n"
            f"【用户追问】{question}\n\n"
            "请基于以上报告数据回答追问。若数据不足以回答，请明确说明缺失哪些字段，"
            "不要编造数字。使用简体中文，必要时用列表。"
        )
        result = await llm_client.chat(
            "你是充电桩运维报告解读助手，只依据给定报告数据与知识库回答，不臆造数据。",
            prompt,
            max_tokens=1200,
        )
        if result.used_llm:
            answer = result.text
        else:
            answer = _deterministic_follow_up(metrics, question, result.error)
    else:
        answer = _deterministic_follow_up(metrics, question, "未配置 LLM_API_KEY")

    follow = AIReportFollowUp(
        report_id=report_id,
        question=question,
        answer=answer,
        refs=to_json_safe(refs),
        llm_used=bool(llm_client.available and use_llm),
        asker_id=user.id if user else None,
    )
    db.add(follow)
    await db.commit()
    await db.refresh(follow)
    return follow


def _deterministic_follow_up(metrics: dict, question: str, reason: str | None) -> str:
    """LLM 不可用时的确定性追问回答（关键词命中指标）。"""
    hints: list[str] = []
    mapping = {
        "逾期": ("逾期工单", "逾期率(%)"),
        "完成": ("已办工单", "完成率(%)"),
        "工单": ("工单总数", "已办工单", "逾期工单"),
        "故障": ("故障总数", "待核查故障", "危急故障"),
        "危急": ("危急故障",),
        "巡检": ("巡检记录数", "巡检异常记录", "巡检异常率(%)"),
        "桩": ("充电桩总数", "离线充电桩"),
        "站点": ("站点总数",),
        "离线": ("离线充电桩",),
    }
    for keyword, keys in mapping.items():
        if keyword in question:
            for k in keys:
                if k in metrics:
                    hints.append(f"- {k}：{metrics[k]}")

    head = f"（当前未启用 LLM 深度问答{('：' + reason) if reason else ''}，以下为报告指标直接答复）"
    if hints:
        return head + "\n\n根据本报告统计周期内的数据：\n" + "\n".join(dict.fromkeys(hints))
    return (
        head
        + "\n\n本报告核心指标：\n"
        + "\n".join(f"- {k}：{v}" for k, v in metrics.items() if not isinstance(v, (list, dict)))
    )


async def compare_reports(
    db: AsyncSession, *, report_type: str, limit: int = 6
) -> dict:
    """历史对比（PDF 3.12 历史对比）。"""
    rows = (
        await db.execute(
            select(AIReport)
            .where(AIReport.report_type == report_type)
            .order_by(AIReport.period_start.desc())
            .limit(limit)
        )
    ).scalars().all()
    if not rows:
        raise BizError("暂无历史报告可供对比")

    series: list[dict] = []
    for report in rows:
        metrics = (report.content or {}).get("metrics") or {}
        series.append(
            {
                "report_id": report.id,
                "title": report.title,
                "period": f"{report.period_start} ~ {report.period_end}",
                "period_start": report.period_start.isoformat() if report.period_start else None,
                "工单总数": metrics.get("工单总数", 0),
                "已办工单": metrics.get("已办工单", 0),
                "逾期工单": metrics.get("逾期工单", 0),
                "完成率(%)": metrics.get("完成率(%)", 0),
                "逾期率(%)": metrics.get("逾期率(%)", 0),
                "故障总数": metrics.get("故障总数", 0),
                "巡检异常记录": metrics.get("巡检异常记录", 0),
            }
        )

    series.reverse()  # 时间升序，便于前端画趋势
    latest, previous = series[-1], (series[-2] if len(series) > 1 else None)
    deltas: dict[str, dict] = {}
    if previous:
        for key in ("工单总数", "逾期工单", "完成率(%)", "逾期率(%)", "故障总数", "巡检异常记录"):
            cur = latest.get(key) or 0
            prev = previous.get(key) or 0
            deltas[key] = {
                "current": cur,
                "previous": prev,
                "delta": round(float(cur) - float(prev), 2),
                "delta_rate": safe_rate(float(cur) - float(prev), prev) if prev else None,
            }

    return {
        "report_type": report_type,
        "series": series,
        "latest": latest,
        "previous": previous,
        "deltas": deltas,
    }


async def push_report(
    db: AsyncSession,
    *,
    report: AIReport,
    user_ids: list[str],
    channels: list[str] | None = None,
) -> dict:
    """报告推送（PDF 3.12 报告推送 + 7.3 消息推送集成）。"""
    channels = channels or ["站内信"]
    from app.services.message import create_message, dispatch

    sent = 0
    for uid in user_ids:
        receiver = await db.get(User, uid)
        if receiver is None:
            continue
        message = await create_message(
            db,
            receiver_id=uid,
            msg_type=MessageType.REPORT_READY.value,
            title=f"运维报告已生成：{report.title}",
            content=(report.summary or "")[:300],
            report_id=report.id,
            link=f"/reports/{report.id}",
            commit=False,
        )
        await db.flush()
        await dispatch(db, message=message, receiver=receiver, channels=channels)
        sent += 1

    report.pushed_channels = channels
    await db.commit()
    return {"pushed": sent, "channels": channels, "report_id": report.id}


async def list_reports(
    db: AsyncSession,
    *,
    report_type: str | None = None,
    project_id: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[AIReport], int]:
    conditions = []
    if report_type:
        conditions.append(AIReport.report_type == report_type)
    if project_id:
        conditions.append(AIReport.project_id == project_id)

    base = select(AIReport)
    count_stmt = select(func.count(AIReport.id))
    for cond in conditions:
        base = base.where(cond)
        count_stmt = count_stmt.where(cond)

    total = int((await db.execute(count_stmt)).scalar() or 0)
    stmt = base.order_by(AIReport.period_start.desc(), AIReport.created_at.desc()).limit(limit).offset(offset)
    return list((await db.execute(stmt)).scalars().all()), total


async def get_report(db: AsyncSession, report_id: str) -> AIReport:
    report = await db.get(AIReport, report_id)
    if report is None:
        raise NotFoundError("报告不存在")
    return report


async def report_statistics_trend(
    db: AsyncSession, *, days: int = 30, project_id: str | None = None
) -> dict:
    """统计日报趋势（PDF 6.1 statistics_daily）。"""
    start = date.today() - timedelta(days=days)
    stmt = (
        select(StatisticsDaily)
        .where(StatisticsDaily.stat_date >= start, StatisticsDaily.station_id.is_(None))
        .order_by(StatisticsDaily.stat_date.asc())
    )
    if project_id:
        stmt = stmt.where(StatisticsDaily.project_id == project_id)
    rows = (await db.execute(stmt)).scalars().all()
    return {
        "days": days,
        "series": [
            {
                "date": r.stat_date.isoformat(),
                "order_total": r.order_total,
                "order_done": r.order_done,
                "order_overdue": r.order_overdue,
                "completion_rate": r.completion_rate,
                "overdue_rate": r.overdue_rate,
                "fault_total": r.fault_total,
                "inspection_abnormal": r.inspection_abnormal,
            }
            for r in rows
        ],
    }
