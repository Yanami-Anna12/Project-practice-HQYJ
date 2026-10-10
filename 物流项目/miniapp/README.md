# 司机端小程序（uni-app + Vue 3 + Vite）

车辆智能调度系统的**司机端**：司机用它看自己当天要跑的趟次、按顺序到店打卡、上报异常、收站内消息。

后端不在本目录，接口全部来自 `物流项目/backend`（FastAPI），本仓库只写前端，没有改动任何后端逻辑。

---

## 1. 环境要求

| 用途 | 要求 |
| --- | --- |
| Node.js | ≥ 18（本机实测 v24.9.0） |
| 包管理器 | **npm**（本机 pnpm 在链接阶段会卡死，请不要用 pnpm） |
| 后端 | 需先启动，见下文第 4 节 |
| 微信小程序 | 微信开发者工具（可选，只在跑小程序端时需要） |

## 2. 安装依赖

```bash
cd 物流项目/miniapp
npm install --registry=https://registry.npmmirror.com
```

## 3. 跑起来

### 3.1 H5（最快，浏览器里就能验证）

```bash
npm run dev:h5      # 开发服务器，默认 http://127.0.0.1:5173
npm run build:h5    # 生产构建，产物在 dist/build/h5
```

H5 开发态下接口走 Vite 代理（`vite.config.js` 里的 `/api` 与 `/uploads` → `http://127.0.0.1:8000`），
所以浏览器里没有跨域问题。**如果后端换了端口**，改 `vite.config.js` 的 proxy target，
或直接给 `src/config.js` 指定绝对地址。

### 3.2 微信小程序

```bash
npm run dev:mp-weixin      # 产物在 dist/dev/mp-weixin
```

然后：打开**微信开发者工具** → 导入项目 → 目录选 `物流项目/miniapp/dist/dev/mp-weixin`
（AppID 可选「测试号」）。

> ⚠️ **必须在开发者工具里勾选「不校验合法域名、web-view（业务域名）、TLS 版本以及 HTTPS 证书」**
> （详情 → 本地设置 → 勾选该项）。
> 否则 `http://127.0.0.1:8000` 这种 http 地址会被小程序拦截，页面会显示「无法连接后端服务」。

生产构建用 `npm run build:mp-weixin`（产物在 `dist/build/mp-weixin`）。

真机预览时 `127.0.0.1` 指向手机自己，**必须**把 `src/config.js` 里的 `DEV_HOST`
改成电脑的局域网 IP（如 `http://192.168.1.10:8000`），并保证手机与电脑同一网段。

## 4. 启动后端（接口依赖）

```bash
cd 物流项目/backend
C:\Users\12966\miniconda3\envs\py312\python.exe run.py
```

实际端口见 `backend/.runtime_port`（默认 `8000`）。

演示数据：如果「我的趟次」是空的，说明当天还没有**已下发**的趟次，
在后端目录跑一次 `python demo_mobile.py`（走真实的下发链路生成数据）。

## 5. 配置后端地址

**只改一个文件**：[`src/config.js`](src/config.js)

```js
const DEV_HOST = 'http://127.0.0.1:8000'   // 改这里即可
```

优先级：`src/config.js` 的显式配置 > 构建时环境变量 `VITE_API_BASE` > 按平台取默认值。

| 平台 | 默认地址 | 说明 |
| --- | --- | --- |
| H5 | 空（相对路径 `/api`） | 由 Vite 代理转发，无跨域 |
| 微信小程序 / App | `http://127.0.0.1:8000` | 小程序无同源限制，必须绝对地址 |

也可以用环境变量一键切换（不用改代码，**H5 端有效**）：

```bash
# H5 指向测试环境后端
VITE_API_BASE=http://127.0.0.1:8001 npm run dev:h5
```

> ⚠️ 小程序端构建不会静态替换 `VITE_API_BASE`（实测产物里是运行时兜底），
> **小程序换后端地址请直接改 `src/config.js` 的 `DEV_HOST`，然后重新构建**。

