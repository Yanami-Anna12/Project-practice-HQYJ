# RBAC 权限管理系统 · 设计说明书（第一阶段：数据表 + 接口骨架）

> 技术栈：FastAPI 0.138 + SQLAlchemy 2.0 + MySQL 8.0 + Vue 3 (Vite) + Pinia + Element Plus
> Python 运行时：`C:\Users\12966\miniconda3\envs\py312\python.exe`（3.12.13，依赖已就绪）
> 数据库：MySQL 8.0.42 @ 127.0.0.1:3306，库名 `rbac_db`，字符集 `utf8mb4`

---

## 0. 设计主线（先想清楚再写代码）

RBAC 的本质是四张表加两条边：

```
User ──(user_roles)──> Role ──(role_permissions)──> Permission
```

- 用户不直接持有权限，**只持有角色**
- 角色是「权限的集合」，权限点是最小粒度的字符串（如 `products:edit`）
- 每一次请求的鉴权只有一句话：**把用户所有角色的权限点求并集，判断目标权限是否在其中**

本设计刻意**不引入 Casbin 等授权引擎**，也不做会话级权限缓存，目的就是让这条链路完全可见可调试。

---

## 1. 数据表设计

### 1.1 ER 关系

```
┌──────────┐        ┌──────────────┐        ┌──────────┐        ┌────────────────────┐        ┌──────────────┐
│  users   │ 1    n │  user_roles  │ n    1 │  roles   │ 1    n │ role_permissions   │ n    1 │ permissions  │
│          ├────────┤              ├────────┤          ├────────┤                    ├────────┤              │
│ id (PK)  │        │ user_id  (FK)│        │ id (PK)  │        │ role_id       (FK) │        │ id (PK)      │
│ username │        │ role_id  (FK)│        │ code     │        │ permission_id (FK) │        │ code (UQ)    │
└────┬─────┘        └──────────────┘        └──────────┘        └────────────────────┘        └──────────────┘
     │ 1
     │ n
┌────┴──────────┐
│  audit_logs   │   ← 只追加，永不 UPDATE / DELETE
└───────────────┘
```

### 1.2 users — 用户表

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | INT | PK, AUTO_INCREMENT | |
| username | VARCHAR(50) | NOT NULL, **UNIQUE** | 登录名 |
| password_hash | VARCHAR(255) | NOT NULL | bcrypt 哈希，**绝不出现在任何响应中** |
| nickname | VARCHAR(50) | NULL | 显示名 |
| is_active | TINYINT(1) | NOT NULL, DEFAULT 1 | 停用后登录返回 401 |
| created_at | DATETIME | NOT NULL, DEFAULT now | |

> 注：用户不做软删除。删除用户时连带清理 `user_roles`（用户侧级联是合理的，与 R3 的角色侧保护不冲突）。

### 1.3 roles — 角色表

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | INT | PK, AUTO_INCREMENT | |
| code | VARCHAR(50) | NOT NULL, **UNIQUE** | `admin` / `operator` / `supplier` / `readonly` |
| name | VARCHAR(50) | NOT NULL | 中文名：管理员 / 运营 / 供应商 / 只读 |
| description | VARCHAR(200) | NULL | |
| is_active | TINYINT(1) | NOT NULL, DEFAULT 1 | 角色停用 → 其权限**整体退出并集**（R4） |
| created_at | DATETIME | NOT NULL, DEFAULT now | |

### 1.4 permissions — 权限点表

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | INT | PK, AUTO_INCREMENT | |
| code | VARCHAR(80) | NOT NULL, **UNIQUE** | `products:read` 等，即 `authorize()` 的入参 |
| name | VARCHAR(80) | NOT NULL | 中文名：查看商品 |
| module | VARCHAR(50) | NOT NULL | 所属模块：products / orders / reports / users / settings |
| is_active | TINYINT(1) | NOT NULL, DEFAULT 1 | **停用即失效，实时生效（R4）** |
| created_at | DATETIME | NOT NULL, DEFAULT now | |

