"""后端端到端冒烟测试。

覆盖 PDF 各模块主链路：
  登录 → 工单（列表/首页/详情/申请/接单/巡检录入）→ 故障（上报/核查/统计）
  → 台账 → 消息 → 统计看板 → 导出 → AI Agent（工作流/诊断/报告/风控/知识库）

用法：
  python smoke_test.py            对真实 uvicorn 服务发 HTTP 请求（默认，推荐）
  python smoke_test.py --verbose  输出框架日志

说明：测试会拉起一个独立端口的 uvicorn 进程并使用独立数据库，
因此与开发中的服务互不干扰，且能真实覆盖 ASGI + 后台任务链路。
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from datetime import date, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent
_DB = BASE / "data" / "_smoke.db"
for _suffix in ("", "-wal", "-shm"):
    _p = Path(str(_DB) + _suffix)
    if _p.exists():
        _p.unlink()

# OR-Tools CP-SAT 在多进程服务下正常工作；如需极速冒烟可设为 false
_USE_CPSAT = os.environ.get("SMOKE_CPSAT", "true").lower() != "false"

_ENV = {
    **os.environ,
    "DATABASE_URL": f"sqlite+aiosqlite:///{_DB.as_posix()}",
    "CPSAT_ENABLED": "true" if _USE_CPSAT else "false",
    "PYTHONIOENCODING": "utf-8",
    "PYTHONUNBUFFERED": "1",
}

_VERBOSE = "--verbose" in sys.argv or "-v" in sys.argv
PORT = int(os.environ.get("SMOKE_PORT", "8123"))
BASE_URL = f"http://127.0.0.1:{PORT}"

import httpx  # noqa: E402

PASS = 0
FAIL = 0
FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  [PASS] {name}", flush=True)
    else:
        FAIL += 1
        FAILURES.append(f"{name} :: {detail}")
        print(f"  [FAIL] {name}  {detail}", flush=True)


class Client:
    """把 httpx.Client 包成与原 TestClient 一致的调用方式。"""

    def __init__(self, base_url: str) -> None:
        self._c = httpx.Client(base_url=base_url, timeout=120.0)

    def request(self, method: str, path: str, **kwargs):
        return self._c.request(method, path, **kwargs)

    def get(self, path: str, **kwargs):
        return self._c.get(path, **kwargs)

    def post(self, path: str, **kwargs):
        return self._c.post(path, **kwargs)

    def put(self, path: str, **kwargs):
        return self._c.put(path, **kwargs)

    def delete(self, path: str, **kwargs):
        return self._c.delete(path, **kwargs)

    def close(self) -> None:
        self._c.close()

    def __enter__(self) -> "Client":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


def _make_png() -> bytes:
    """生成一张结构合法的 1x1 白色 PNG（含正确 CRC），用于上传测试。"""
    import struct
    import zlib

    def chunk(ctype: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + ctype
            + data
            + struct.pack(">I", zlib.crc32(ctype + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)  # 1x1, 8bit, truecolor
    raw = b"\x00\xff\xff\xff"  # 一行像素：滤波字节 + RGB 白
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def api(client: "Client", method: str, path: str, **kwargs):
    resp = client.request(method, path, **kwargs)
    try:
        body = resp.json()
    except Exception:
        body = {"raw": resp.text[:400]}
    return resp.status_code, body


def wait_for_server(proc: subprocess.Popen, timeout: float = 120.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            return False
        try:
            with socket.create_connection(("127.0.0.1", PORT), timeout=1.0):
                pass
        except OSError:
            time.sleep(0.5)
            continue
        try:
            resp = httpx.get(f"{BASE_URL}/health", timeout=5.0)
            if resp.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def main() -> int:
    print("=" * 78)
    print("  充电桩运维管理 AI Agent 平台 —— 后端冒烟测试")
    print("=" * 78)
    print(f"  启动测试服务：{BASE_URL}（独立数据库 {_DB.name}，CP-SAT={_USE_CPSAT}）")

    log_file = None if _VERBOSE else open(BASE / "smoke_server.log", "w", encoding="utf-8")
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(PORT),
            "--log-level",
            "warning" if not _VERBOSE else "info",
        ],
        cwd=str(BASE),
        env=_ENV,
        stdout=log_file or sys.stdout,
        stderr=subprocess.STDOUT,
    )

    code = 1
    try:
        if not wait_for_server(proc):
            print("  服务启动失败，请查看 smoke_server.log")
            return 1
        print("  服务已就绪，开始测试\n")
        with Client(BASE_URL) as client:
            code = run_suite(client)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
        if log_file:
            log_file.close()
        write_report(code)

    return code


def write_report(exit_code: int) -> None:
    """把结果写入 UTF-8 报告文件，便于在任意终端/编辑器中查看。"""
    lines = [
        "=" * 78,
        "  充电桩运维管理 AI Agent 平台 —— 后端冒烟测试报告",
        "=" * 78,
        f"  执行时间：{time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"  PASS {PASS} / FAIL {FAIL}",
        f"  退出码：{exit_code}",
        "",
    ]
    if FAILURES:
        lines.append("失败项：")
        lines.extend(f"  - {item}" for item in FAILURES)
        lines.append("")
    lines.append("=" * 78)

    text = "\n".join(lines) + "\n"
    (BASE / "smoke_report.txt").write_text(text, encoding="utf-8")
    (BASE / "smoke_result.json").write_text(
        json.dumps(
            {
                "pass": PASS,
                "fail": FAIL,
                "exit_code": exit_code,
                "failures": FAILURES,
                "at": time.strftime("%Y-%m-%d %H:%M:%S"),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(text, flush=True)


def run_suite(client: "Client") -> int:  # noqa: C901
    # ---------------- 基础 ----------------
    print("\n[1] 系统基础")
    code, body = api(client, "GET", "/")
    check("GET / 服务信息", code == 200 and body.get("code") == 0, str(body)[:200])
    code, body = api(client, "GET", "/health")
    check(
        "GET /health 健康检查",
        code == 200 and body["data"]["database"]["ok"],
        str(body)[:300],
    )

    # ---------------- 认证 ----------------
    print("\n[2] 认证与权限")
    code, body = api(
        client, "POST", "/api/v1/auth/login", json={"username": "admin", "password": "wrong"}
    )
    check("错误密码被拒绝", code == 401, str(body)[:200])

    code, body = api(
        client, "POST", "/api/v1/auth/login", json={"username": "admin", "password": "admin123"}
    )
    check("管理员登录成功", code == 200 and body["data"]["access_token"], str(body)[:300])
    if code != 200:
        print("登录失败，终止测试")
        return 1
    token = body["data"]["access_token"]
    H = {"Authorization": f"Bearer {token}"}
    check(
        "登录返回数据权限",
        body["data"]["user"].get("data_scope") == "平台数据",
        str(body["data"]["user"])[:200],
    )

    code, body = api(client, "GET", "/api/v1/auth/profile", headers=H)
    check(
        "个人资料与权限菜单",
        code == 200 and len(body["data"]["permissions"]) > 10,
        f"perm={len(body.get('data', {}).get('permissions', []))}",
    )

    code, body = api(client, "GET", "/api/v1/work-orders")
    check("无 Token 访问被拒绝", code == 401, str(body)[:200])

    # ---------------- 角色与用户 ----------------
    print("\n[3] 角色与用户管理")
    code, body = api(client, "GET", "/api/v1/admin/roles", headers=H)
    check(
        "角色列表（5 个内置角色）",
        code == 200 and body["data"]["meta"]["total"] >= 5,
        f"total={body.get('data', {}).get('meta', {}).get('total')}",
    )
    code, body = api(client, "GET", "/api/v1/admin/permissions/tree", headers=H)
    check("树形权限菜单", code == 200 and len(body["data"]) > 0, str(body)[:200])
    code, body = api(client, "GET", "/api/v1/admin/users", headers=H)
    check(
        "用户列表",
        code == 200 and body["data"]["meta"]["total"] >= 5,
        f"total={body['data']['meta']['total'] if code==200 else body}",
    )

    code, body = api(
        client,
        "POST",
        "/api/v1/admin/users",
        headers=H,
        json={
            "username": "smoke_user",
            "real_name": "冒烟测试用户",
            "password": "test123456",
            "user_type": "staff",
        },
    )
    check("新增用户", code == 200 and body["data"]["username"] == "smoke_user", str(body)[:200])
    new_user_id = body["data"]["id"] if code == 200 else None
    if new_user_id:
        code, body = api(
            client,
            "PUT",
            f"/api/v1/admin/users/{new_user_id}",
            headers=H,
            json={"real_name": "冒烟测试用户（已改）"},
        )
        check("编辑用户", code == 200 and "已改" in body["data"]["real_name"], str(body)[:200])
        code, body = api(client, "DELETE", f"/api/v1/admin/users/{new_user_id}", headers=H)
        check("删除用户", code == 200, str(body)[:200])

    # ---------------- 项目 / 站点 / 桩 ----------------
    print("\n[4] 台账与资产")
    code, body = api(client, "GET", "/api/v1/admin/projects", headers=H)
    check("项目列表", code == 200 and len(body["data"]) >= 3, str(body)[:200])
    project_id = body["data"][0]["id"] if code == 200 else None

    code, body = api(client, "GET", "/api/v1/admin/stations", headers=H, params={"page_size": 50})
    check(
        "站点列表（含桩数量）",
        code == 200 and body["data"]["meta"]["total"] >= 8,
        f"total={body['data']['meta']['total'] if code==200 else body}",
    )
    station_id = body["data"]["items"][0]["id"] if code == 200 else None

    code, body = api(client, "GET", "/api/v1/admin/piles/status-summary", headers=H)
    check(
        "充电桩状态汇总（含充电枪总数）",
        code == 200 and body["data"]["gun_total"] > 0,
        str(body)[:200],
    )

    code, body = api(
        client, "GET", "/api/v1/admin/ledger", headers=H, params={"page_size": 100}
    )
    check(
        "台账查询",
        code == 200 and body["data"]["meta"]["total"] > 0,
        str(body)[:200],
    )

    if station_id:
        code, body = api(
            client,
            "PUT",
            f"/api/v1/admin/stations/{station_id}/extensions",
            headers=H,
            json={"extinguisher_type": "无"},
        )
        check(
            "灭火器「无」选项（PDF 3.10 动态表单）",
            code == 200
            and body["data"]["extinguisher_type"] == "无"
            and body["data"]["extinguisher_spec"] is None,
            str(body)[:250],
        )
        code, body = api(
            client,
            "GET",
            f"/api/v1/admin/stations/{station_id}/navigation",
            headers=H,
        )
        check("站点导航与地图分享", code == 200 and "amap_uri" in body["data"], str(body)[:200])

    # ---------------- 工单 ----------------
    print("\n[5] 工单管理（核心业务）")
    code, body = api(client, "GET", "/api/v1/work-orders/home", headers=H)
    check(
        "工单首页统计",
        code == 200 and body["data"]["total"] > 0,
        str(body)[:250],
    )
    baseline_total = body["data"]["total"] if code == 200 else 0

    code, body = api(
        client, "GET", "/api/v1/work-orders", headers=H, params={"page_size": 50}
    )
    check(
        "工单列表",
        code == 200 and body["data"]["meta"]["total"] > 0,
        str(body)[:250],
    )
    work_orders = body["data"]["items"] if code == 200 else []
    check("工单列表含时间状态 tag", all("time_status" in w for w in work_orders))

    # 公式验证：巡视 2 站点 × 周期1 × 频率月(1) = 2
    code, body = api(
        client,
        "POST",
        "/api/v1/work-orders",
        headers=H,
        json={
            "order_name": "冒烟测试巡视工单",
            "order_type": "巡视",
            "project_id": project_id,
            "inspect_start_date": date.today().isoformat(),
            "inspect_end_date": (date.today() + timedelta(days=30)).isoformat(),
            "inspect_frequency": "月",
            "inspect_cycle": 1,
        },
    )
    check("工单申请（巡视）", code == 200, str(body)[:300])
    created_order = body["data"] if code == 200 else None
    if created_order:
        n_stations = len(
            body["data"].get("station_names") or []
        )
        expected = n_stations * 1 * 1
        check(
            f"子任务公式校验（{n_stations} 站点 × 周期1 × 频率月 = {expected}）",
            created_order["subtask_total"] == expected,
            f"实际 {created_order['subtask_total']}，期望 {expected}",
        )

        code, body = api(
            client,
            "GET",
            f"/api/v1/work-orders/{created_order['id']}",
            headers=H,
        )
        check(
            "工单详情含子任务与权限位",
            code == 200
            and len(body["data"]["subtasks"]) == expected
            and "can_accept" in body["data"]["permissions"],
            str(body)[:250],
        )

        code, body = api(
            client,
            "POST",
            f"/api/v1/work-orders/{created_order['id']}/accept",
            headers=H,
        )
        check("接受工单", code == 200 and body["data"]["status"] == "待完成", str(body)[:200])

    # 消缺工单固定 1 个子任务
    code, body = api(
        client,
        "POST",
        "/api/v1/work-orders",
        headers=H,
        json={
            "order_name": "冒烟测试消缺工单",
            "order_type": "消缺",
            "project_id": project_id,
            "inspect_start_date": date.today().isoformat(),
        },
    )
    check(
        "消缺工单固定 1 个子任务（硬约束）",
        code == 200 and body["data"]["subtask_total"] == 1,
        f"subtask_total={body.get('data', {}).get('subtask_total')}",
    )
    defect_order = body["data"] if code == 200 else None

    # 特巡公式：站点 × 次数
    code, body = api(
        client,
        "POST",
        "/api/v1/work-orders",
        headers=H,
        json={
            "order_name": "冒烟测试特巡工单",
            "order_type": "特巡",
            "project_id": project_id,
            "inspect_start_date": date.today().isoformat(),
            "inspect_count": 3,
        },
    )
    if code == 200:
        n = len(body["data"].get("station_names") or [])
        check(
            f"特巡公式校验（{n} 站点 × 3 次 = {n*3}）",
            body["data"]["subtask_total"] == n * 3,
            f"实际 {body['data']['subtask_total']}",
        )
    else:
        check("特巡工单申请", False, str(body)[:200])

    # 状态机校验：已完成工单不能再次接受
    if defect_order:
        code, body = api(
            client,
            "POST",
            f"/api/v1/work-orders/{defect_order['id']}/cancel",
            headers=H,
            json={"reason": "冒烟测试取消"},
        )
        check("取消工单", code == 200 and body["data"]["status"] == "已取消", str(body)[:200])
        code, body = api(
            client,
            "POST",
            f"/api/v1/work-orders/{defect_order['id']}/accept",
            headers=H,
        )
        check("状态机拦截非法迁移（已取消 → 待完成）", code == 400, str(body)[:200])

    # 作业管理
    code, body = api(
        client, "GET", "/api/v1/work-orders/subtasks/mine", headers=H, params={"scope_all": True}
    )
    check(
        "我的作业任务（作业管理）",
        code == 200 and body["data"]["meta"]["total"] > 0,
        str(body)[:200],
    )

    # 巡检录入
    code, body = api(
        client,
        "GET",
        "/api/v1/work-orders/inspections/template",
        headers=H,
        params={"order_type": "巡视"},
    )
    check(
        "巡检项模板（分类显示）",
        code == 200 and len(body["data"]["template"]) > 5 and body["data"]["max_remark_length"] == 200,
        str(body)[:200],
    )

    # 找一个待完成子任务做巡检录入
    pending_subtask = None
    for wo in work_orders:
        if wo["status"] in ("待完成", "待接单"):
            code, body = api(
                client,
                "GET",
                f"/api/v1/work-orders/{wo['id']}/subtasks",
                headers=H,
            )
            if code == 200:
                for st in body["data"]["items"]:
                    if st["status"] == "待完成":
                        pending_subtask = st
                        break
        if pending_subtask:
            break

    if pending_subtask:
        code, body = api(
            client,
            "POST",
            "/api/v1/work-orders/inspections",
            headers=H,
            json={
                "subtask_id": pending_subtask["id"],
                "items": [
                    {"item_name": "桩体外观无破损", "item_group": "外观与环境", "result": "正常"},
                    {
                        "item_name": "急停按钮功能正常",
                        "item_group": "电气安全",
                        "result": "异常",
                        "remark": "急停按钮卡滞，需更换",
                    },
                ],
                "images": ["/static/data/uploads/smoke_1.jpg"],
                "remark": "冒烟测试巡检记录",
                "checkin_location": "测试点位",
                "finish": True,
            },
        )
        check(
            "巡检情况录入（正常/异常勾选 + 200 字备注）",
            code == 200
            and body["data"]["abnormal_count"] == 1
            and body["data"]["normal_count"] == 1,
            str(body)[:300],
        )
        code, body = api(
            client,
            "POST",
            "/api/v1/work-orders/inspections",
            headers=H,
            json={
                "subtask_id": pending_subtask["id"],
                "items": [],
                "remark": "长" * 250,
            },
        )
        check("巡检备注超 200 字被拒绝", code == 422 or code == 400, str(body)[:200])

    # 工单导出
    code, body = api(client, "POST", "/api/v1/exports/work-orders", headers=H, json={})
    check("创建工单导出任务", code == 200 and body["data"]["task_id"], str(body)[:200])
    if code == 200:
        task_id = body["data"]["task_id"]
        for _ in range(30):
            code2, body2 = api(client, "GET", f"/api/v1/exports/tasks/{task_id}", headers=H)
            if code2 == 200 and body2["data"]["status"] in ("success", "failed"):
                break
            time.sleep(0.3)
        check(
            "导出任务完成并可下载",
            code2 == 200 and body2["data"]["status"] == "success",
            str(body2)[:250],
        )
        if code2 == 200 and body2["data"]["status"] == "success":
            resp = client.get(
                f"/api/v1/exports/tasks/{task_id}/download", headers=H
            )
            check(
                "下载 Excel 文件",
                resp.status_code == 200 and len(resp.content) > 2000,
                f"status={resp.status_code} size={len(resp.content)}",
            )

    # ---------------- 附件上传（多图上传，PDF 3.4 / 3.5）----------------
    # 放在故障/巡检用例之前：后续用真实上传的 URL 走完整业务链路，
    # 才能验证「图片真的落盘 + 附件归属真的回填」。
    print("\n[6b] 附件上传（多图上传）")
    code, body = api(client, "GET", "/api/v1/uploads/info", headers=H)
    check(
        "上传能力与限制说明",
        code == 200 and body["data"].get("max_image_mb", 0) > 0,
        str(body)[:250],
    )

    png_bytes = _make_png()
    resp = client.post(
        "/api/v1/uploads/images",
        headers=H,
        params={"biz_type": "fault"},
        files=[
            ("files", ("现场照片1.png", png_bytes, "image/png")),
            ("files", ("现场照片2.png", png_bytes, "image/png")),
        ],
    )
    up = resp.json() if resp.status_code == 200 else {}
    fault_image_urls = up.get("data", {}).get("urls", []) if up else []
    check(
        f"多图上传（{len(fault_image_urls)} 张）",
        resp.status_code == 200 and len(fault_image_urls) == 2,
        f"{resp.status_code} {resp.text[:200]}",
    )
    check(
        "返回可访问的图片 URL",
        bool(fault_image_urls)
        and all(u.startswith("/static/data/uploads/") for u in fault_image_urls),
        str(fault_image_urls)[:200],
    )

    if fault_image_urls:
        r = client.get(fault_image_urls[0])
        check(
            f"图片可经静态挂载访问（{len(r.content)} 字节）",
            r.status_code == 200 and len(r.content) == len(png_bytes),
            f"{r.status_code} {len(r.content)}",
        )

        # 回归：不存在的静态资源必须返回 404（曾因兜底 404 处理器无差别返回
        # JSONResponse 而变成 500 —— StaticFiles 抛的 HTTPException 被误当内部错误）
        r = client.get("/static/data/uploads/definitely-missing-file.png")
        check(
            "不存在的静态文件返回 404 而非 500",
            r.status_code == 404,
            f"{r.status_code} {r.text[:120]}",
        )
        r = client.get("/api/v1/definitely-missing-endpoint")
        check(
            "不存在的 API 返回 404 且为统一 JSON 结构",
            r.status_code == 404 and r.json().get("code") == 404,
            f"{r.status_code} {r.text[:120]}",
        )

        bad = [("files", ("坏文件.exe", b"MZ\x90\x00", "application/x-msdownload"))]
        r = client.post(
            "/api/v1/uploads/images",
            headers=H,
            params={"biz_type": "fault"},
            files=bad,
        )
        check("非法文件类型被拒绝", r.status_code == 400, f"{r.status_code} {r.text[:160]}")

    # ---------------- 故障 ----------------
    print("\n[6] 故障管理")
    code, body = api(client, "GET", "/api/v1/faults/home", headers=H)
    check(
        "故障首页统计",
        code == 200 and body["data"]["total"] > 0,
        str(body)[:250],
    )

    code, body = api(client, "GET", "/api/v1/faults/piles/options", headers=H, params={"project_id": project_id})
    check("充电桩级联下拉", code == 200 and len(body["data"]) > 0, str(body)[:200])
    pile = body["data"][0] if code == 200 and body["data"] else None

    code, body = api(client, "GET", "/api/v1/faults/levels", headers=H)
    check(
        "故障等级/状态字典",
        code == 200 and len(body["data"]["levels"]) == 3,
        str(body)[:200],
    )

    # 草稿
    code, body = api(
        client,
        "POST",
        "/api/v1/faults",
        headers=H,
        json={
            "project_id": project_id,
            "station_id": pile["station_id"] if pile else None,
            "pile_id": pile["id"] if pile else None,
            "fault_type": "通信故障",
            "description": "桩体离线，平台无法下发指令",
            "is_draft": True,
        },
    )
    check(
        "故障保存草稿",
        code == 200 and body["data"]["is_draft"] and body["data"]["status"] == "待上报",
        str(body)[:250],
    )
    draft_id = body["data"]["id"] if code == 200 else None

    if draft_id:
        code, body = api(
            client, "POST", f"/api/v1/faults/{draft_id}/confirm", headers=H
        )
        check(
            "草稿确认上报",
            code == 200 and body["data"]["status"] == "待核查",
            str(body)[:200],
        )

    # 危急故障自动等级判定
    code, body = api(
        client,
        "POST",
        "/api/v1/faults",
        headers=H,
        json={
            "project_id": project_id,
            "station_id": pile["station_id"] if pile else None,
            "pile_id": pile["id"] if pile else None,
            "fault_type": "绝缘监测报警",
            "description": "现场冒烟并有漏电现象，需紧急处理",
            "images": fault_image_urls,
        },
    )
    check(
        "高风险关键词自动判定为「危急」",
        code == 200 and body["data"]["fault_level"] == "危急",
        f"level={body.get('data', {}).get('fault_level')}",
    )
    critical_id = body["data"]["id"] if code == 200 else None

    # 核查用的照片单独上传（一次上传只归属一条业务记录，符合附件语义）
    verify_image_urls = []
    if critical_id:
        vresp = client.post(
            "/api/v1/uploads/images",
            headers=H,
            params={"biz_type": "verify"},
            files=[
                ("files", ("核查照片1.png", png_bytes, "image/png")),
                ("files", ("核查照片2.png", png_bytes, "image/png")),
            ],
        )
        if vresp.status_code == 200:
            verify_image_urls = vresp.json()["data"]["urls"]

    if critical_id:
        code, body = api(
            client,
            "POST",
            f"/api/v1/faults/{critical_id}/verify",
            headers=H,
            json={
                "verify_status": "核查通过",
                "verify_level": "危急",
                "verify_desc": "现场确认绝缘失效，已停机并更换枪线，复测绝缘电阻 2.5 兆欧合格。",
                "images": verify_image_urls,
                "need_defect_order": True,
            },
        )
        check(
            "故障核查（核查通过）",
            code == 200 and body["data"]["verify_status"] == "核查通过",
            str(body)[:250],
        )

        # 故障照片真实落盘 + 附件归属回填到该故障单（PDF 3.5 多图上传）
        if fault_image_urls and critical_id:
            code, body = api(client, "GET", f"/api/v1/faults/{critical_id}", headers=H)
            imgs = (body.get("data", {}).get("fault", {}) or {}).get("images") or []
            check(
                "故障详情回显真实上传的照片",
                code == 200
                and len(imgs) == 2
                and all(str(u).startswith("/static/data/uploads/") for u in imgs),
                str(imgs)[:200],
            )

            code, body = api(
                client,
                "GET",
                "/api/v1/uploads/attachments",
                headers=H,
                params={"biz_type": "fault", "page_size": 50},
            )
            linked = [
                a
                for a in body.get("data", {}).get("items", [])
                if a.get("biz_id") == critical_id
            ]
            check(
                f"故障照片附件已绑定业务单据（{len(linked)} 条）",
                len(linked) == 2,
                str(linked)[:220],
            )

            # 核查照片也应绑定到核查记录
            code, body = api(
                client,
                "GET",
                "/api/v1/uploads/attachments",
                headers=H,
                params={"biz_type": "verify", "page_size": 50},
            )
            verify_linked = [
                a for a in body.get("data", {}).get("items", []) if a.get("biz_id")
            ]
            check(
                f"核查照片附件已绑定核查记录（{len(verify_linked)} 条）",
                len(verify_linked) >= 2,
                str(verify_linked)[:220],
            )

    code, body = api(
        client,
        "GET",
        "/api/v1/faults",
        headers=H,
        params={"tab": "待核查", "page_size": 50},
    )
    check(
        "故障 tab 筛选（待核查）",
        code == 200
        and all(f["status"] == "待核查" for f in body["data"]["items"]),
        str(body)[:200],
    )

    # ---------------- 消息中心 ----------------
    print("\n[7] 消息中心")
    code, body = api(client, "GET", "/api/v1/messages", headers=H)
    check(
        "消息列表 + 未读数",
        code == 200 and "unread_count" in body["data"],
        str(body)[:250],
    )
    code, body = api(client, "GET", "/api/v1/messages/types", headers=H)
    check("消息类型区分", code == 200 and len(body["data"]) > 0, str(body)[:200])

    # ---------------- 统计分析 ----------------
    print("\n[8] 统计分析与看板")
    code, body = api(client, "GET", "/api/v1/statistics/dashboard", headers=H)
    d = body.get("data", {}) if code == 200 else {}
    check(
        "统计看板（工单/完成率/逾期率）",
        code == 200 and "completion_rate" in d.get("work_order", {}),
        str(body)[:250],
    )
    check(
        "5 种工单数量分布",
        len(d.get("order_type_dist", [])) == 5,
        f"dist={d.get('order_type_dist')}",
    )
    check(
        "项目工单排名 + 站点消缺排名",
        "project_rank" in d and "defect_station_rank" in d,
        str(list(d.keys()))[:200],
    )

    code, body = api(client, "GET", "/api/v1/statistics/trend", headers=H, params={"days": 30})
    check(
        "统计日报趋势",
        code == 200 and len(body["data"]["series"]) >= 0,
        str(body)[:200],
    )

    # ---------------- 附件与业务单据的关联 ----------------
    # 上传用例已在 [6b] 完成，这里只验证「巡检录入带真实照片 + 附件归属回填」
    if fault_image_urls:
        code, body = api(
            client,
            "GET",
            "/api/v1/uploads/attachments",
            headers=H,
            params={"biz_type": "fault", "page_size": 50},
        )
        check(
            "附件登记到 attachment 表",
            code == 200 and body["data"]["meta"]["total"] >= 2,
            str(body)[:200],
        )

        # 带真实照片做一次巡检录入（另上传两张 inspection 类型图片）
        insp_resp = client.post(
            "/api/v1/uploads/images",
            headers=H,
            params={"biz_type": "inspection"},
            files=[
                ("files", ("巡检照片1.png", png_bytes, "image/png")),
                ("files", ("巡检照片2.png", png_bytes, "image/png")),
            ],
        )
        insp_urls = (
            insp_resp.json()["data"]["urls"] if insp_resp.status_code == 200 else []
        )

        code, body = api(
            client,
            "GET",
            "/api/v1/work-orders",
            headers=H,
            params={"page_size": 30},
        )
        target_sub = None
        for wo in body.get("data", {}).get("items", []):
            code2, body2 = api(
                client, "GET", f"/api/v1/work-orders/{wo['id']}/subtasks", headers=H
            )
            if code2 == 200:
                for st in body2["data"]["items"]:
                    if st["status"] in ("待完成", "巡检中"):
                        target_sub = st
                        break
            if target_sub:
                break

        if target_sub and insp_urls:
            code, body = api(
                client,
                "POST",
                "/api/v1/work-orders/inspections",
                headers=H,
                json={
                    "subtask_id": target_sub["id"],
                    "items": [
                        {
                            "item_name": "桩体外观无破损",
                            "item_group": "外观与环境",
                            "result": "正常",
                            "images": [insp_urls[0]],
                        }
                    ],
                    "images": insp_urls,
                    "remark": "带实拍照片的巡检记录",
                    "finish": True,
                },
            )
            check(
                "巡检录入携带真实上传照片",
                code == 200
                and len(body["data"]["images"]) == 2
                and body["data"]["images"][0].startswith("/static/data/uploads/"),
                str(body)[:250],
            )

            code, body = api(
                client,
                "GET",
                "/api/v1/uploads/attachments",
                headers=H,
                params={"biz_type": "inspection"},
            )
            bound = [a for a in body.get("data", {}).get("items", []) if a.get("biz_id")]
            check(
                f"附件归属回填业务单据（{len(bound)} 条）",
                len(bound) >= 2,
                str(bound)[:200],
            )

    # ---------------- AI Agent ----------------
    print("\n[9] AI Agent（核心）")
    code, body = api(client, "GET", "/api/v1/ai/health", headers=H)
    check(
        "AI 能力与 LLM 状态",
        code == 200 and "status" in body["data"],
        str(body)[:300],
    )
    print(
        f"        LLM 状态：{body['data'].get('status')} | "
        f"模型：{body['data'].get('model')} | "
        f"Key 已配置：{body['data'].get('api_key_configured')}"
    )

    code, body = api(client, "GET", "/api/v1/ai/graph", headers=H)
    check(
        "LangGraph 工作流信息",
        code == 200 and len(body["data"]["normal_flow"]) == 11,
        str(body["data"].get("normal_flow"))[:250],
    )

    # 知识库
    code, body = api(client, "GET", "/api/v1/ai/knowledge/categories", headers=H)
    check(
        "知识库分类",
        code == 200 and len(body["data"]) >= 3,
        str(body)[:250],
    )
    code, body = api(
        client,
        "POST",
        "/api/v1/ai/knowledge/ask",
        headers=H,
        json={"question": "绝缘故障现场怎么处置？", "top_k": 3},
    )
    check(
        "知识库 RAG 问答（命中 SOP/故障案例）",
        code == 200 and len(body["data"]["references"]) > 0,
        str(body)[:300],
    )
    if code == 200 and body["data"]["references"]:
        print(
            "        命中：" + "、".join(
                f"{r['title']}({r['score']})" for r in body["data"]["references"][:3]
            )
        )

    # 智能工单生成（LangGraph 全流程 + 人工确认）
    code, body = api(
        client,
        "POST",
        "/api/v1/ai/work-order/generate",
        headers=H,
        json={
            "project_id": project_id,
            "order_type": "巡视",
            "inspect_frequency": "月",
            "inspect_cycle": 1,
            "auto_start": True,
            "explain_with_llm": True,
        },
    )
    check("智能工单生成任务创建", code == 200 and body["data"]["task_id"], str(body)[:300])
    agent_task_id = body["data"]["task_id"] if code == 200 else None

    if agent_task_id:
        state = None
        for _ in range(60):
            code2, body2 = api(
                client, "GET", f"/api/v1/ai/agent/tasks/{agent_task_id}", headers=H
            )
            state = body2.get("data", {}) if code2 == 200 else {}
            st = state.get("task", {}).get("status")
            if st in ("waiting_confirmation", "failed", "completed", "dispatched"):
                break
            time.sleep(0.5)

        task_info = state.get("task", {}) if state else {}
        check(
            "Agent 工作流执行至人工确认节点（LangGraph interrupt）",
            task_info.get("status") == "waiting_confirmation",
            f"status={task_info.get('status')} err={task_info.get('error')}",
        )
        traces = state.get("traces", []) if state else []
        check(
            "节点追踪落库（ai_agent_trace）",
            len(traces) >= 5,
            f"traces={len(traces)}",
        )
        if traces:
            print("        执行节点：" + " → ".join(t["node_name"] for t in traces))
        selected = task_info.get("selected_plan") or {}
        check(
            "生成多方案并选出最优",
            bool(selected.get("plan_id")),
            f"selected={selected.get('plan_id')} score={selected.get('score')}",
        )
        if selected:
            print(
                f"        最优方案：{selected.get('name')} "
                f"得分 {selected.get('score')} 子任务 {selected.get('subtask_count')}"
            )
        plan_explanation = task_info.get("plan_explanation")
        check("方案解释已生成", bool(plan_explanation), str(plan_explanation)[:150])

        # 人工确认 → 下发
        code, body = api(
            client,
            "POST",
            f"/api/v1/ai/agent/tasks/{agent_task_id}/confirm",
            headers=H,
            json={
                "approved": True,
                "plan_id": selected.get("plan_id"),
                "comment": "冒烟测试确认",
                "auto_dispatch": True,
            },
        )
        check(
            "人工确认并下发工单",
            code == 200 and body["data"]["status"] == "dispatched",
            str(body)[:350],
        )
        if code == 200:
            dr = body["data"].get("dispatch_result") or {}
            print(
                f"        下发结果：工单 {dr.get('order_no')} "
                f"子任务 {dr.get('created')} 通知 {dr.get('notified_users')} 人"
            )

    # 故障诊断
    code, body = api(
        client,
        "POST",
        "/api/v1/ai/fault/diagnose",
        headers=H,
        json={"fault_type": "功率模块故障", "description": "充电功率仅能维持 30kW，报 E05 故障码"},
    )
    diag = body.get("data", {}).get("diagnosis", {}) if code == 200 else {}
    check(
        "智能故障诊断（规则引擎 + RAG）",
        code == 200 and diag.get("matched_category") == "功率",
        f"category={diag.get('matched_category')}",
    )
    check(
        "诊断输出根因与处置措施",
        len(diag.get("possible_causes", [])) > 0 and len(diag.get("actions", [])) > 0,
        str(diag)[:200],
    )
    print(f"        LLM 增强：{body.get('data', {}).get('llm_used')}（degraded={body.get('data', {}).get('degraded')}）")

    # 运维建议
    code, body = api(
        client,
        "POST",
        "/api/v1/ai/maintenance/suggest",
        headers=H,
        json={"fault_type": "绝缘监测报警", "diagnosis": "雨后桩体报绝缘报警，底部积水"},
    )
    check(
        "智能运维建议",
        code == 200 and len(body["data"]["suggestions"]) > 0,
        str(body)[:250],
    )

    # 巡检报告
    code, body = api(
        client,
        "POST",
        "/api/v1/ai/inspection/report",
        headers=H,
        json={"use_llm": True},
    )
    check(
        "智能巡检报告（含异常项明细）",
        code == 200 and body["data"]["metrics"]["巡检记录数"] > 0,
        str(body)[:300],
    )
    if code == 200:
        print(
            f"        巡检记录 {body['data']['metrics']['巡检记录数']} 条，"
            f"异常项 {body['data']['metrics']['异常项总数']} 个，"
            f"正常率 {body['data']['metrics']['正常率(%)']}%"
        )

    # 风控
    code, body = api(
        client,
        "POST",
        "/api/v1/ai/risk/check",
        headers=H,
        json={"scope": "whole", "days": 90},
    )
    check(
        "智能风控检查",
        code == 200 and "findings" in body["data"],
        str(body)[:300],
    )
    if code == 200:
        print(
            f"        命中风险 {body['data']['total']} 条 {body['data']['summary']}"
        )

    # 报告生成
    code, body = api(
        client,
        "POST",
        "/api/v1/ai/report/generate",
        headers=H,
        json={"report_type": "daily", "use_llm": True},
    )
    check(
        "智能报告生成（日运营简报）",
        code == 200 and body["data"]["report_id"],
        str(body)[:350],
    )
    report_id = body["data"]["report_id"] if code == 200 else None
    if code == 200:
        print(
            f"        报告 {body['data']['report_no']} | "
            f"LLM：{body['data']['llm_used']} | 降级：{body['data']['degraded']} | "
            f"PDF：{bool(body['data']['file_url'])}"
        )
        sections = ["运行概览", "充放电分析", "设备状态诊断", "异常检测与告警", "根因分析", "运维建议"]
        md = body["data"]["markdown"]
        missing = [s for s in sections if s not in md]
        check(
            "报告包含 PDF 3.12 规定的 6 个内容模块",
            not missing,
            f"缺失：{missing}",
        )

    if report_id:
        code, body = api(
            client,
            "POST",
            f"/api/v1/ai/report/{report_id}/follow-up",
            headers=H,
            json={"question": "本周逾期工单有多少？", "use_llm": True},
        )
        check(
            "报告追问下钻",
            code == 200 and len(body["data"]["answer"]) > 5,
            str(body)[:250],
        )

    code, body = api(
        client, "GET", "/api/v1/ai/report/compare/weekly", headers=H, params={"limit": 3}
    )
    check(
        "报告历史对比",
        code == 200 or code == 400,
        f"code={code}（无历史周报时返回 400 亦属预期）",
    )

    # 报告列表
    code, body = api(client, "GET", "/api/v1/ai/report/list", headers=H)
    check(
        "报告列表",
        code == 200 and body["data"]["meta"]["total"] > 0,
        str(body)[:200],
    )

    # 学习助手
    code, body = api(
        client,
        "POST",
        "/api/v1/ai/assistant/ask",
        headers=H,
        json={"question": "直流桩功率模块故障怎么排查？"},
    )
    check(
        "学习助手追问",
        code == 200 and len(body["data"]["answer"]) > 10,
        str(body)[:250],
    )

    # Agent 中心
    code, body = api(client, "GET", "/api/v1/ai/agent/center", headers=H)
    check(
        "AI Agent 中心（8 类 Agent）",
        code == 200 and len(body["data"]["agents"]) == 8,
        str(body)[:250],
    )

    # 异常扫描
    code, body = api(client, "POST", "/api/v1/ai/exceptions/scan", headers=H)
    check(
        "异常事件扫描（PDF 4.9）",
        code == 200 and "scanned" in body["data"],
        str(body)[:250],
    )

    # 定时任务
    code, body = api(client, "GET", "/api/v1/ai/jobs", headers=H)
    check(
        "定时任务列表（日/周/月报告）",
        code == 200 and len(body["data"]) >= 6,
        str(body)[:250],
    )

    # ---------------- 排班与配置 ----------------
    print("\n[10] 系统参数与排班")
    code, body = api(client, "GET", "/api/v1/admin/configs", headers=H)
    check(
        "系统参数列表（工单/故障/报告/AI 开关）",
        code == 200 and len(body["data"]) >= 20,
        f"count={len(body.get('data', []))}",
    )
    code, body = api(client, "GET", "/api/v1/admin/rules/active", headers=H)
    check(
        "当前生效规则版本",
        code == 200 and "hard_constraints" in body["data"],
        str(body)[:250],
    )
    code, body = api(client, "GET", "/api/v1/admin/shifts", headers=H)
    check("人员排班", code == 200 and len(body["data"]) > 0, str(body)[:200])

    code, body = api(client, "GET", "/api/v1/admin/logs/operations", headers=H)
    check(
        "操作日志（审计）",
        code == 200 and body["data"]["meta"]["total"] > 0,
        str(body)[:200],
    )

    # ---------------- 数据权限 ----------------
    print("\n[11] 数据权限（个人/站点/项目/平台）")
    code, body = api(
        client,
        "POST",
        "/api/v1/auth/login",
        json={"username": "inspector", "password": "123456"},
    )
    check("运维人员登录", code == 200, str(body)[:200])
    if code == 200:
        staff_token = body["data"]["access_token"]
        SH = {"Authorization": f"Bearer {staff_token}"}
        check(
            "运维人员数据权限为「个人数据」",
            body["data"]["user"]["data_scope"] == "个人数据",
            str(body["data"]["user"].get("data_scope")),
        )
        code, body = api(client, "GET", "/api/v1/work-orders", headers=SH)
        staff_total = body["data"]["meta"]["total"] if code == 200 else -1
        check(
            "运维人员仅见本人工单（数据权限生效）",
            code == 200 and staff_total <= baseline_total,
            f"staff={staff_total} admin={baseline_total}",
        )
        code, body = api(client, "DELETE", "/api/v1/admin/users/00000000-0000-0000-0000-000000000000", headers=SH)
        check("运维人员无用户管理权限被拒绝", code == 403, str(body)[:200])

    # ---------------- 汇总 ----------------
    print("\n" + "=" * 78)
    print(f"  测试完成：PASS {PASS} / FAIL {FAIL}")
    if FAILURES:
        print("  失败项：")
        for item in FAILURES:
            print(f"    - {item}")
    print("=" * 78)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
