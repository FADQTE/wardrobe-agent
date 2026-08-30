-- 非破坏性增量结构：应用每次启动执行，兼容已经存在的 MySQL 数据卷。
CREATE TABLE IF NOT EXISTS after_sale (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  request_no VARCHAR(32) NOT NULL UNIQUE,
  order_id BIGINT NOT NULL,
  user_id BIGINT NOT NULL,
  type VARCHAR(24) NOT NULL COMMENT 'refund|return_refund|exchange',
  status VARCHAR(16) NOT NULL DEFAULT 'pending' COMMENT 'pending|approved|rejected|completed',
  reason VARCHAR(255),
  amount DECIMAL(10,2) NOT NULL,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX idx_user (user_id),
  INDEX idx_order (order_id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS user_auth_token (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  user_id BIGINT NOT NULL,
  token_hash CHAR(64) NOT NULL UNIQUE,
  expires_at DATETIME NOT NULL,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_user (user_id),
  INDEX idx_expires (expires_at)
) ENGINE=InnoDB;
