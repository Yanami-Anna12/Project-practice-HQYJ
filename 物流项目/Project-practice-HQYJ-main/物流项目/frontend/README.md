# 车辆智能调度 Agent · 前端

Vue 3 + Vite 6 + Pinia + Vue Router 4 + Element Plus 2 + ECharts 5。

**项目总览与快速开始见上级目录的 `README.md`**，本文件只讲前端。

---

## 启动

```bash
pnpm install
pnpm run dev      # http://127.0.0.1:5175
```

需要后端同时运行（`../backend`，默认 8000）。开发模式下 Vite 把 `/api`
代理到 `http://127.0.0.1:8000`，无跨域问题。

---

## 页面清单（共 24 个业务页面）

### 调度看板
| 路由 | 说明 |
| --- | --- |
| `/dashboard` | 车辆规模、日趟次上限、核心业务约束、Agent 工作流 |

### 业务基础数据（7 页）
| 路由 | 说明 |
| --- | --- |
| `/base/stores` | 门店管理（地形、配送时段、交界门店标记） |
| `/base/routes` | 线路管理（地形覆盖、禁限行） |
| `/base/mappings` | 门店线路映射（多对多 + 优先级 + 交界门店概览） |
| `/base/vehicles` | 车辆档案（地形能力、可跑线路、司机绑定） |
| `/base/vehicle-types` | 车型能力配置（装载量区间、趟次拆分） |
| `/base/drivers` | 司机管理（班次、请假状态） |
| `/base/terrain` | 地形与通行规则（可点击切换的通行矩阵） |

### 调度规则配置（4 页）
| 路由 | 说明 |
| --- | --- |
| `/rules/load` | 装载量规则（复用车型能力配置） |
| `/rules/trip` | 趟次规则（复用车型能力配置） |
| `/rules/strategy` | 调度策略与评分（硬/软约束清单、冲突检测、评分公式） |
| `/rules/governance` | 规则版本治理（发布 / 变更对比 / 回滚） |

### 车辆分配管理（3 页）
| 路由 | 说明 |
| --- | --- |
| `/assign/available` | 可出勤车辆（含不可出勤原因、与计划保有量对比） |
| `/assign/demand` | 门店配送需求（当日货量，调度的输入） |
| `/assign/result` | 分配结果（各次调度的方案与指标汇总） |

### 智能调度 Agent（4 页）
| 路由 | 说明 |
| --- | --- |
| `/scheduling/tasks` | 调度任务（创建调度、可行性预检、多方案比选、方案明细、报告） |
| `/scheduling/plans` | 多方案比选（方案卡片 + 指标横向对比 + 最优值高亮） |
| `/scheduling/confirm` | 人工确认（确认 / 驳回 / 下发，幂等提示） |
| `/scheduling/exception` | 异常重排（上报异常、重排上限可视化） |

### 报表与看板（5 页）
| 路由 | 说明 |
| --- | --- |
| `/reports/attendance` | 车辆出勤（计划保有量 vs 实际出车） |
| `/reports/trip` | 趟次达成（含大包小包保障达成） |
| `/reports/loadrate` | 装载率分析（分布 + 各车型） |
| `/reports/store` | 门店配送达成（线路覆盖 + 交界门店归属验证） |
| `/reports/cost` | 成本与方案对比 |

### 系统管理（7 页）
`/system/users` `/system/roles` `/system/permissions` `/system/dicts`
`/system/params` `/system/attachments` `/system/logs`

### 集成与监控（2 页）
| 路由 | 说明 |
| --- | --- |
| `/integration/systems` | 接口集成配置（如实标注未连通 + 本地落地证据） |
| `/integration/monitor` | 监控预警（真实指标 + 数据推导的预警） |

---

## 目录结构

```
src/
├── api/
│   ├── index.js       ★ 数据访问层 —— 所有接口调用都在这里
│   ├── request.js     axios 实例 + 401/403 拦截器
│   └── meta.js        模块元信息、动作码中文名
├── components/
│   └── EChart.vue     ECharts 轻量封装（按需注册 + 自动 resize）
├── directives/
│   └── permission.js  按钮级权限指令 v-permission
├── layout/            侧边栏 / 顶栏 / 主布局
├── router/index.js    路由定义与权限守卫
├── stores/auth.js     登录态与权限
├── styles/index.css   全局样式
├── utils/
│   ├── crud.js        ★ 列表页 CRUD 通用逻辑
│   ├── enums.js       业务枚举中文标签（取值与后端 seed 一致）
│   ├── error.js       统一错误处理
│   ├── permission.js  usePermission 组合式函数
│   ├── reportDate.js  报表页共用的日期选择
│   ├── storage.js     localStorage 读写
│   └── table.js       列表页加载 + 格式化
└── views/             24 个业务页面
```

