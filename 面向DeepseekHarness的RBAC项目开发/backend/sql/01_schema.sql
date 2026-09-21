-- =============================================================================
-- RBAC 权限管理系统 · 建库建表脚本（参考实现，与 ORM 定义逐字对应）
-- =============================================================================
-- 【重要】唯一真源是 app/models/ 下的 SQLAlchemy 模型。
--   本文件由模型元数据导出，等价于 `Base.metadata.create_all()` 的产物，
--   目的是让你在 Navicat / DataGrip 里能直观看到表结构，也支持手工建库。
--
--   推荐做法：直接 `python seed.py`（它内部调用 create_all 建表 + 灌种子数据），
--   这样永远不会出现「SQL 脚本」与「ORM 模型」两边改不同步的结构漂移。
--
--   手工建库的顺序：
--     mysql -u root -p < 01_schema.sql
--     python seed.py                      -- 表已存在则跳过建表，只灌数据
--
-- 【可移植性说明】
--   时间戳默认值用 `DEFAULT CURRENT_TIMESTAMP`（可移植写法），
--   而不是 `DEFAULT (now())`（MySQL 8.0.13+ 的表达式默认值语法，5.7 会报语法错）。
--   在 ORM 侧对应 database.now_default()，注意不要改回 func.now()。
--
-- 【MySQL 版本要求】8.0+（JSON 列类型）。8.0.13 以下需自行降级为 TEXT。
-- =============================================================================

CREATE DATABASE IF NOT EXISTS `rbac_db`
  DEFAULT CHARACTER SET utf8mb4
  COLLATE utf8mb4_0900_ai_ci;

USE `rbac_db`;

