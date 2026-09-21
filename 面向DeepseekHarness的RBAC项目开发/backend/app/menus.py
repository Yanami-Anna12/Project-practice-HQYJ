"""菜单定义与权限裁剪。

为什么菜单「不建表」：
    菜单结构天然跟随前端路由走。若把菜单建成数据库表，就会出现
    「前端加一个页面」要同时改前端路由、改菜单表数据、改后端裁剪逻辑三处，
    维护成本远高于收益。RBAC 要管的对象是「权限点」，菜单只是权限点的一种视图。

本模块只负责「定义」与「按权限裁剪」；接口层在 routers/me.py。
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# 菜单树
# ---------------------------------------------------------------------------
# 字段约定：
#   key        唯一标识（前端做 keep-alive、选中态用）
#   title      显示名
#   path       前端路由路径（分组节点可为空）
#   icon       Element Plus 图标组件名
#   permission 访问该菜单所需权限码；None 表示登录即可见
#   children   子菜单
MENU_TREE: list[dict[str, Any]] = [
    {
        "key": "dashboard",
        "title": "工作台",
        "path": "/dashboard",
        "icon": "HomeFilled",
        "permission": None,  # 登录即可见
    },
    {
        "key": "products",
        "title": "商品管理",
        "path": "/products",
        "icon": "Goods",
        "permission": "products:read",
    },
    {
        "key": "orders",
        "title": "订单管理",
        "path": "/orders",
        "icon": "List",
        "permission": "orders:read",
    },
    {
        "key": "reports",
        "title": "数据报表",
        "path": "/reports",
        "icon": "TrendCharts",
        "permission": "reports:view",
    },
    {
        "key": "system",
        "title": "系统管理",
        "icon": "Setting",
        "path": None,  # 分组节点，本身不可点击
        "permission": "users:manage",
        "children": [
            {
                "key": "system-users",
                "title": "用户管理",
                "path": "/system/users",
                "icon": "User",
                "permission": "users:manage",
            },
            {
                "key": "system-roles",
                "title": "角色管理",
                "path": "/system/roles",
                "icon": "Avatar",
                "permission": "users:manage",
            },
            {
                "key": "system-permissions",
                "title": "权限点管理",
                "path": "/system/permissions",
                "icon": "Key",
                "permission": "users:manage",
            },
            {
                "key": "system-audit",
                "title": "审计日志",
                "path": "/system/audit",
                "icon": "Document",
                "permission": "users:manage",
            },
        ],
    },
]


def _node_permitted(node: dict[str, Any], permissions: set[str]) -> bool:
    """节点自身是否可见。permission 为 None 表示登录即可见。"""
    required = node.get("permission")
    return required is None or required in permissions


def filter_menus(
    permissions: set[str], tree: list[dict[str, Any]] | None = None
) -> list[dict[str, Any]]:
    """★ 按权限裁剪菜单树。

    关键点：裁剪在「服务端」完成，无权限的节点根本不返回给前端。
    相比之下「返回完整菜单树 + 前端过滤」有两个问题：
      1. 把管理端的菜单结构暴露给了无权访问的用户（信息泄露）；
      2. 前端过滤一旦写错，用户会看到点不动的死菜单。

    父节点处理：父节点自己有权限、但所有子节点都被裁掉时，父节点一并隐藏
    （否则会留下一个展开后空无一物的分组）。
    """
    source = MENU_TREE if tree is None else tree
    result: list[dict[str, Any]] = []

    for node in source:
        if not _node_permitted(node, permissions):
            continue

        item = {k: v for k, v in node.items() if k != "children"}

        if "children" in node:
            visible_children = filter_menus(permissions, node["children"])
            if not visible_children:
                # 分组节点下没有任何可见子项 —— 整个分组隐藏。
                # 例：某用户只有 users:manage 但子项权限都被改掉时不会出现空分组。
                continue
            item["children"] = visible_children

        result.append(item)

    return result


def all_menu_permissions() -> set[str]:
    """收集菜单树里出现的全部权限码（供测试与自检使用）。"""
    found: set[str] = set()

    def walk(nodes: list[dict[str, Any]]) -> None:
        for n in nodes:
            if n.get("permission"):
                found.add(n["permission"])
            if n.get("children"):
                walk(n["children"])

    walk(MENU_TREE)
    return found
