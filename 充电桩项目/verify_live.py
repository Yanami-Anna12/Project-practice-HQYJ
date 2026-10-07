"""最终联调验证：对运行中的真实服务做端到端检查。

默认检查充电桩项目（后端 8010 + 前端 5185），可用环境变量覆盖：
    API_PORT=8010  WEB_PORT=5185  python verify_live.py
"""

from __future__ import annotations

import os
import sys
import time

import httpx

API = f"http://127.0.0.1:{os.environ.get('API_PORT', '8010')}"
WEB = f"http://127.0.0.1:{os.environ.get('WEB_PORT', '5185')}"

PASS = 0
FAIL = 0
FAILURES: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [PASS] {name}", flush=True)
    else:
        FAIL += 1
        FAILURES.append(f"{name} :: {detail}")
        print(f"  [FAIL] {name}  {detail}", flush=True)


def _make_png() -> bytes:
    """生成结构合法的 1x1 PNG（含正确 CRC），用于真实上传验证。"""
    import struct
    import zlib

    def chunk(ctype: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + ctype
            + data
            + struct.pack(">I", zlib.crc32(ctype + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(b"\x00\xff\xff\xff"))
        + chunk(b"IEND", b"")
    )


def main() -> int:
    print("=" * 78)
    print("  最终联调验证：充电桩运维管理 AI Agent 平台")
    print(f"  后端 {API}　前端 {WEB}")
    print("=" * 78)

    c = httpx.Client(timeout=180.0)

    # ---------------- 前端 ----------------
    print("\n[1] 前端静态资源")
    r = c.get(WEB)
    check("前端首页 200", r.status_code == 200, str(r.status_code))
    check("返回 HTML 且含挂载点", "id=\"app\"" in r.text and "<script" in r.text, r.text[:120])
    r2 = c.get(f"{WEB}/src/main.js")
    check("Vite 提供模块入口", r2.status_code == 200, str(r2.status_code))

    # ---------------- 后端健康 ----------------
    print("\n[2] 后端健康与文档")
    r = c.get(f"{API}/health")
    body = r.json()
    check(
        "健康检查（数据库连通）",
        r.status_code == 200 and body["data"]["database"]["ok"],
        str(body)[:180],
    )
    r = c.get(f"{API}/openapi.json")
    paths = r.json().get("paths", {})
    check(f"OpenAPI 接口数 {len(paths)}", len(paths) >= 95, str(len(paths)))
    r = c.get(f"{API}/docs")
    check("Swagger 文档可用", r.status_code == 200, str(r.status_code))
    r = c.get(f"{API}/metrics")
    check(
        "Prometheus 指标输出",
        r.status_code == 200 and "maintenance_work_order_total" in r.text,
        r.text[:120],
    )

    # ---------------- 登录 ----------------
    print("\n[3] 认证")
    r = c.post(f"{API}/api/v1/auth/login", json={"username": "admin", "password": "admin123"})
    check("管理员登录", r.status_code == 200, r.text[:160])
    token = r.json()["data"]["access_token"]
    H = {"Authorization": f"Bearer {token}"}
    r = c.get(f"{API}/api/v1/auth/profile", headers=H)
    perms = r.json()["data"]["permissions"]
    check(f"权限菜单 {len(perms)} 项", len(perms) > 20, str(len(perms)))

    # ---------------- 核心业务数据 ----------------
    print("\n[4] 核心业务数据")
    checks = [
        ("工单首页", "/api/v1/work-orders/home", "total"),
        ("工单列表", "/api/v1/work-orders?page_size=5", None),
        ("作业任务", "/api/v1/work-orders/subtasks/mine?scope_all=true&page_size=5", None),
        ("巡检模板", "/api/v1/work-orders/inspections/template?order_type=巡视", "template"),
        ("故障首页", "/api/v1/faults/home", "total"),
        ("故障列表", "/api/v1/faults?page_size=5", None),
        ("台账查询", "/api/v1/admin/ledger?page_size=5", None),
        ("站点列表", "/api/v1/admin/stations?page_size=5", None),
        ("充电桩汇总", "/api/v1/admin/piles/status-summary", "gun_total"),
        ("统计看板", "/api/v1/statistics/dashboard", "work_order"),
        ("统计趋势", "/api/v1/statistics/trend?days=30", "series"),
        ("消息列表", "/api/v1/messages", "unread_count"),
        ("系统参数", "/api/v1/admin/configs", None),
        ("生效规则", "/api/v1/admin/rules/active", "hard_constraints"),
        ("操作日志", "/api/v1/admin/logs/operations", None),
    ]
    for name, path, key in checks:
        r = c.get(f"{API}{path}", headers=H)
        ok = r.status_code == 200 and r.json().get("code") == 0
        if ok and key:
            ok = r.json().get("data", {}).get(key) is not None
        check(name, ok, f"{r.status_code} {r.text[:110]}")

    # ---------------- AI Agent ----------------
    print("\n[5] AI Agent 能力")
    r = c.get(f"{API}/api/v1/ai/health", headers=H)
    h = r.json()["data"]
    print(
        f"         LLM 状态：{h.get('status')} | 模型：{h.get('model')} | "
        f"知识库：{h.get('knowledge_docs')} 条"
    )
    check("AI 健康检查", r.status_code == 200 and "status" in h, str(h)[:160])

    r = c.get(f"{API}/api/v1/ai/graph", headers=H)
    check(
        "LangGraph 工作流（11 节点）",
        len(r.json()["data"]["normal_flow"]) == 11,
        str(len(r.json()["data"]["normal_flow"])),
    )

    r = c.get(f"{API}/api/v1/ai/agent/center", headers=H)
    check("8 类 Agent 概览", len(r.json()["data"]["agents"]) == 8, str(r.json()["data"]["agents"])[:120])

    r = c.post(
        f"{API}/api/v1/ai/knowledge/ask",
        headers=H,
        json={"question": "绝缘故障现场怎么处置？", "top_k": 3},
    )
    refs = r.json()["data"]["references"]
    check(f"RAG 检索命中 {len(refs)} 条", len(refs) > 0, str(refs)[:160])
    if refs:
        print("         命中：" + "、".join(f"{x['title'][:20]}({x['score']})" for x in refs[:3]))

    r = c.post(
        f"{API}/api/v1/ai/fault/diagnose",
        headers=H,
        json={"fault_type": "功率模块故障", "description": "功率仅 30kW，报 E05 故障码"},
    )
    d = r.json()["data"]
    check(
        "智能故障诊断（类别+根因+措施）",
        d["diagnosis"].get("matched_category") == "功率"
        and len(d["diagnosis"].get("possible_causes", [])) > 0,
        str(d)[:160],
    )
    print(f"         LLM 增强：{d.get('llm_used')}")

    # ---------------- 智能工单调度 + 人工确认（核心闭环）----------------
    print("\n[6] 智能工单调度闭环（多方案 → 人工确认 → 下发）")
    projects = c.get(f"{API}/api/v1/admin/projects", headers=H).json()["data"]
    pid = projects[0]["id"]

    r = c.post(
        f"{API}/api/v1/ai/work-order/generate",
        headers=H,
        json={
            "project_id": pid,
            "order_type": "巡视",
            "inspect_frequency": "月",
            "inspect_cycle": 1,
            "auto_start": True,
            "explain_with_llm": False,
        },
    )
    check("创建调度任务", r.status_code == 200, r.text[:160])
    task_id = r.json()["data"]["task_id"]

    state = {}
    for _ in range(120):
        r = c.get(f"{API}/api/v1/ai/agent/tasks/{task_id}", headers=H)
        state = r.json().get("data", {})
        st = state.get("task", {}).get("status")
        if st in ("waiting_confirmation", "failed", "completed", "dispatched"):
            break
        time.sleep(0.8)

    task = state.get("task", {})
    check(
        "工作流挂起于「待人工确认」",
        task.get("status") == "waiting_confirmation",
        f"status={task.get('status')} err={task.get('error')}",
    )
    traces = state.get("traces", [])
    check(f"节点追踪落库 {len(traces)} 条", len(traces) >= 8, str(len(traces)))
    if traces:
        print("         执行节点：" + " → ".join(t["node_name"] for t in traces))
    plan = task.get("selected_plan") or {}
    check(
        f"多方案比选（选中 {plan.get('plan_id')}，得分 {plan.get('score')}）",
        bool(plan.get("plan_id")),
        str(plan)[:160],
    )
    check("方案解释已生成", bool(task.get("plan_explanation")), str(task.get("plan_explanation"))[:100])
    check(
        f"子任务按公式计算（{plan.get('subtask_count')} 个）",
        (plan.get("subtask_count") or 0) > 0,
        str(plan.get("subtask_count")),
    )

    r = c.post(
        f"{API}/api/v1/ai/agent/tasks/{task_id}/confirm",
        headers=H,
        json={"approved": True, "plan_id": plan.get("plan_id"), "comment": "联调验证确认"},
    )
    data = r.json().get("data", {})
    dr = data.get("dispatch_result") or {}
    check(
        "人工确认后完成工单下发",
        r.status_code == 200 and data.get("status") == "dispatched" and bool(dr.get("order_no")),
        str(data)[:200],
    )
    if dr:
        print(
            f"         下发工单 {dr.get('order_no')}：子任务 {dr.get('created')} 个，"
            f"覆盖站点 {dr.get('station_count')} 个，通知 {dr.get('notified_users')} 人"
        )
        r2 = c.get(f"{API}/api/v1/work-orders/{dr.get('work_order_id')}", headers=H)
        wo = r2.json()["data"]["work_order"]
        check(
            f"新工单可查（{wo['order_no']}，来源「{wo['source']}」）",
            wo.get("source") == "AI 生成",
            str(wo)[:160],
        )

    # ---------------- 报告生成 ----------------
    print("\n[7] 运维分析报告")
    r = c.post(
        f"{API}/api/v1/ai/report/generate",
        headers=H,
        json={"report_type": "daily", "use_llm": False},
    )
    rep = r.json().get("data", {})
    check("生成日运营简报", r.status_code == 200 and bool(rep.get("report_id")), str(rep)[:160])
    md = rep.get("markdown", "")
    sections = ["运行概览", "充放电分析", "设备状态诊断", "异常检测与告警", "根因分析", "运维建议"]
    missing = [s for s in sections if s not in md]
    check("包含 6 个规定内容模块", not missing, f"缺失 {missing}")
    print(f"         报告 {rep.get('report_no')}，PDF：{bool(rep.get('file_url'))}，{len(md)} 字符")

    # ---------------- 导出 ----------------
    print("\n[8] Excel 导出（任务式 + 进度）")
    r = c.post(f"{API}/api/v1/exports/work-orders", headers=H, json={})
    etid = r.json()["data"]["task_id"]
    final = {}
    for _ in range(60):
        r = c.get(f"{API}/api/v1/exports/tasks/{etid}", headers=H)
        final = r.json()["data"]
        if final["status"] in ("success", "failed"):
            break
        time.sleep(0.4)
    check(
        f"导出完成（{final.get('row_count')} 行）",
        final.get("status") == "success",
        str(final)[:160],
    )
    if final.get("status") == "success":
        dl = c.get(f"{API}/api/v1/exports/tasks/{etid}/download", headers=H)
        check(
            f"下载 Excel（{len(dl.content)} 字节）",
            dl.status_code == 200 and len(dl.content) > 3000,
            str(dl.status_code),
        )

    # ---------------- 附件上传（多图上传）----------------
    print("\n[8b] 附件上传（故障上报 / 故障核查 / 巡检录入）")
    r = c.get(f"{API}/api/v1/uploads/info", headers=H)
    info = r.json()["data"]
    check(
        f"上传能力（单张上限 {info.get('max_image_mb')}MB，最多 {info.get('max_files_per_request')} 张）",
        r.status_code == 200 and info.get("max_image_mb", 0) > 0,
        str(info)[:180],
    )

    png = _make_png()

    # ---- 故障上报带真实照片（原为 base64 占位，现已修）----
    r = c.post(
        f"{API}/api/v1/uploads/images",
        headers=H,
        params={"biz_type": "fault"},
        files=[
            ("files", ("故障照片1.png", png, "image/png")),
            ("files", ("故障照片2.png", png, "image/png")),
        ],
    )
    fault_urls = r.json()["data"]["urls"] if r.status_code == 200 else []
    check(f"故障照片上传 {len(fault_urls)} 张", len(fault_urls) == 2, str(r.status_code))

    piles = c.get(
        f"{API}/api/v1/faults/piles/options", headers=H, params={"project_id": pid}
    ).json()["data"]
    if fault_urls and piles:
        r = c.post(
            f"{API}/api/v1/faults",
            headers=H,
            json={
                "project_id": pid,
                "station_id": piles[0]["station_id"],
                "pile_id": piles[0]["id"],
                "fault_type": "通信故障",
                "description": "联调验证：带实拍照片的故障上报",
                "images": fault_urls,
            },
        )
        fid = r.json()["data"]["id"] if r.status_code == 200 else None
        check("故障上报携带真实照片", r.status_code == 200, f"{r.status_code} {r.text[:160]}")

        if fid:
            det = c.get(f"{API}/api/v1/faults/{fid}", headers=H).json()["data"]
            imgs = (det.get("fault") or {}).get("images") or []
            check(
                f"故障详情回显真实照片（{len(imgs)} 张）",
                len(imgs) == 2
                and all(str(u).startswith("/static/data/uploads/") for u in imgs),
                str(imgs)[:180],
            )
            att = c.get(
                f"{API}/api/v1/uploads/attachments",
                headers=H,
                params={"biz_type": "fault", "page_size": 50},
            ).json()["data"]["items"]
            check(
                f"故障照片已绑定业务单据（{len([a for a in att if a.get('biz_id') == fid])} 条）",
                len([a for a in att if a.get("biz_id") == fid]) == 2,
                str(att)[:180],
            )

            # 核查照片单独上传并绑定到核查记录
            vr = c.post(
                f"{API}/api/v1/uploads/images",
                headers=H,
                params={"biz_type": "verify"},
                files=[
                    ("files", ("核查照片1.png", png, "image/png")),
                    ("files", ("核查照片2.png", png, "image/png")),
                ],
            )
            vurls = vr.json()["data"]["urls"] if vr.status_code == 200 else []
            r = c.post(
                f"{API}/api/v1/faults/{fid}/verify",
                headers=H,
                json={
                    "verify_status": "核查通过",
                    "verify_level": "危急",
                    "verify_desc": "联调验证：现场已停机处置，复测合格。",
                    "images": vurls,
                },
            )
            check("故障核查携带真实照片", r.status_code == 200, f"{r.status_code} {r.text[:140]}")
            att = c.get(
                f"{API}/api/v1/uploads/attachments",
                headers=H,
                params={"biz_type": "verify", "page_size": 50},
            ).json()["data"]["items"]
            check(
                f"核查照片已绑定核查记录（{len([a for a in att if a.get('biz_id')])} 条）",
                len([a for a in att if a.get("biz_id")]) >= 2,
                str(att)[:180],
            )

    # ---- 巡检录入带真实照片 ----
    r = c.post(
        f"{API}/api/v1/uploads/images",
        headers=H,
        params={"biz_type": "inspection"},
        files=[
            ("files", ("巡检照片1.png", png, "image/png")),
            ("files", ("巡检照片2.png", png, "image/png")),
        ],
    )
    urls = r.json()["data"]["urls"] if r.status_code == 200 else []
    check(f"巡检照片上传 {len(urls)} 张", len(urls) == 2, f"{r.status_code} {r.text[:160]}")

    if urls:
        rr = c.get(f"{API}{urls[0]}")
        check(
            f"图片经 /static/data 可访问（{len(rr.content)} 字节）",
            rr.status_code == 200 and len(rr.content) == len(png),
            str(rr.status_code),
        )

        bad = [("files", ("bad.exe", b"MZ\x90\x00", "application/x-msdownload"))]
        rb = c.post(
            f"{API}/api/v1/uploads/images",
            headers=H,
            params={"biz_type": "inspection"},
            files=bad,
        )
        check("非法文件类型被拒绝", rb.status_code == 400, str(rb.status_code))

        # 带真实照片做巡检录入，验证附件归属回填
        subs = c.get(
            f"{API}/api/v1/work-orders/subtasks/mine",
            headers=H,
            params={"scope_all": True, "status": "待完成", "page_size": 5},
        ).json()["data"]["items"]
        if subs:
            r = c.post(
                f"{API}/api/v1/work-orders/inspections",
                headers=H,
                json={
                    "subtask_id": subs[0]["id"],
                    "items": [
                        {
                            "item_name": "桩体外观无破损",
                            "item_group": "外观与环境",
                            "result": "正常",
                            "images": [urls[0]],
                        }
                    ],
                    "images": urls,
                    "remark": "联调验证：带实拍照片的巡检记录",
                    "finish": True,
                },
            )
            check(
                "巡检录入携带真实照片",
                r.status_code == 200 and len(r.json()["data"]["images"]) == 2,
                f"{r.status_code} {r.text[:160]}",
            )
            bound = c.get(
                f"{API}/api/v1/uploads/attachments",
                headers=H,
                params={"biz_type": "inspection", "page_size": 50},
            ).json()["data"]["items"]
            linked = [a for a in bound if a.get("biz_id")]
            check(
                f"附件归属回填业务单据（{len(linked)} 条）",
                len(linked) >= 2,
                str(linked)[:160],
            )

    # ---------------- 前端代理 ----------------
    print("\n[9] 前端反向代理")
    r = c.post(
        f"{WEB}/api/v1/auth/login", json={"username": "admin", "password": "admin123"}
    )
    check("/api 代理到后端", r.status_code == 200 and "access_token" in r.text, str(r.status_code))

    print("\n" + "=" * 78)
    print(f"  联调验证完成：PASS {PASS} / FAIL {FAIL}")
    if FAILURES:
        print("  失败项：")
        for f in FAILURES:
            print(f"    - {f}")
    print("=" * 78)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