**内置 6 个权限点**（即需求文档第 2 节的六行）：

| code | name | module |
|---|---|---|
| `products:read` | 查看商品 | products |
| `products:edit` | 编辑商品 | products |
| `orders:read` | 查看订单 | orders |
| `reports:view` | 查看报表 | reports |
| `users:manage` | 用户与权限管理 | users |
| `settings:edit` | 系统设置 | settings |

### 1.5 role_permissions — 角色-权限点关联表

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | INT | PK, AUTO_INCREMENT | 代理主键，便于后续审计 |
| role_id | INT | NOT NULL, FK→roles.id, ON DELETE CASCADE | |
| permission_id | INT | NOT NULL, FK→permissions.id, ON DELETE CASCADE | |

**唯一约束**：`UNIQUE(role_id, permission_id)` — 防重复绑定。

### 1.6 user_roles — 用户-角色关联表

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | INT | PK, AUTO_INCREMENT | |
| user_id | INT | NOT NULL, FK→users.id, ON DELETE CASCADE | |
| role_id | INT | NOT NULL, FK→roles.id, **ON DELETE RESTRICT** | ← **R3 在数据库层的兜底** |
| created_at | DATETIME | NOT NULL, DEFAULT now | 分配时间 |

**唯一约束**：`UNIQUE(user_id, role_id)` — 同一用户不重复绑同一角色。

> **关键设计点**：`ON DELETE RESTRICT` 让数据库成为 R3 的最后一道防线。即使应用层漏判，MySQL 也会用外键错误拒绝删除被引用的角色——应用层把该错误翻译成 409。这是「应用层校验 + 数据库约束」双保险。

### 1.7 audit_logs — 审计日志表（只追加，R5）

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | BIGINT | PK, AUTO_INCREMENT | |
| actor_id | INT | NULL, FK→users.id, ON DELETE SET NULL | 操作者 |
| actor_name | VARCHAR(50) | NOT NULL | **冗余快照**，操作者被删后日志仍可读 |
| action | VARCHAR(50) | NOT NULL | `role.create` / `role.delete` / `role.assign_permissions` / `user.assign_roles` / `permission.toggle` / `auth.login` |
| target_type | VARCHAR(30) | NULL | `role` / `user` / `permission` |
| target_id | INT | NULL | |
| detail | JSON | NULL | 变更详情（旧值/新值），中文可读 |
| created_at | DATETIME | NOT NULL, DEFAULT now | |

**「只追加」如何落实**：
1. 应用层只提供 `append_audit()` 一个写入口，**代码中不存在 UPDATE/DELETE audit_logs 的语句**；
2. ORM 层除 `POST` 追加外不暴露任何写接口给它；
3. 建表时对该表**不设**外键级联删除，`actor_id` 用 `SET NULL` 保留日志；
4. 验收时用 `grep` 证明代码库里没有对 `AuditLog` 的修改/删除调用。

### 1.8 建表 DDL 要点

```sql
CREATE DATABASE IF NOT EXISTS rbac_db
  DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;

-- user_roles.role_id 的 RESTRICT 是 R3 的数据库级保障
CONSTRAINT fk_ur_role FOREIGN KEY (role_id) REFERENCES roles(id) ON DELETE RESTRICT
```

---

## 2. 接口设计

### 2.1 统一响应约定

**成功**：直接返回业务数据（不额外包 `{code,data}` 信封，便于前端直取）。

**失败**：统一由全局异常处理器输出，与需求文档第 6 节完全一致。

