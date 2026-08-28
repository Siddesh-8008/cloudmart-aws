-- ============================================================
-- CLOUDMART DATABASE SCHEMA
-- ============================================================

-- Create database if it does not already exist
CREATE DATABASE IF NOT EXISTS cloudmart
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE cloudmart;


-- ============================================================
-- PRODUCTS TABLE
-- ============================================================

CREATE TABLE IF NOT EXISTS products (

    id BIGINT NOT NULL AUTO_INCREMENT,

    name VARCHAR(255) NOT NULL,

    description TEXT NULL,

    price DECIMAL(10,2) NOT NULL,

    stock INT NOT NULL DEFAULT 0,

    low_stock_threshold INT NOT NULL DEFAULT 5,

    created_at TIMESTAMP NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

    updated_at TIMESTAMP NOT NULL
        DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,

    PRIMARY KEY (id)

) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci;


-- ============================================================
-- OPTIONAL TEST DATA
-- ============================================================
-- Uncomment these INSERT statements if you want sample
-- products for testing GET /products.

INSERT INTO products
(
    name,
    description,
    price,
    stock,
    low_stock_threshold
)
SELECT
    'Laptop',
    'CloudMart sample laptop',
    75000.00,
    10,
    5
WHERE NOT EXISTS (
    SELECT 1
    FROM products
    WHERE name = 'Laptop'
);


INSERT INTO products
(
    name,
    description,
    price,
    stock,
    low_stock_threshold
)
SELECT
    'Wireless Mouse',
    'CloudMart sample wireless mouse',
    999.00,
    25,
    5
WHERE NOT EXISTS (
    SELECT 1
    FROM products
    WHERE name = 'Wireless Mouse'
);


-- ============================================================
-- VERIFY
-- ============================================================

SELECT
    id,
    name,
    description,
    price,
    stock,
    low_stock_threshold,
    created_at,
    updated_at
FROM products
ORDER BY id;