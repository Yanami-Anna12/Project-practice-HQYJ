"""菜单定义与服务端裁剪。

★ 菜单树在这里定义，路由前缀与前端 src/api/menus.js **刻意保持一致**：
   接真实后端后，前端删除自己的 MENU_TREE，改为渲染 GET /api/me/menus 的结果。

裁剪规则：
  - 叶子节点：permission 不满足则剔除
  - 分组节点：所有子项都被剔除后，分组自身也不返回
"""

from __future__ import annotations

from typing import Any

MENU_TREE: list[dict[str, Any]] = [
    {
        "key": "dashboard",
        "title": "调度看板",
        "icon": "Odometer",
        "path": "/dashboard",
    },
    {
        "key": "base",
        "title": "业务基础数据",
        "icon": "OfficeBuilding",
        "children": [
            {"key": "base-stores", "title": "门店管理", "icon": "Shop", "path": "/base/stores", "permission": "stores:read"},
            {"key": "base-routes", "title": "线路管理", "icon": "Guide", "path": "/base/routes", "permission": "routes:read"},
            {"key": "base-mappings", "title": "门店线路映射", "icon": "Connection", "path": "/base/mappings", "permission": "routes:read"},
            {"key": "base-vehicles", "title": "车辆档案", "icon": "Van", "path": "/base/vehicles", "permission": "vehicles:read"},
            {"key": "base-vehicle-types", "title": "车辆类型", "icon": "Files", "path": "/base/vehicle-types", "permission": "vehicles:read"},
            {"key": "base-drivers", "title": "司机管理", "icon": "UserFilled", "path": "/base/drivers", "permission": "drivers:read"},
            {"key": "base-terrain", "title": "地形与通行规则", "icon": "Warning", "path": "/base/terrain", "permission": "terrain:manage"},
        ],
    },
    {
        "key": "rules",
        "title": "调度规则配置",
        "icon": "SetUp",
        "children": [
            {"key": "rules-load", "title": "装载量规则", "icon": "ScaleToOriginal", "path": "/rules/load", "permission": "vehicles:read"},
            {"key": "rules-trip", "title": "趟次规则", "icon": "Timer", "path": "/rules/trip", "permission": "vehicles:read"},
            {"key": "rules-strategy", "title": "调度策略与评分", "icon": "TrendCharts", "path": "/rules/strategy", "permission": "scheduling:read"},
            {"key": "rules-governance", "title": "规则版本治理", "icon": "DocumentChecked", "path": "/rules/governance", "permission": "scheduling:read"},
        ],
    },
    {
        "key": "assign",
        "title": "车辆分配管理",
        "icon": "Sort",
        "children": [
            {"key": "assign-available", "title": "可出勤车辆", "icon": "CircleCheck", "path": "/assign/available", "permission": "vehicles:read"},
            {"key": "assign-demand", "title": "门店配送需求", "icon": "ShoppingCart", "path": "/assign/demand", "permission": "stores:read"},
            {"key": "assign-result", "title": "分配结果", "icon": "Finished", "path": "/assign/result", "permission": "scheduling:read"},
        ],
    },
    {
        "key": "scheduling",
        "title": "智能调度 Agent",
        "icon": "MagicStick",
        "children": [
            {"key": "sched-tasks", "title": "调度任务", "icon": "List", "path": "/scheduling/tasks", "permission": "scheduling:read"},
            {"key": "sched-plans", "title": "多方案比选", "icon": "DataAnalysis", "path": "/scheduling/plans", "permission": "scheduling:read"},
            {"key": "sched-confirm", "title": "人工确认", "icon": "Select", "path": "/scheduling/confirm", "permission": "scheduling:confirm"},
            {"key": "sched-exception", "title": "异常重排", "icon": "RefreshRight", "path": "/scheduling/exception", "permission": "scheduling:replan"},
        ],
    },
    {
        "key": "reports",
        "title": "报表与看板",
        "icon": "PieChart",
        "children": [
            {"key": "reports-attendance", "title": "车辆出勤", "icon": "Calendar", "path": "/reports/attendance", "permission": "reports:view"},
            {"key": "reports-trip", "title": "趟次达成", "icon": "Checked", "path": "/reports/trip", "permission": "reports:view"},
            {"key": "reports-loadrate", "title": "装载率分析", "icon": "Histogram", "path": "/reports/loadrate", "permission": "reports:view"},
            {"key": "reports-store", "title": "门店配送达成", "icon": "Shop", "path": "/reports/store", "permission": "reports:view"},
            {"key": "reports-cost", "title": "成本与方案对比", "icon": "Money", "path": "/reports/cost", "permission": "reports:view"},
        ],
    },
    {
        "key": "system",
        "title": "系统管理",
        "icon": "Setting",
        "children": [
            {"key": "sys-users", "title": "用户管理", "icon": "User", "path": "/system/users", "permission": "users:read"},
            {"key": "sys-roles", "title": "角色管理", "icon": "Avatar", "path": "/system/roles", "permission": "roles:read"},
            {"key": "sys-permissions", "title": "权限管理", "icon": "Key", "path": "/system/permissions", "permission": "permissions:read"},
            {"key": "sys-dicts", "title": "字典管理", "icon": "Notebook", "path": "/system/dicts", "permission": "dicts:read"},
            {"key": "sys-params", "title": "参数管理", "icon": "Tools", "path": "/system/params", "permission": "params:read"},
            {"key": "sys-attachments", "title": "附件管理", "icon": "Paperclip", "path": "/system/attachments", "permission": "attachments:read"},
            {"key": "sys-logs", "title": "日志管理", "icon": "Document", "path": "/system/logs", "permission": "logs:read"},
        ],
    },
    {
        "key": "integration",
        "title": "集成与监控",
        "icon": "Link",
        "children": [
            {"key": "int-systems", "title": "接口集成配置", "icon": "Switch", "path": "/integration/systems", "permission": "integrations:manage"},
            {"key": "int-monitor", "title": "监控预警", "icon": "Bell", "path": "/integration/monitor", "permission": "monitor:read"},
        ],
    },
]


def build_menus(permission_set: set[str]) -> list[dict[str, Any]]:
    """按权限集合裁剪菜单树。"""

    def allowed(node: dict[str, Any]) -> bool:
        perm = node.get("permission")
        return not perm or perm in permission_set

    result: list[dict[str, Any]] = []
    for node in MENU_TREE:
        children = node.get("children")
        if not children:
            if allowed(node):
                result.append({k: v for k, v in node.items() if k != "permission"})
            continue

        kept = [{k: v for k, v in c.items() if k != "permission"} for c in children if allowed(c)]
        if kept:
            item = {k: v for k, v in node.items() if k != "children"}
            item["children"] = kept
            result.append(item)

    return result