-- -----------------------------------------------------------------------------
-- 1. users —— 用户表
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `users` (
  `id`            INT          NOT NULL AUTO_INCREMENT,
  `username`      VARCHAR(50)  NOT NULL COMMENT '登录名，全局唯一',
  `password_hash` VARCHAR(255) NOT NULL COMMENT 'bcrypt 哈希；绝不存明文，绝不出现在响应中',
  `nickname`      VARCHAR(50)  DEFAULT NULL COMMENT '显示名',
  `is_active`     TINYINT(1)   NOT NULL DEFAULT 1 COMMENT '停用后登录一律 401',
  `created_at`    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `ix_users_username` (`username`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='用户表';

-- -----------------------------------------------------------------------------
-- 2. roles —— 角色表
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `roles` (
  `id`          INT          NOT NULL AUTO_INCREMENT,
  `code`        VARCHAR(50)  NOT NULL COMMENT '角色标识：admin/operator/supplier/readonly',
  `name`        VARCHAR(50)  NOT NULL COMMENT '中文名',
  `description` VARCHAR(200) DEFAULT NULL,
  `is_active`   TINYINT(1)   NOT NULL DEFAULT 1 COMMENT '停用后其权限整体退出并集（R4）',
  `created_at`  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `ix_roles_code` (`code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='角色表';

-- -----------------------------------------------------------------------------
-- 3. permissions —— 权限点表
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `permissions` (
  `id`         INT         NOT NULL AUTO_INCREMENT,
  `code`       VARCHAR(80) NOT NULL COMMENT '权限码「模块:动作」，即 authorize() 的入参',
  `name`       VARCHAR(80) NOT NULL COMMENT '中文名',
  `module`     VARCHAR(50) NOT NULL COMMENT '所属模块',
  `is_active`  TINYINT(1)  NOT NULL DEFAULT 1 COMMENT '★ R4：置 0 后所有持有者下次请求立即被拒',
  `created_at` DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `ix_permissions_code` (`code`),
  KEY `ix_permissions_module` (`module`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='权限点表';

-- -----------------------------------------------------------------------------
-- 4. role_permissions —— 角色-权限点关联表
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `role_permissions` (
  `id`            INT NOT NULL AUTO_INCREMENT,
  `role_id`       INT NOT NULL,
  `permission_id` INT NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_role_permission` (`role_id`, `permission_id`),
  KEY `ix_role_permissions_role_id` (`role_id`),
  KEY `ix_role_permissions_permission_id` (`permission_id`),
  CONSTRAINT `fk_rp_role`       FOREIGN KEY (`role_id`)       REFERENCES `roles` (`id`)       ON DELETE CASCADE,
  CONSTRAINT `fk_rp_permission` FOREIGN KEY (`permission_id`) REFERENCES `permissions` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='角色-权限点关联表';

-- -----------------------------------------------------------------------------
-- 5. user_roles —— 用户-角色关联表
--    ★★ 全项目最关键的一条约束：fk_ur_role 的 ON DELETE RESTRICT
--        这是 R3（删除被引用角色必须 409）的数据库级兜底。
--        即使应用层漏判，MySQL 也会以 1451 错误拒绝删除，绝不允许级联清除。
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `user_roles` (
  `id`         INT      NOT NULL AUTO_INCREMENT,
  `user_id`    INT      NOT NULL,
  `role_id`    INT      NOT NULL,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '分配时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_user_role` (`user_id`, `role_id`),
  KEY `ix_user_roles_user_id` (`user_id`),
  KEY `ix_user_roles_role_id` (`role_id`),
  CONSTRAINT `fk_ur_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_ur_role` FOREIGN KEY (`role_id`) REFERENCES `roles` (`id`) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='用户-角色关联表';

-- -----------------------------------------------------------------------------
-- 6. audit_logs —— 审计日志表（R5：只追加，不修改，不删除）
--    ★ actor_id 用 SET NULL 而非 CASCADE：操作者被删，日志必须留下。
--    ★ actor_name 冗余快照：即使 actor_id 为 NULL，历史日志仍可读。
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `audit_logs` (
  `id`          BIGINT      NOT NULL AUTO_INCREMENT,
  `actor_id`    INT         DEFAULT NULL COMMENT '操作者；其被删除时置 NULL',
  `actor_name`  VARCHAR(50) NOT NULL DEFAULT 'system' COMMENT '操作者快照，冗余存储',
  `action`      VARCHAR(50) NOT NULL COMMENT 'role.create / user.assign_roles / permission.toggle ...',
  `target_type` VARCHAR(30) DEFAULT NULL COMMENT 'role / user / permission',
  `target_id`   INT         DEFAULT NULL,
  `target_name` VARCHAR(80) DEFAULT NULL,
  `detail`      JSON        DEFAULT NULL COMMENT '变更详情（旧值/新值）',
  `created_at`  DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `ix_audit_logs_actor_id` (`actor_id`),
  KEY `ix_audit_logs_action` (`action`),
  KEY `ix_audit_logs_target_type` (`target_type`),
  KEY `ix_audit_logs_created_at` (`created_at`),
  CONSTRAINT `fk_audit_actor` FOREIGN KEY (`actor_id`) REFERENCES `users` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='审计日志表（只追加）';

-- -----------------------------------------------------------------------------
-- 7. products —— 商品表（受 products:read / products:edit 保护）
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `products` (
  `id`         INT           NOT NULL AUTO_INCREMENT,
  `name`       VARCHAR(100)  NOT NULL,
  `sku`        VARCHAR(50)   NOT NULL,
  `price`      DECIMAL(10,2) NOT NULL DEFAULT 0,
  `stock`      INT           NOT NULL DEFAULT 0,
  `created_by` INT           DEFAULT NULL COMMENT '创建人，演示鉴权身份透传到业务层',
  `created_at` DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_products_sku` (`sku`),
  KEY `ix_products_name` (`name`),
  KEY `fk_product_creator` (`created_by`),
  CONSTRAINT `fk_product_creator` FOREIGN KEY (`created_by`) REFERENCES `users` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='商品表';

-- -----------------------------------------------------------------------------
-- 8. orders —— 订单表（受 orders:read 保护，只读接口）
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `orders` (
  `id`         INT           NOT NULL AUTO_INCREMENT,
  `order_no`   VARCHAR(50)   NOT NULL,
  `customer`   VARCHAR(80)   NOT NULL,
  `amount`     DECIMAL(10,2) NOT NULL DEFAULT 0,
  `status`     VARCHAR(20)   NOT NULL DEFAULT 'pending',
  `created_at` DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `ix_orders_order_no` (`order_no`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='订单表';

-- =============================================================================
-- 验证建表结果
-- =============================================================================
-- SHOW TABLES;
-- SELECT TABLE_NAME, TABLE_COMMENT FROM information_schema.TABLES WHERE TABLE_SCHEMA='rbac_db';
--
-- 验证 R3 的数据库级兜底 —— 应报 ERROR 1451 (Cannot delete or update a parent row)：
--   DELETE FROM roles WHERE id = (SELECT role_id FROM user_roles LIMIT 1);