| 场景 | 状态码 | 响应体 |
|---|---|---|
| 未登录 / Token 缺失、过期、非法 / 用户被停用 | 401 | `{"error": "未登录"}` |
| 已登录但无权限（含 R2 全部情形） | 403 | `{"error": "没有权限"}` |
| 删除被引用角色（R3） | 409 | `{"error": "该角色仍绑定 N 个用户，请先改绑"}` |
| 资源不存在 | 404 | `{"error": "资源不存在"}` |
| 参数校验失败 | 422 | `{"error": "参数校验失败", "detail": [...]}` |

### 2.2 接口清单

#### 认证

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| POST | `/api/auth/login` | 公开 | 登录，返回 JWT + 权限集合（**仅用于前端渲染**） |
| GET | `/api/me` | requireAuth | 当前用户信息 |
| GET | `/api/me/menus` | requireAuth | 返回**已按权限裁剪**的菜单树 |
| GET | `/api/me/permissions` | requireAuth | 当前用户有效权限码列表（前端按钮控制用） |

**POST /api/auth/login**
```jsonc
// 请求
{ "username": "admin", "password": "admin123" }
// 200
{
  "access_token": "eyJhbGciOi...",
  "token_type": "bearer",
  "expires_in": 7200,
  "user": { "id": 1, "username": "admin", "nickname": "系统管理员" },
  "roles": ["admin"],
  "permissions": ["products:read", "products:edit", "orders:read",
                  "reports:view", "users:manage", "settings:edit"]
}
// 401  { "error": "未登录" }   ← 用户名或密码错误、账号被停用
```

> **注意**：`permissions` 字段是给前端画界面用的。后端每个接口仍会**重新查库**算一遍权限，客户端伪造该字段不会获得任何实际权限。这一句会在 README 和代码注释里写明，是本次实践最核心的认知点。

#### 权限点管理（全部挂 `users:manage`）

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `/api/permissions` | `users:manage` | 权限点列表（含被多少角色引用） |
| POST | `/api/permissions` | `users:manage` | 新建权限点 |
| PATCH | `/api/permissions/{id}` | `users:manage` | **启停权限点**（`{"is_active": false}`）→ 触发 R4 |
| GET | `/api/roles/{id}/permissions` | `users:manage` | 某角色已绑定的权限码 |

#### 角色管理（全部挂 `users:manage`）

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `/api/roles` | `users:manage` | 角色列表（含权限码、绑定用户数） |
| POST | `/api/roles` | `users:manage` | 新建角色 + 绑定权限 |
| PUT | `/api/roles/{id}` | `users:manage` | 改名 / 改描述 / **整表重置权限绑定** |
| DELETE | `/api/roles/{id}` | `users:manage` | 删除角色，**被引用返回 409（R3）** |

**POST /api/roles**
```jsonc
{ "code": "auditor", "name": "审计员", "description": "只读审计",
  "permission_codes": ["products:read", "reports:view"] }
```

**PUT /api/roles/{id}** — `permission_codes` 为**全量覆盖**（不是增量追加），避免前端要做差集运算。

**DELETE /api/roles/{id}**
```jsonc
// 409
{ "error": "该角色仍绑定 3 个用户，请先改绑" }
// 200
{ "ok": true, "deleted": "auditor" }
```

#### 用户管理

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `/api/users` | `users:manage` | 用户列表（含角色码） |
| GET | `/api/users/{id}/roles` | `users:manage` | 某用户的角色 |
| PUT | `/api/users/{id}/roles` | `users:manage` | **用户-角色分配（全量覆盖）** → 触发 R1 |

**PUT /api/users/{id}/roles**
```jsonc
// 请求：运营 + 只读 → 验证 R1 并集
{ "role_codes": ["operator", "readonly"] }
// 200：返回结算后的并集，前端可立即看到权限变化
{ "user_id": 5, "roles": ["operator", "readonly"],
  "permissions": ["products:read", "products:edit",
                  "orders:read", "reports:view"] }
```

#### 业务接口（挂具体权限点）

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `/api/products` | `products:read` | 商品列表 |
| POST | `/api/products` | `products:edit` | 新建商品（供应商 403 验收点） |
| GET | `/api/reports/summary` | `reports:view` | 报表（只读 200 验收点） |

