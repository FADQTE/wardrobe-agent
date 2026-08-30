-- 潮引智能衣橱商城 Demo 初始化脚本（仅在 MySQL 数据卷首次创建时执行）
CREATE DATABASE IF NOT EXISTS chaoyin DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE chaoyin;

CREATE TABLE IF NOT EXISTS `user` (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  username VARCHAR(64) NOT NULL UNIQUE,
  password VARCHAR(128) NOT NULL,
  nickname VARCHAR(64),
  avatar VARCHAR(512),
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

-- 个人衣橱：与商品同构标签（category/color/season/style/tags），打通衣橱↔商城
CREATE TABLE IF NOT EXISTS wardrobe_item (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  user_id BIGINT NOT NULL,
  name VARCHAR(128) NOT NULL,
  image_url VARCHAR(512),
  category VARCHAR(32) NOT NULL COMMENT 'top|bottom|outerwear|dress|shoes|accessory',
  color VARCHAR(32),
  season VARCHAR(32),
  style VARCHAR(32),
  tags JSON,
  note VARCHAR(255),
  source VARCHAR(16) DEFAULT 'upload' COMMENT 'upload|from_product',
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_user (user_id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS product (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(128) NOT NULL,
  image_url VARCHAR(512),
  category VARCHAR(32) NOT NULL,
  color VARCHAR(32),
  season VARCHAR(32),
  style VARCHAR(32),
  tags JSON,
  price DECIMAL(10,2) NOT NULL,
  stock INT NOT NULL DEFAULT 0,
  status TINYINT NOT NULL DEFAULT 1 COMMENT '1上架 0下架',
  sales INT DEFAULT 0,
  detail TEXT,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_cat (category),
  INDEX idx_status (status)
) ENGINE=InnoDB;

-- 穿搭/活动规则：版本 + 时间窗 + 发布状态
CREATE TABLE IF NOT EXISTS `rule` (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  type VARCHAR(16) NOT NULL COMMENT 'activity|outfit',
  title VARCHAR(128) NOT NULL,
  content TEXT NOT NULL,
  tags JSON,
  version INT NOT NULL DEFAULT 1,
  effective_from DATETIME,
  effective_to DATETIME,
  publish_status VARCHAR(16) NOT NULL DEFAULT 'draft' COMMENT 'draft|published|offline',
  source VARCHAR(128),
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX idx_type_status (type, publish_status)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS orders (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  order_no VARCHAR(32) NOT NULL UNIQUE,
  user_id BIGINT NOT NULL,
  total_amount DECIMAL(10,2) NOT NULL,
  status VARCHAR(16) NOT NULL DEFAULT 'pending' COMMENT 'pending|paid|shipped|done|cancelled',
  receiver_name VARCHAR(64),
  receiver_phone VARCHAR(32),
  receiver_address VARCHAR(255),
  logistics_no VARCHAR(64),
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_user (user_id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS order_item (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  order_id BIGINT NOT NULL,
  product_id BIGINT NOT NULL,
  product_name VARCHAR(128),
  price DECIMAL(10,2),
  quantity INT DEFAULT 1,
  INDEX idx_order (order_id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS favorite (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  user_id BIGINT NOT NULL,
  product_id BIGINT NOT NULL,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uk_user_product (user_id, product_id)
) ENGINE=InnoDB;

-- 会话记忆：state 存人物/选中单品/候选搭配 JSON
CREATE TABLE IF NOT EXISTS chat_session (
  id VARCHAR(64) PRIMARY KEY,
  user_id BIGINT,
  title VARCHAR(128),
  state JSON,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS chat_message (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  session_id VARCHAR(64) NOT NULL,
  role VARCHAR(16) NOT NULL,
  content TEXT,
  meta JSON,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_session (session_id)
) ENGINE=InnoDB;

-- 换装任务（mock 生图）：统一管理输入参数/状态/结果地址
CREATE TABLE IF NOT EXISTS tryon_task (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  session_id VARCHAR(64),
  user_id BIGINT,
  person_image VARCHAR(512),
  garment_ids JSON,
  params JSON,
  status VARCHAR(16) DEFAULT 'pending' COMMENT 'pending|processing|done|failed',
  result_url VARCHAR(512),
  error_msg VARCHAR(255),
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  finished_at DATETIME
) ENGINE=InnoDB;

-- Trace 可观测：每轮执行的公开证据（不含系统提示词/CoT/密钥/隐私原文）
CREATE TABLE IF NOT EXISTS trace_event (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  session_id VARCHAR(64) NOT NULL,
  event_type VARCHAR(32) NOT NULL COMMENT 'plan|status|tool|rag|product|outfit|image|memory|token|done|error|safety|handoff|context',
  category VARCHAR(32) COMMENT 'entry|fact|knowledge|control|result|safety|cost',
  payload JSON,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_session (session_id)
) ENGINE=InnoDB;
