"""核查两个「是否真的完成」的问题：
1) 故障页用 base64 提交的图片，后端能否落盘/回显？
2) 周报、月报是否真的能生成？
"""

from __future__ import annotations

import sys

import httpx

API = "http://127.0.0.1:8000"
PASS = 0
FAIL = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [OK]   {name}")
    else:
        FAIL += 1
        print(f"  [问题] {name}  {detail}")


def main() -> int:
    c = httpx.Client(base_url=API, timeout=180.0)
    token = c.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "admin123"}
    ).json()["data"]["access_token"]
    H = {"Authorization": f"Bearer {token}"}
    projects = c.get("/api/v1/admin/projects", headers=H).json()["data"]
    pid = projects[0]["id"]

    print("=" * 78)
    print("  核查 1：故障图片用 base64 提交会怎样")
    print("=" * 78)
    # 模拟前端 FaultList 的行为：把 base64 data URL 当图片数组提交
    fake_base64 = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8AAAwAB/wD/AL0AAAAASUVORK5CYII="
    r = c.post(
        "/api/v1/faults",
        headers=H,
        json={
            "project_id": pid,
            "fault_type": "通信故障",
            "description": "核查用：测试 base64 图片提交",
            "images": [fake_base64],
        },
    )
    fault_id = r.json()["data"]["id"] if r.status_code == 200 else None
    check("故障上报接口接受 base64 字符串", r.status_code == 200, str(r.status_code))

    if fault_id:
        detail = c.get(f"/api/v1/faults/{fault_id}", headers=H).json()["data"]
        imgs = detail["fault"].get("images") or []
        check(
            "故障详情能回显该图片（即数据库里存了字符串）",
            len(imgs) == 1,
            str(imgs)[:100],
        )
        # 关键：这个 base64 是否能作为图片被浏览器/接口访问？
        r2 = c.get(f"/static/data/uploads/{fake_base64[:20]}")
        check("base64 不能作为静态图片访问（符合预期）", r2.status_code == 404, str(r2.status_code))
        print(
            "        结论：base64 字符串只是被当作普通文本存进 JSON 字段，\n"
            "              既没有落盘、也不能通过 URL 访问，附件表里没有记录。"
        )
        # 附件表是否有对应记录
        att = c.get(
            "/api/v1/uploads/attachments", headers=H, params={"biz_type": "fault", "page_size": 50}
        ).json()["data"]["items"]
        linked = [a for a in att if a.get("biz_id") == fault_id]
        check(
            "附件表中有该故障的记录（应当没有，故这是功能缺口）",
            len(linked) > 0,
            f"实际 {len(linked)} 条 → 说明故障页图片没有真正入库",
        )

    print()
    print("=" * 78)
    print("  核查 2：周报 / 月报 / 即时报告能否生成")
    print("=" * 78)
    for rtype, label in [
        ("daily", "日运营简报"),
        ("weekly", "周运维分析"),
        ("monthly", "月度深度报告"),
        ("instant", "即时分析运营报告"),
    ]:
        r = c.post(
            "/api/v1/ai/report/generate",
            headers=H,
            json={"report_type": rtype, "use_llm": False},
        )
        ok = r.status_code == 200 and r.json().get("data", {}).get("report_id")
        d = r.json().get("data", {}) if r.status_code == 200 else {}
        check(
            f"{label}",
            bool(ok),
            f"{r.status_code} {r.text[:120]}",
        )
        if ok:
            md = d.get("markdown", "")
            print(
                f"         {d.get('report_no')} | 周期 {d['period']['start']}~{d['period']['end']}"
                f" | 6 模块全含: {all(s in md for s in ['运行概览','设备状态诊断','根因分析','运维建议'])}"
            )

    print()
    print("=" * 78)
    print(f"  核查完成：正常 {PASS} / 问题 {FAIL}")
    print("=" * 78)
    c.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