> 需求文档 4.2 表格中 `/api/orders` 只出现在权限矩阵里，未给出接口行。**我将补一个 `GET /api/orders` 挂 `orders:read`**，让权限矩阵的六行都有对应出口，便于验收演示。如不需要请告知。

#### 审计日志

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `/api/audit-logs` | `users:manage` | 审计日志查询（**只读，无任何写接口**） |

> 需求只要求「记录」日志，未要求查询接口。我加只读查询是为了**让 R5 可被验证**（能看到确实追加了）。同样，请确认是否需要。

### 2.3 菜单树的数据来源

菜单**不建表**，由后端常量定义 + 权限裁剪。理由：菜单结构随前端路由走，建表会带来前后端双份维护成本；而 RBAC 要管的是「权限点」，菜单只是权限点的视图。

```python
MENU_TREE = [
  {"key": "dashboard", "title": "工作台",   "path": "/dashboard", "icon": "HomeFilled", "permission": None},
  {"key": "products",  "title": "商品管理", "path": "/products",  "icon": "Goods",      "permission": "products:read"},
  {"key": "orders",    "title": "订单管理", "path": "/orders",    "icon": "List",       "permission": "orders:read"},
  {"key": "reports",   "title": "数据报表", "path": "/reports",   "icon": "TrendCharts","permission": "reports:view"},
  {"key": "system",    "title": "系统管理", "icon": "Setting", "permission": "users:manage",
   "children": [
     {"key": "users",       "title": "用户管理", "path": "/system/users",       "permission": "users:manage"},
     {"key": "roles",       "title": "角色管理", "path": "/system/roles",       "permission": "users:manage"},
     {"key": "permissions", "title": "权限点管理","path": "/system/permissions","permission": "users:manage"},
     {"key": "audit",       "title": "审计日志", "path": "/system/audit",       "permission": "users:manage"},
   ]},
]
```

`GET /api/me/menus` **在服务端就完成裁剪**：无权限的节点直接不返回，父节点若无任何可见子节点也一并隐藏。这样供应商登录后连「系统管理」这一栏都看不到——比返回全量再让前端过滤更安全（不泄露管理面结构）。

### 2.4 鉴权中间件：`authorize(permission)` 依赖链

**请求链路**：`requireAuth(401) → authorize('xxx')(403) → handler`

```
JWT (Authorization: Bearer xxx)
        │
        ▼
┌──────────────────────────────────────────────────────────┐
│ requireAuth                                              │
│  1. 解析 Bearer Token，无/过期/签名错 → 401 {"error":"未登录"} │
│  2. 取 sub(user_id) 查库拿 User                            │
│  3. 用户不存在 / is_active=0 → 401 {"error":"未登录"}        │
│  4. ★ 实时查库计算有效权限集合（R4：无任何缓存）              │
│       SELECT DISTINCT p.code                              │
│       FROM user_roles ur                                  │
│         JOIN roles r        ON r.id = ur.role_id AND r.is_active = 1
│         JOIN role_permissions rp ON rp.role_id = r.id      │
│         JOIN permissions p  ON p.id = rp.permission_id AND p.is_active = 1
│       WHERE ur.user_id = :uid                              │
│     → 结果挂到 request.state.permissions（set）              │
│  5. 返回 CurrentUser(id, username, roles, permissions)      │
└──────────────────────────────────────────────────────────┘
        │
        ▼
┌──────────────────────────────────────────────────────────┐
│ authorize("products:edit")  ← 闭包工厂，返回 Depends 可调用体  │
│  if perm not in user.permissions → 403 {"error":"没有权限"}  │
└──────────────────────────────────────────────────────────┘
        │
        ▼
      handler
```

**R4 实时生效的四个落点**（都必须实时查库，缺一不可）：

