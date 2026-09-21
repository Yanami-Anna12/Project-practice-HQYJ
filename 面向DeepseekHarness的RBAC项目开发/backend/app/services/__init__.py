"""服务层包。

约定：所有跨表业务逻辑放这里，路由层只做「参数校验 + 调用 + 组装响应」。

★ 本文件刻意不做任何再导出（from app.services.rbac import ...）。
  原因：rbac.py 需要 `from app.services.audit import append_audit`，
  若 __init__ 再回头导入 rbac，就形成 services.rbac → services.__init__
  → services.rbac 的循环导入。统一用「完整路径导入子模块」最省心：

      from app.services import rbac      # 推荐
      from app.services.rbac import delete_role
"""
