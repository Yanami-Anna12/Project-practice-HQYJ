"""API 路由包。

★ 本文件刻意不做任何再导出。
  各路由模块都需要 `from app.deps import authorize, get_current_user`，
  若这里再导入 app.deps，就形成 routers.__init__ → app.deps → app.services.rbac
  → app.models 的连锁导入，容易出现难以定位的循环导入错误。
  统一用完整路径导入子模块即可：

      from app.routers import auth, roles      # main.py 里这样用
"""