| 变更动作 | 生效机制 |
|---|---|
| 停用权限点 `permissions.is_active=0` | SQL 里 `AND p.is_active = 1` 过滤掉 |
| 停用角色 `roles.is_active=0` | SQL 里 `AND r.is_active = 1` 过滤掉 |
| 角色增删权限 `role_permissions` | 每次请求重新 JOIN |
| 用户改绑角色 `user_roles` | 每次请求重新 JOIN |

**R2 默认拒绝的三个落点**：

| 情形 | 结果 |
|---|---|
| 权限码在 `permissions` 表里根本不存在 | `authorize("ghost:perm")` → 不在集合中 → **403** |
| 用户无任何角色 | 并集为空集 → **403** |
| 权限点存在但 `is_active=0` | SQL 过滤掉 → **403** |

> 关键点：`authorize()` **不查 permissions 表判断权限点是否存在**。不存在 = 不在集合里 = 403。这样 R2 的三个情形收敛成同一个判断，实现极简且不会漏。

### 2.5 后端文件骨架

```
backend/
├── app/
│   ├── main.py                    # FastAPI 实例 / CORS / 全局异常处理器
│   ├── config.py                  # pydantic-settings，读 .env
│   ├── database.py                # engine / SessionLocal / Base / get_db
│   ├── deps.py                    # ★ requireAuth / authorize / CurrentUser  ← 核心
│   ├── security.py                # bcrypt 哈希 + JWT 签发解析
│   ├── menus.py                   # MENU_TREE 常量 + 按权限裁剪
│   ├── models/                    # users / roles / permissions / audit
│   ├── schemas/                   # 请求响应模型
│   ├── services/
│   │   ├── rbac.py                # ★ get_user_permissions() / 并集计算  ← 核心
│   │   └── audit.py               # ★ append_audit() 唯一写入口        ← 核心
│   └── routers/                   # auth / me / permissions / roles / users / products / orders / reports / audit
├── sql/
│   ├── 01_schema.sql              # 建库建表
│   └── 02_seed.sql                # 4 角色 + 6 权限点 + 绑定矩阵 + 5 个演示账号
├── tests/test_acceptance.py       # ★ pytest 覆盖 7 条验收标准
├── seed.py                        # 幂等初始化（可重复执行）
├── run.py                         # 启动脚本
└── requirements.txt
```

### 2.6 前端文件骨架

```
frontend/
├── src/
│   ├── api/            # request.js（axios 拦截器：注入 Token、401 跳登录）
│   │                   # auth.js / roles.js / users.js / permissions.js / products.js
│   ├── stores/         # auth.js  ← 保存 token/user/roles/permissions/menus；Pinia persist
│   ├── router/         # index.js + 全局前置守卫（登录态 + meta.permission 校验）
│   ├── directives/     # ★ permission.js  → v-permission="'products:edit'"  ← 按钮级控制
│   ├── utils/          # hasPermission(code) 工具函数
│   ├── layout/         # Sidebar（由 menus 动态渲染）/ Navbar / AppMain
│   └── views/          # Login / Dashboard / Products / Orders / Reports
│                       # System/{Users,Roles,Permissions,Audit}
└── vite.config.js      # 代理 /api → 127.0.0.1:8000
```

**双层权限控制（前端只是体验优化）**：

| 层 | 手段 | 效果 |
|---|---|---|
| 路由级 | `meta.permission` + 全局前置守卫 | 手输 URL 访问无权限页 → 拦截回 403 页 |
| 菜单级 | Sidebar 遍历 `/api/me/menus` | 无权限菜单**不渲染** |
| 按钮级 | `v-permission` 指令 | 「编辑商品」按钮无权限时**移除 DOM** |
| 接口级 | 后端 `authorize()` | **最终防线，永远生效** |

> 前端的 `permissions` 来自登录响应，用户可在浏览器控制台篡改 Pinia 状态让按钮重新出现——**但点击后后端仍然 403**。我会在验收测试里专门演示这一点。

