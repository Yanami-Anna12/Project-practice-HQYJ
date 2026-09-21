# RBAC 权限管理系统

基于 **Vue 3 + FastAPI + MySQL** 的角色访问控制系统。实现了用户/角色/权限点的完整管理，
并在**后端接口层**与**前端菜单/按钮层**同时落实权限校验。

- 后端：FastAPI 0.138 + SQLAlchemy 2.0 + MySQL 8.0 + PyJWT + bcrypt
- 前端：Vue 3 + Vite 6 + Pinia + Element Plus + axios
- 测试：pytest，**74 项全部通过**，覆盖需求文档的 7 条验收标准

---

## 一、快速开始

### 1. 环境要求

| 组件 | 版本 | 本机实测 |
|---|---|---|
| Python | 3.11+ | `C:\Users\12966\miniconda3\envs\py312\python.exe`（3.12.13） |
| MySQL | 8.0+ | 8.0.42 @ 127.0.0.1:3306 |
| Node.js | 18+ | v24.9.0 |
| pnpm | 8+ | 10.34.5 |

### 2. 后端

```powershell
cd backend

# 依赖（本机 py312 环境已预装，此步用于换机复现）
& "C:\Users\12966\miniconda3\envs\py312\python.exe" -m pip install -r requirements.txt

# 配置数据库连接：复制 .env.example 为 .env 并填入 MySQL 密码
# 建库建表 + 灌入种子数据（幂等，可反复执行）
& "C:\Users\12966\miniconda3\envs\py312\python.exe" seed.py

# 启动（接口文档 http://127.0.0.1:8000/docs）
& "C:\Users\12966\miniconda3\envs\py312\python.exe" run.py
```

`seed.py` 执行后会打印权限矩阵，可直接对照需求文档第 2 节逐格核验。

### 3. 前端

```powershell
cd frontend
pnpm install
pnpm run dev        # http://127.0.0.1:5173，已配置 /api 代理到后端
```

浏览器打开 <http://127.0.0.1:5173>。

### 4. 演示账号

| 用户名 | 密码 | 角色 | 权限数 | 特点 |
|---|---|---|---|---|
| `admin` | `admin123` | 管理员 | 6 | 全部权限，可进管理端 |
| `operator` | `123456` | 运营 | 4 | 可编辑商品，不能进管理端 |
| `supplier` | `123456` | 供应商 | 1 | 只有 `products:read` |
| `readonly` | `123456` | 只读 | 3 | 只读订单与报表 |
| `multi` | `123456` | 运营 + 只读 | 4 | **★ 验证 R1 并集** |

登录页提供了一键填充，切换账号能立刻看到菜单与按钮的变化。

---

## 二、运行测试

```powershell
cd backend
& "C:\Users\12966\miniconda3\envs\py312\python.exe" -m pytest
```

74 项测试按验收标准分组命名，可以直接对照：

```
Test标准1_四角色权限矩阵        32 项   4 角色 × 6 权限逐格核对
Test标准2_供应商不能编辑商品      2 项
Test标准3_只读角色边界          4 项
Test标准4_多角色并集            4 项
Test标准5_删除被引用角色         4 项
Test标准6_权限变更实时生效        3 项
Test标准7_菜单按权限裁剪         6 项
TestT1_错误响应规范            4 项
TestT2_默认拒绝fail_closed    3 项
TestT3_前端伪造权限无效          2 项   ★ 本项目核心认知点
TestT4_审计日志只追加           3 项
TestT5_防自锁与边界            6 项
TestT6_权限点为空的边界          1 项
```

只跑某一条验收标准：

```powershell
python -m pytest -k "标准5 or 标准6"
```

另外有两个独立的诊断脚本：

| 脚本 | 用途 |
|---|---|
| `backend/check_schema_parity.py` | 校验 ORM 模型与 `sql/01_schema.sql` 的结构一致性（防止两份定义漂移），并实测 R3 的数据库外键兜底 |
| `backend/check_auth_flow.py` | 鉴权链路端到端自检（41 项），失败时逐条打印实际状态码 |

前端静态检查（发现"图标名写错""权限码不存在"这类只在运行时暴露的问题）：

```powershell
cd frontend
node scripts/check-frontend.mjs
```

---

## 三、核心设计

### 3.1 数据模型

RBAC 的本质是四张表加两条边：

```
User ──(user_roles)──> Role ──(role_permissions)──> Permission
```

**用户不直接持有权限，只持有角色。** 所有权限都通过角色间接获得。

| 表 | 关键设计 |
|---|---|
| `users` | 密码只存 bcrypt 哈希，绝不出现在任何响应中 |
| `roles` | `is_active=0` 时其权限整体退出并集 |
| `permissions` | `code` 即 `authorize()` 的入参，全局唯一 |
| `role_permissions` | `UNIQUE(role_id, permission_id)` 防重复绑定 |
| `user_roles` | **`role_id` 外键 `ON DELETE RESTRICT`** ← R3 的数据库级兜底 |
| `audit_logs` | `actor_id` 用 `SET NULL`（操作者被删日志仍在）+ `actor_name` 冗余快照 |