---

## 权限如何生效

三道界面控制只是**体验优化**，真正的把关在后端：

1. **菜单级** —— 侧边栏渲染 `GET /api/me/menus` 返回的树，后端已按权限裁剪
2. **路由级** —— `meta.permission` 声明，守卫拦截并跳 403
3. **按钮级** —— `v-permission="'users:manage'"` 指令，无权限直接不渲染
4. **接口级** —— 后端 `require_permission()` 独立复核，绕过界面也拦得住

可以验证：用 `viewer` 登录后侧边栏没有「系统管理」「集成与监控」；
手动访问 `/integration/monitor` 会被守卫拦到 403 页。

---

## 自检

```bash
pnpm run dev                  # 需保持运行
node scripts/verify-ui.mjs            # 30 项：系统管理 + 基础数据 + 权限裁剪
node scripts/verify-edit-save.mjs     # 15 项：各编辑弹窗的保存回归
node scripts/verify-scheduling.mjs    # 18 项：车辆分配 + 调度页面
node scripts/verify-reports.mjs       # 14 项：5 个报表页 + 图表渲染
node scripts/verify-rules-monitor.mjs # 29 项：规则配置 + 监控集成
node scripts/compile-check.mjs        # 40 个 .vue 的模板编译检查
node scripts/check-form-fields.mjs    # 静态检查：禁用字段是否已回填

# 或一次跑全部：
node scripts/verify-all.mjs
```

基于 Playwright-core，用**本机已装的 Chrome**，不下载额外浏览器。
所有脚本都会收集控制台错误，正常运行应为 0 条。截图输出到 `.verify/`。

`compile-check.mjs` 尤其有用：它用 Vue 官方编译器解析模板，
能定位到具体行号 —— 排查「模板属性写错导致 500」这类问题比看浏览器报错快得多。

---

## 四个踩过的坑（已在代码注释里标注）

1. **编辑弹窗里「只读 + 必填」的字段必须回填。**
   门店编码、线路编码、车牌号、工号在编辑时是禁用（只读）的，但校验规则
   仍然要求它们必填。如果 `toForm` 不回填这些字段，输入框是灰的、
   里面是空的，点保存就被"请输入 xxx"拦住 —— **编辑功能直接不可用**。
   这个 bug 同时存在于 4 个页面，靠 `scripts/check-form-fields.mjs`
   静态扫描才确认了范围，靠 `scripts/verify-edit-save.mjs` 做回归防护。

2. **Vue 模板只对顶层 setup 绑定做 ref 自动解包。**
   把组合式函数返回的 ref 塞进普通对象（`const crud = useCrud()` 然后 `crud.rows`），
   模板里拿到的是 `RefImpl` 而不是数组，`el-table` 会报 "rows is not iterable"。
   正确做法是顶层解构。见 `utils/crud.js` 文件头。

3. **模板属性不能这么写：`:color="#67c23a"`。**
   `:` 前缀让 Vue 把值当 JS 表达式解析，`#67c23a` 是语法错误，
   会导致整个组件编译失败（Vite 返回 500）。要么去掉 `:`，要么写 `:color="'#67c23a'"`。

4. **菜单不要缓存到 localStorage。**
   菜单是服务端的授权状态，缓存后会出现「后台加了新菜单 / 改了权限，
   用户不重新登录就一直看不到」。见 `stores/auth.js` 的 `loadMenus()`。

---

## 已知限制

1. **附件不做真实上传**：只登记文件名与大小。
2. **图表数据依赖已跑过调度**：没有调度任务的日期，报表页会显示空图表并说明原因。
3. **成本是相对系数**：用于方案间相对比较，不是真实金额，页面上已标注。
4. **监控页不展示未采集的指标**：API QPS、P95 延迟等需外部监控栈，
   页面明确标注「未接入」而不是编数字。