### 2.7 种子数据（4 角色绑定矩阵，严格对齐需求第 2 节）

| 权限点 | admin | operator | supplier | readonly |
|---|:---:|:---:|:---:|:---:|
| products:read | ✓ | ✓ | ✓ | ✓ |
| products:edit | ✓ | ✓ | — | — |
| orders:read | ✓ | ✓ | — | ✓ |
| reports:view | ✓ | ✓ | — | ✓ |
| users:manage | ✓ | — | — | — |
| settings:edit | ✓ | — | — | — |

**演示账号**（密码统一 `123456`，bcrypt 入库）：

| 用户名 | 密码 | 角色 | 用途 |
|---|---|---|---|
| `admin` | `admin123` | admin | 全权限，管理端演示 |
| `operator` | `123456` | operator | 运营 |
| `supplier` | `123456` | supplier | 验收：POST /api/products → 403 |
| `readonly` | `123456` | readonly | 验收：GET 200 / POST 403 |
| `multi` | `123456` | operator + readonly | **验收 R1 并集** |

---

## 3. 与 7 条验收标准的对应关系

| # | 验收标准 | 设计上的保障 | 验证方式 |
|---|---|---|---|
| 1 | 四角色权限符合矩阵 | `02_seed.sql` 按矩阵精确写入 | pytest 参数化遍历 4 角色 × 6 权限 = 24 断言 |
| 2 | 供应商 POST /api/products → 403 | `authorize("products:edit")`，supplier 无此权限 | pytest |
| 3 | 只读 GET 200 / POST 403 | `products:read` ✓ / `products:edit` ✗ | pytest |
| 4 | 多角色并集 | `get_user_permissions()` 用 `DISTINCT` 求并集，无交集/最严逻辑 | pytest：`multi` 账号断言 4 个权限全在 |
| 5 | 删除被引用角色 → 409 含数量 | `services/rbac.py` 先 `COUNT(*)` 判引用数，DB 层 RESTRICT 兜底 | pytest 断言状态码 + 文案含数字 |
| 6 | 停用权限点立即生效 | SQL 实时过滤 `p.is_active=1`，无缓存 | pytest：同一 Token 停用前后各请求一次，403 立即出现 |
| 7 | 前端菜单动态渲染 | `/api/me/menus` 服务端裁剪 | pytest 断言 supplier 菜单不含「系统管理」；前端手动核对 |

---

## 4. 待你确认的 3 个决策点

1. **`GET /api/orders`** — 需求表格未列出，我打算补上以让权限矩阵六行都有出口，是否可以？
2. **`GET /api/audit-logs`** — 需求只要求「记录」，我打算加只读查询以便验证 R5，是否可以？
3. **前端 UI 库** — 用 Element Plus（表格/表单/弹窗现成，界面完成度高）还是手写轻量样式（依赖更少）？

> 另：需求 4.2 的 `/api/permissions` 写的是「GET/POST」，我额外加了 `PATCH /api/permissions/{id}` 用于**启停权限点**——否则验收第 6 条无法操作触发。这一点也请一并确认。

---

**确认后我将按以下顺序逐模块生成代码**（每步可独立运行验证）：

1. 基础设施：`config.py` / `database.py` / `models/` / SQL 建表脚本
2. `security.py`（bcrypt + JWT）+ `services/rbac.py`（并集计算）+ `seed.py`
3. `deps.py`（requireAuth / authorize）+ 全局异常处理器 → **先跑通 401/403 两条链路**
4. 业务路由：auth / me / products / orders / reports
5. 管理路由：permissions / roles / users / audit（含 R3 的 409、R5 的日志）
6. `tests/test_acceptance.py` → **一次性跑出 7 条验收结果**
7. 前端：脚手架 → api/stores/router → 权限指令与守卫 → 各业务页面
