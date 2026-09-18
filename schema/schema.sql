CREATE DATABASE IF NOT EXISTS cloudmart
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE cloudmart;


-- ============================================================
-- PRODUCTS
-- ============================================================

CREATE TABLE IF NOT EXISTS products
(
    id BIGINT NOT NULL AUTO_INCREMENT,

    name VARCHAR(255) NOT NULL,

    description TEXT NOT NULL,

    price DECIMAL(10,2) NOT NULL,

    stock INT NOT NULL DEFAULT 0,

    low_stock_threshold INT NOT NULL DEFAULT 5,

    is_active BOOLEAN NOT NULL DEFAULT TRUE,

    created_at TIMESTAMP NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

    updated_at TIMESTAMP NOT NULL
        DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,

    PRIMARY KEY (id)

)
ENGINE=InnoDB
DEFAULT CHARSET=utf8mb4
COLLATE=utf8mb4_unicode_ci;


-- ============================================================
-- SEED PRODUCTS
-- ============================================================

INSERT INTO products
(
    name,
    description,
    price,
    stock,
    low_stock_threshold,
    is_active
)

SELECT
    s.name,
    s.description,
    s.price,
    s.stock,
    s.low_stock_threshold,
    TRUE

FROM
(
    SELECT
        'Apple iPhone 15',
        'Apple iPhone 15 128GB smartphone',
        69999.00,
        25,
        5

    UNION ALL

    SELECT
        'Samsung Galaxy S24',
        'Samsung Galaxy S24 256GB smartphone',
        74999.00,
        20,
        5

    UNION ALL

    SELECT
        'OnePlus 12',
        'OnePlus 12 256GB 5G smartphone',
        64999.00,
        18,
        5

    UNION ALL

    SELECT
        'Apple MacBook Air M2',
        'MacBook Air M2 13-inch laptop',
        99999.00,
        10,
        3

    UNION ALL

    SELECT
        'Dell Inspiron 15',
        'Dell Inspiron 15 performance laptop',
        58999.00,
        12,
        3

    UNION ALL

    SELECT
        'Samsung Galaxy Tab S9 FE',
        'Samsung Galaxy Tab S9 FE tablet',
        36999.00,
        15,
        5

    UNION ALL

    SELECT
        'Sony WH-1000XM5',
        'Sony wireless noise cancelling headphones',
        29999.00,
        20,
        5

    UNION ALL

    SELECT
        'JBL Flip 6',
        'JBL portable Bluetooth speaker',
        11999.00,
        30,
        5

    UNION ALL

    SELECT
        'Logitech MX Master 3S',
        'Wireless productivity mouse',
        8999.00,
        25,
        5

    UNION ALL

    SELECT
        'Apple AirPods Pro 2',
        'Apple AirPods Pro 2 wireless earbuds',
        24999.00,
        22,
        5

) AS s
(
    name,
    description,
    price,
    stock,
    low_stock_threshold
)

WHERE NOT EXISTS
(
    SELECT 1
    FROM products
);


-- ============================================================
-- ORDER STATUS
-- ============================================================

CREATE TABLE IF NOT EXISTS order_status
(
    status_id INT NOT NULL AUTO_INCREMENT,

    status_name VARCHAR(30) NOT NULL,

    description VARCHAR(255) NULL,

    PRIMARY KEY (status_id),

    UNIQUE KEY uq_order_status_name
        (status_name)

)
ENGINE=InnoDB
DEFAULT CHARSET=utf8mb4
COLLATE=utf8mb4_unicode_ci;


INSERT INTO order_status
(
    status_name,
    description
)

VALUES

(
    'PENDING',
    'Order created and waiting for processing'
),

(
    'CONFIRMED',
    'Order processed and inventory deducted'
),

(
    'FAILED',
    'Order processing failed'
),

(
    'CANCELLED',
    'Order was cancelled'
)

ON DUPLICATE KEY UPDATE
    description = VALUES(description);


-- ============================================================
-- ORDERS
-- ============================================================

CREATE TABLE IF NOT EXISTS orders
(
    order_id BIGINT NOT NULL AUTO_INCREMENT,

    customer_id VARCHAR(100) NOT NULL,

    total_amount DECIMAL(12,2) NOT NULL,

    status_id INT NOT NULL,

    failure_reason VARCHAR(1000) NULL,

    created_at TIMESTAMP NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

    updated_at TIMESTAMP NOT NULL
        DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,

    PRIMARY KEY (order_id),

    KEY idx_orders_customer_created
        (customer_id, created_at),

    KEY idx_orders_status
        (status_id),

    CONSTRAINT fk_orders_status
        FOREIGN KEY (status_id)
        REFERENCES order_status(status_id)

)
ENGINE=InnoDB
DEFAULT CHARSET=utf8mb4
COLLATE=utf8mb4_unicode_ci;


-- ============================================================
-- ORDER ITEMS
-- ============================================================

CREATE TABLE IF NOT EXISTS order_items
(
    order_item_id BIGINT NOT NULL AUTO_INCREMENT,

    order_id BIGINT NOT NULL,

    product_id BIGINT NOT NULL,

    quantity INT NOT NULL,

    unit_price DECIMAL(10,2) NOT NULL,

    line_total DECIMAL(12,2) NOT NULL,

    created_at TIMESTAMP NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (order_item_id),

    KEY idx_order_items_order
        (order_id),

    KEY idx_order_items_product
        (product_id),

    CONSTRAINT fk_order_items_order
        FOREIGN KEY (order_id)
        REFERENCES orders(order_id)
        ON DELETE CASCADE,

    CONSTRAINT fk_order_items_product
        FOREIGN KEY (product_id)
        REFERENCES products(id)

)
ENGINE=InnoDB
DEFAULT CHARSET=utf8mb4
COLLATE=utf8mb4_unicode_ci;


