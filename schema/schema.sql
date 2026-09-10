CREATE DATABASE IF NOT EXISTS cloudmart
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE cloudmart;

CREATE TABLE IF NOT EXISTS products (
    id BIGINT NOT NULL AUTO_INCREMENT,
    name VARCHAR(255) NOT NULL,
    description TEXT NULL,
    price DECIMAL(10,2) NOT NULL,
    stock INT NOT NULL DEFAULT 0,
    low_stock_threshold INT NOT NULL DEFAULT 5,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS order_status (
    status_id TINYINT NOT NULL AUTO_INCREMENT,
    status_name VARCHAR(30) NOT NULL,
    description VARCHAR(255) NULL,
    PRIMARY KEY (status_id),
    UNIQUE KEY uq_order_status_name (status_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT INTO order_status (status_name, description) VALUES
('PENDING', 'Order created and waiting for processing'),
('CONFIRMED', 'Order processed and inventory deducted'),
('FAILED', 'Order processing failed')
ON DUPLICATE KEY UPDATE description = VALUES(description);

CREATE TABLE IF NOT EXISTS orders (
    order_id BIGINT NOT NULL AUTO_INCREMENT,
    customer_id VARCHAR(100) NOT NULL,
    total_amount DECIMAL(12,2) NOT NULL,
    status_id TINYINT NOT NULL,
    failure_reason VARCHAR(1000) NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (order_id),
    KEY idx_orders_customer_created (customer_id, created_at),
    KEY idx_orders_status (status_id),
    CONSTRAINT fk_orders_status FOREIGN KEY (status_id) REFERENCES order_status(status_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS order_items (
    order_item_id BIGINT NOT NULL AUTO_INCREMENT,
    order_id BIGINT NOT NULL,
    product_id BIGINT NOT NULL,
    quantity INT NOT NULL,
    unit_price DECIMAL(10,2) NOT NULL,
    line_total DECIMAL(12,2) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (order_item_id),
    KEY idx_order_items_order (order_id),
    KEY idx_order_items_product (product_id),
    CONSTRAINT fk_order_items_order FOREIGN KEY (order_id) REFERENCES orders(order_id) ON DELETE CASCADE,
    CONSTRAINT fk_order_items_product FOREIGN KEY (product_id) REFERENCES products(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
-- ============================================================
-- CUSTOMERS
-- ============================================================

CREATE TABLE IF NOT EXISTS customers (

    customer_id VARCHAR(100) NOT NULL,

    name VARCHAR(255) NOT NULL,

    email VARCHAR(255) NOT NULL,

    status ENUM('ACTIVE', 'INACTIVE')
        NOT NULL DEFAULT 'ACTIVE',

    created_at TIMESTAMP
        NOT NULL DEFAULT CURRENT_TIMESTAMP,

    updated_at TIMESTAMP
        NOT NULL DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,

    PRIMARY KEY (customer_id),

    UNIQUE KEY uq_customers_email (email)

) ENGINE=InnoDB
DEFAULT CHARSET=utf8mb4
COLLATE=utf8mb4_unicode_ci;


-- ============================================================
-- CUSTOMER AUTH TOKENS
-- ============================================================

CREATE TABLE IF NOT EXISTS customer_auth_tokens (

    token_id BIGINT NOT NULL AUTO_INCREMENT,

    customer_id VARCHAR(100) NOT NULL,

    token_hash CHAR(64) NOT NULL,

    is_active BOOLEAN NOT NULL DEFAULT TRUE,

    created_at TIMESTAMP
        NOT NULL DEFAULT CURRENT_TIMESTAMP,

    expires_at TIMESTAMP NULL,

    last_used_at TIMESTAMP NULL,

    PRIMARY KEY (token_id),

    UNIQUE KEY uq_customer_token_hash (token_hash),

    KEY idx_customer_auth_customer (customer_id),

    CONSTRAINT fk_customer_auth_customer
        FOREIGN KEY (customer_id)
        REFERENCES customers(customer_id)
        ON DELETE CASCADE

) ENGINE=InnoDB
DEFAULT CHARSET=utf8mb4
COLLATE=utf8mb4_unicode_ci;
INSERT INTO customers
(
    customer_id,
    name,
    email,
    status
)
VALUES
(
    'CUST001',
    'Siddesh',
    'siddesh@example.com',
    'ACTIVE'
),
(
    'CUST002',
    'Rahul',
    'rahul@example.com',
    'ACTIVE'
),
(
    'CUST003',
    'Priya',
    'priya@example.com',
    'ACTIVE'
)
ON DUPLICATE KEY UPDATE
    name = VALUES(name),
    email = VALUES(email),
    status = VALUES(status);
    INSERT INTO customer_auth_tokens
(
    customer_id,
    token_hash,
    is_active
)
VALUES
(
    'CUST001',
    SHA2('Xc4SvD_R0MCE9P2vjRXGyWXQeZ_52_QOUhh_fXlK5Hk', 256),
    TRUE
),
(
    'CUST002',
    SHA2('GgGigYvglp6sclYCnY7bNOrK1WaJc_q6QrlZrLSQZmc', 256),
    TRUE
),
(
    'CUST003',
    SHA2('xL_KsFGAs2p1toyPfZX0nXmm3Wy2HiAvntawIrqzemQ', 256),
    TRUE
);