### 3.2 鉴权链路

```
JWT (Authorization: Bearer xxx)
        │
        ▼
   requireAuth          无 Token / 过期 / 非法 / 用户被停用 → 401 {"error":"未登录"}
        │                ★ 实时查库计算有效权限，无任何缓存
        ▼
   authorize('xxx')     权限不在集合中 → 403 {"error":"没有权限"}
        │
        ▼
     handler
```

**有效权限的计算就是一条 SQL**（`app/services/rbac.py`）：

```sql
SELECT DISTINCT p.code
FROM user_roles ur
  JOIN roles             r  ON r.id  = ur.role_id       AND r.is_active = 1
  JOIN role_permissions  rp ON rp.role_id = r.id
  JOIN permissions       p  ON p.id  = rp.permission_id AND p.is_active = 1
WHERE ur.user_id = :uid
```

这一条查询同时承载了三条业务规则：

| 规则 | 实现方式 |
|---|---|
| **R1 多角色并集** | `DISTINCT` 天然求并集，**没有任何取交集/取最严的逻辑** |
| **R2 默认拒绝** | 权限点不存在 ⇒ 不在集合中 ⇒ 403。三种 fail-closed 情形收敛成同一判断 |
| **R4 实时生效** | 每次请求重新执行，`is_active` 在 SQL 里过滤，**无 lru_cache / 无会话缓存** |

### 3.3 五条业务规则的落点

| 规则 | 主要实现位置 |
|---|---|
| R1 多角色并集 | `services/rbac.py` → `effective_permissions()` |
| R2 默认拒绝 | `services/rbac.py` → `has_permission()` + 上述 SQL 的 `is_active` 过滤 |
| R3 删除角色保护 | `services/rbac.py` → `delete_role()`（应用层 COUNT）+ `models/associations.py`（外键 RESTRICT） |
| R4 权限实时生效 | `deps.py` → `get_current_user()` 每次请求重新查库 |
| R5 审计只追加 | `services/audit.py` → `append_audit()` 唯一写入口，只有 INSERT |

### 3.4 前端双层控制

| 层 | 手段 | 效果 |
|---|---|---|
| 菜单级 | 侧边栏渲染 `/api/me/menus` | **服务端已裁剪**，无权限节点根本不返回 |
| 路由级 | `meta.permission` + 全局守卫 | 手输 URL 访问无权限页 → 跳到提示页 |
| 按钮级 | `v-permission="'products:edit'"` | 无权限时移除 DOM（`.disable` 修饰符则置灰） |
| 接口级 | 后端 `authorize()` | **最终防线，永远生效** |

> ### ★ 一个必须理解的认知点
>
> 登录响应里的 `permissions` 字段**只是给前端渲染界面用的**，保存在浏览器里，
> 可以在控制台随意篡改。
>
> 把它改成全权限后，菜单和按钮确实会出现 —— 但**点下去后端照样返回 403**。
> 因为后端每个接口都会重新查库计算权限，从不信任客户端传来的任何权限声明。
>
> 这不是漏洞，而是设计如此。需求文档里「菜单和按钮的隐藏仅作为体验优化，
> 后端接口始终是最终防线」这句话，在代码上的确切含义就是：
> **前端隐藏 ≠ 安全控制。**
>
> 想亲眼验证：用 `supplier` 登录，打开商品管理页，
> 点「直接提交请求」按钮 —— 它会绕过界面按钮直接调接口，结果必然是 403。

---

## 四、接口清单

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| POST | `/api/auth/login` | 公开 | 登录，返回 JWT + 权限集合 |
| GET | `/api/me` | 登录 | 当前用户信息 |
| GET | `/api/me/permissions` | 登录 | 当前用户有效权限码 |
| GET | `/api/me/menus` | 登录 | **已按权限裁剪**的菜单树 |
| GET | `/api/permissions` | `users:manage` | 权限点列表 |
| POST | `/api/permissions` | `users:manage` | 新建权限点 |
| PATCH | `/api/permissions/{id}` | `users:manage` | **启停权限点**（R4 操作入口） |
| GET | `/api/roles` | `users:manage` | 角色列表（含绑定用户数） |
| POST | `/api/roles` | `users:manage` | 新建角色 + 绑定权限 |
| PUT | `/api/roles/{id}` | `users:manage` | 更新角色 / 全量重置权限 |
| DELETE | `/api/roles/{id}` | `users:manage` | **删除角色，被引用返回 409** |
| GET | `/api/roles/{id}/permissions` | `users:manage` | 角色已绑定的权限码 |
| GET | `/api/users` | `users:manage` | 用户列表（含角色与并集权限） |
| GET | `/api/users/{id}/roles` | `users:manage` | 某用户的角色 |
| PUT | `/api/users/{id}/roles` | `users:manage` | **用户-角色分配（R1 并集）** |
| GET | `/api/products` | `products:read` | 商品列表 |
| POST | `/api/products` | `products:edit` | 新建商品 |
| GET | `/api/orders` | `orders:read` | 订单列表 |
| GET | `/api/reports/summary` | `reports:view` | 报表汇总 |
| GET | `/api/audit-logs` | `users:manage` | 审计日志（**只读**） |