> ⚠️ 部署静态 H5（`dist/build/h5`）时注意：产物里 API 地址是**相对路径**，
> 需要给静态站点配一个把 `/api` 与 `/uploads` 转发到后端的反向代理（Nginx 等），
> 或者在构建前设 `VITE_API_BASE=http://后端地址` 重新构建。

> ⚠️ 小程序端改完 `src/config.js` 后**必须重新构建**（`npm run dev:mp-weixin`），
> 微信开发者工具读的是构建产物，改源码不会自动生效。

## 6. 演示账号

| 账号 | 密码 | 说明 |
| --- | --- | --- |
| `driver1` / `driver2` / `driver3` | `123456` | 司机账号，登录页可一键填入 |
| `admin` / `admin123` | 管理员（能看到菜单，但没有司机档案） |

登录复用管理端的 `POST /api/auth/login`，token 放在 `Authorization: Bearer <token>`。

## 7. 页面与接口对应

| 页面 | 路径 | 用到的接口 |
| --- | --- | --- |
| 登录 | `pages/login/login` | `POST /api/auth/login` |
| 我的趟次（首页） | `pages/trips/index` | `GET /api/mobile/my-trips`、`GET /api/mobile/notifications/unread-count` |
| 趟次详情 | `pages/trips/detail` | `GET /api/mobile/trips/{trip_key}`、`POST /api/mobile/checkin` |
| 异常上报 | `pages/exception/report` | `POST /api/mobile/files` → `POST /api/mobile/exceptions` |
| 消息中心 | `pages/messages/index` | `GET /api/mobile/notifications`、`POST /api/mobile/notifications/{id}/read` |
| 我的 | `pages/profile/index` | `GET /api/mobile/profile` |

tabBar：趟次 / 消息 / 我的（`src/pages.json`）。

## 8. 代码结构

```
src/
├── api/index.js        # 所有后端接口（页面只 import 这里，不直接调 uni.request）
├── config.js           # 后端地址、超时、演示账号（换地址只改这个文件）
├── utils/
│   ├── request.js      # uni.request / uni.uploadFile 封装：自动带 token、401 跳登录、409 交给页面
│   ├── storage.js      # token 与用户信息的本地缓存
│   ├── format.js       # 日期/状态/异常类型的展示口径
│   └── ui.js           # tabBar 未读红点、页面登录校验
├── pages/              # 6 个页面（<script setup> 写法，中文注释）
├── pages.json          # 页面注册 + tabBar
└── manifest.json       # 各端配置（h5 / mp-weixin）
```

## 9. 司机端的打卡状态机

后端对重复打卡会返回 **409**，前端必须给出友好提示（`pages/trips/detail.vue` 已处理）：

```
dispatched 待打卡 --[到店 arrive]--> arrived 已到店 --[离店 depart]--> done 已完成
                                                     --[完成 complete]--> done 已完成
```

* 「离店」和「完成」在服务端是**平行**的两个终态动作（都落 `done`），不是先离店再完成；
* 必须先「到店」才能「离店/完成」，否则后端返回 409；
* 门店状态 `planned`（未下发）时不能打卡，页面按钮置灰。

## 10. 已知限制

1. **不做微信登录、不做订阅消息**：后端没有 openid 体系，token 走账号密码登录；触达只有站内消息。
2. **打卡定位是尽力而为**：用户拒绝授权或定位失败时，打卡照常提交，只是不带经纬度。
3. **导航**：门店有经纬度用 `uni.openLocation`；没有经纬度时退化为复制地址（H5 端 `openLocation` 支持有限，同样会退回复制）。
4. **H5 端 `uni.makePhoneCall` 无效**（浏览器没有拨号能力），拨号按钮只在小程序/App 端有实际效果。
5. **H5 端 `uni.openLocation` 依赖在线地图服务**：浏览器里是打开地图网页，失败时代码已退化为「复制门店地址」。
6. **选图用的是 `uni.chooseImage`**：微信从基础库 2.21.0 起推荐 `uni.chooseMedia`，`chooseImage` 仍然可用（会有兼容提示）；若要彻底避免提示，换成 `chooseMedia` 即可，返回结构调整很小。
7. **离线容错**：所有列表页在请求失败时显示错误文案 +「重试」按钮，不会白屏。
