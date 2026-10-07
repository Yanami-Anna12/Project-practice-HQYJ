"""验证前端 Vite 能真实编译所有页面（不只是首页返回 200）。

默认检查充电桩项目前端（5185），可用 WEB_PORT 环境变量覆盖：
    WEB_PORT=5185  python verify_frontend.py
"""

from __future__ import annotations

import os
import sys

import httpx

WEB = f"http://127.0.0.1:{os.environ.get('WEB_PORT', '5185')}"

# 与 router/index.js 一一对应
ROUTES = [
    ("/src/main.js", "入口"),
    ("/src/App.vue", "根组件"),
    ("/src/layouts/BasicLayout.vue", "主框架"),
    ("/src/views/Login.vue", "登录"),
    ("/src/views/Dashboard.vue", "首页看板"),
    ("/src/views/WorkOrderList.vue", "工单管理"),
    ("/src/views/WorkOrderDetail.vue", "工单详情"),
    ("/src/views/TaskList.vue", "作业管理"),
    ("/src/views/FaultList.vue", "故障管理"),
    ("/src/views/FaultDetail.vue", "故障详情"),
    ("/src/views/Ledger.vue", "台账管理"),
    ("/src/views/Statistics.vue", "统计分析"),
    ("/src/views/Messages.vue", "消息中心"),
    ("/src/views/Reports.vue", "运维报告"),
    ("/src/views/ReportDetail.vue", "报告详情"),
    ("/src/views/NotFound.vue", "404"),
    ("/src/views/ai/AgentCenter.vue", "AI Agent 中心"),
    ("/src/views/ai/WorkOrderAgent.vue", "智能工单调度"),
    ("/src/views/ai/FaultDiagnosis.vue", "智能故障诊断"),
    ("/src/views/ai/RiskControl.vue", "智能风控"),
    ("/src/views/ai/Knowledge.vue", "知识库"),
    ("/src/views/ai/AgentTasks.vue", "Agent 任务"),
    ("/src/views/system/Users.vue", "用户管理"),
    ("/src/views/system/Roles.vue", "角色权限"),
    ("/src/views/system/Configs.vue", "参数与规则"),
    ("/src/views/system/Logs.vue", "日志审计"),
    ("/src/components/BaseChart.vue", "图表组件"),
    ("/src/components/StatCard.vue", "指标卡片"),
    ("/src/components/ImageUploader.vue", "图片上传组件"),
    ("/src/api/index.js", "接口封装"),
    ("/src/stores/user.js", "用户状态"),
    ("/src/router/index.js", "路由"),
]

PASS = 0
FAIL = 0
FAILURES: list[str] = []


def main() -> int:
    global PASS, FAIL
    c = httpx.Client(timeout=60.0)
    print("=" * 78)
    print("  前端页面编译验证（Vite 实时转换每个模块）")
    print("=" * 78)

    for path, label in ROUTES:
        try:
            r = c.get(f"{WEB}{path}")
            ok = r.status_code == 200 and len(r.text) > 50
            # Vite 编译失败会返回带 error 的 JS 或 500
            if ok and "Internal server error" in r.text:
                ok = False
            if ok and path.endswith(".vue") and "export default" not in r.text and "_sfc_main" not in r.text:
                ok = False
        except Exception as exc:
            ok = False
            r = None
            detail = f"{type(exc).__name__}: {exc}"
        else:
            detail = f"{r.status_code} {len(r.text)}B"

        if ok:
            PASS += 1
            print(f"  [PASS] {label:16s} {path}")
        else:
            FAIL += 1
            FAILURES.append(f"{label} {path} :: {detail}")
            print(f"  [FAIL] {label:16s} {path}  {detail}")

    c.close()
    print("=" * 78)
    print(f"  前端编译验证：PASS {PASS} / FAIL {FAIL}")
    if FAILURES:
        for f in FAILURES:
            print(f"    - {f}")
    print("=" * 78)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