### 错误响应规范

| 场景 | 状态码 | 响应体 |
|---|---|---|
| 未登录 / Token 失效 / 用户被停用 | 401 | `{"error": "未登录"}` |
| 已登录但无权限 | 403 | `{"error": "没有权限"}` |
| 删除被引用的角色 | 409 | `{"error": "该角色仍绑定 N 个用户，请先改绑"}` |
| 资源不存在 | 404 | `{"error": "资源不存在"}` |
| 参数校验失败 | 422 | `{"error": "参数校验失败", "detail": [...]}` |

所有错误响应只在 `app/main.py` 的 `register_exception_handlers()` 里定义一处，
业务代码只抛 `AppError` 子类，不需要知道 HTTP 状态码。

---

## 五、目录结构

```
项目实践/
├── docs/DESIGN.md                设计说明书（数据表 + 接口骨架）
├── backend/
│   ├── app/
│   │   ├── main.py               应用入口 + 统一异常处理（错误规范的唯一出处）
│   │   ├── config.py             配置（注意 database_url 的密码渲染坑）
│   │   ├── database.py           engine / Session / 建库建表
│   │   ├── deps.py               ★ requireAuth / authorize（鉴权链路）
│   │   ├── security.py           bcrypt 哈希 + JWT 签发解析
│   │   ├── errors.py             领域异常 → HTTP 状态码映射
│   │   ├── menus.py              菜单树定义 + 按权限裁剪
│   │   ├── schemas.py            Pydantic 请求/响应模型
│   │   ├── models/               8 张表的 ORM 定义
│   │   ├── services/
│   │   │   ├── rbac.py           ★ 有效权限计算（R1/R2/R3/R4）
│   │   │   └── audit.py          ★ 审计日志唯一写入口（R5）
│   │   └── routers/              9 个路由模块
│   ├── sql/01_schema.sql         与 ORM 逐字对应的参考 DDL
│   ├── tests/test_acceptance.py  74 项验收测试
│   ├── seed.py                   种子数据（幂等）
│   ├── run.py                    启动脚本
│   ├── check_schema_parity.py    结构一致性守卫
│   └── check_auth_flow.py        鉴权链路端到端自检
└── frontend/
    ├── src/
    │   ├── api/                  axios 实例 + 接口定义
    │   ├── stores/auth.js        Pinia 登录态与权限状态
    │   ├── router/index.js       路由 + 全局权限守卫
    │   ├── directives/permission.js  ★ v-permission 按钮级权限
    │   ├── utils/                权限判定工具 + 本地存储
    │   ├── layout/               Sidebar（动态菜单）/ Navbar / AppLayout
    │   └── views/                12 个页面
    └── scripts/check-frontend.mjs 前端静态一致性检查
```

---

## 六、验收自查路径

按需求文档第 7 节逐条操作（也可以直接跑 `pytest`）：

| # | 验收标准 | 手工验证方式 |
|---|---|---|
| 1 | 四角色权限符合矩阵 | 分别用 4 个账号登录，看工作台的权限矩阵高亮行 |
| 2 | 供应商 POST 商品 403 | `supplier` 登录 → 商品页 → 点「直接提交请求」→ 403 |
| 3 | 只读 GET 200 / POST 403 | `readonly` 登录 → 商品列表正常显示，但无「新建」按钮 |
| 4 | 多角色并集 | `multi` 登录，权限含 `products:edit`（只读角色没有这个） |
| 5 | 删除被引用角色 409 | 管理端 → 角色管理 → 删除内置角色被拒，提示含绑定用户数 |
| 6 | 停用权限点立即生效 | 管理端 → 权限点管理 → 点「开始验证」，观察 200 → 403 的跳变 |
| 7 | 菜单动态渲染 | 切换 4 个账号，观察左侧菜单数量变化（供应商只有 2 项） |

---

## 七、已知限制

- **MySQL 版本**：`audit_logs.detail` 用了 `JSON` 列类型，需要 MySQL 5.7.8+；
  5.7 以下需改为 `TEXT`。
- **`GET /api/orders` 是补充接口**：需求文档 4.2 的接口表未列出订单接口，
  但第 2 节权限矩阵有 `orders:read`。为了让矩阵每一行都有对应用口便于验收，
  补了只读接口（无写接口，因为矩阵里订单没有写权限点）。
- **`PATCH /api/permissions/{id}` 是补充接口**：需求 4.2 只写了 `GET/POST`，
  但没有启停接口就无法触发验收标准 6，因此补上。
- **`GET /api/audit-logs` 是补充接口**：需求只要求"记录"日志，
  加只读查询是为了让 R5 可被验证（能看到日志确实被追加）。
- **额外保护**：`PUT /api/users/{id}/roles` 会拒绝「移除最后一个管理员」。
  需求未要求，但系统一旦失去最后一个管理员，所有管理接口都会 403，
  只能手工改数据库恢复 —— 这类不可逆自锁必须提前拦。
- **审计日志无归档机制**：只追加表会持续增长，生产环境需要配套的归档策略。