-- ============================================================
-- CUSTOMERS
-- ============================================================

CREATE TABLE IF NOT EXISTS customers
(
    customer_id VARCHAR(100) NOT NULL,

    name VARCHAR(255) NOT NULL,

    email VARCHAR(255) NOT NULL,

    status ENUM('ACTIVE', 'INACTIVE')
        NOT NULL DEFAULT 'ACTIVE',

    created_at TIMESTAMP NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

    updated_at TIMESTAMP NOT NULL
        DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,

    PRIMARY KEY (customer_id),

    UNIQUE KEY uq_customers_email
        (email)

)
ENGINE=InnoDB
DEFAULT CHARSET=utf8mb4
COLLATE=utf8mb4_unicode_ci;


-- ============================================================
-- CUSTOMER SEED DATA
-- ============================================================

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


-- ============================================================
-- CUSTOMER AUTH TOKENS
--
-- token_hash is intentionally NOT UNIQUE.
--
-- Duplicate token hashes are allowed.
--
-- role:
--     customer
--     admin
--
-- Admin rows use NULL customer_id.
-- ============================================================

CREATE TABLE IF NOT EXISTS customer_auth_tokens
(
    token_id BIGINT NOT NULL AUTO_INCREMENT,

    customer_id VARCHAR(100) NULL,

    token_hash CHAR(64) NOT NULL,

    role ENUM('customer', 'admin')
        NOT NULL DEFAULT 'customer',

    is_active BOOLEAN NOT NULL DEFAULT TRUE,

    created_at TIMESTAMP NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

    expires_at TIMESTAMP NULL,

    last_used_at TIMESTAMP NULL,

    PRIMARY KEY (token_id),

    KEY idx_customer_auth_customer
        (customer_id),

    KEY idx_customer_auth_token_hash
        (token_hash),

    CONSTRAINT fk_customer_auth_customer
        FOREIGN KEY (customer_id)
        REFERENCES customers(customer_id)
        ON DELETE CASCADE

)
ENGINE=InnoDB
DEFAULT CHARSET=utf8mb4
COLLATE=utf8mb4_unicode_ci;


-- ============================================================
-- CUSTOMER AUTH TOKEN SEEDS
-- ============================================================

INSERT INTO customer_auth_tokens
(
    customer_id,
    token_hash,
    role,
    is_active
)

SELECT
    'CUST001',
    SHA2(
        '6A0JLpPl3uM7pb_Uv73FaxC2LuI_WhKbFNEXUddy_VM',
        256
    ),
    'customer',
    TRUE

WHERE NOT EXISTS
(
    SELECT 1
    FROM customer_auth_tokens
    WHERE customer_id = 'CUST001'
      AND token_hash =
          SHA2(
              '6A0JLpPl3uM7pb_Uv73FaxC2LuI_WhKbFNEXUddy_VM',
              256
          )
      AND role = 'customer'
);


INSERT INTO customer_auth_tokens
(
    customer_id,
    token_hash,
    role,
    is_active
)

SELECT
    'CUST002',
    SHA2(
        'txk-wMbwQziK1TDu4HB4R7Nu7lj8wF1kASxkgQtHWa0',
        256
    ),
    'customer',
    TRUE

WHERE NOT EXISTS
(
    SELECT 1
    FROM customer_auth_tokens
    WHERE customer_id = 'CUST002'
      AND token_hash =
          SHA2(
              'txk-wMbwQziK1TDu4HB4R7Nu7lj8wF1kASxkgQtHWa0',
              256
          )
      AND role = 'customer'
);


INSERT INTO customer_auth_tokens
(
    customer_id,
    token_hash,
    role,
    is_active
)

SELECT
    'CUST003',
    SHA2(
        'bVIS4olBt9xVuvKS-Fxw1nOf1tXmgN7AhG59qYB2-9k',
        256
    ),
    'customer',
    TRUE

WHERE NOT EXISTS
(
    SELECT 1
    FROM customer_auth_tokens
    WHERE customer_id = 'CUST003'
      AND token_hash =
          SHA2(
              'bVIS4olBt9xVuvKS-Fxw1nOf1tXmgN7AhG59qYB2-9k',
              256
          )
      AND role = 'customer'
);


-- ============================================================
-- ADMIN AUTH TOKEN
--
-- The plaintext token is used only during seeding.
-- RDS stores SHA-256(token), not the plaintext.
--
-- No admin token is stored in SSM.
-- ============================================================

INSERT INTO customer_auth_tokens
(
    customer_id,
    token_hash,
    role,
    is_active
)

SELECT
    NULL,
    SHA2(
        'CloudMartAdmin@2026!',
        256
    ),
    'admin',
    TRUE

WHERE NOT EXISTS
(
    SELECT 1
    FROM customer_auth_tokens
    WHERE token_hash =
          SHA2(
              'CloudMartAdmin@2026!',
              256
          )
      AND role = 'admin'
);
