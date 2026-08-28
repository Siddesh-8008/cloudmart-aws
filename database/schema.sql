-- ============================================================
-- CloudMart Database Schema
-- ============================================================

CREATE DATABASE IF NOT EXISTS cloudmart;

USE cloudmart;

-- ============================================================
-- PRODUCTS TABLE
-- ============================================================

CREATE TABLE IF NOT EXISTS products (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,

    name VARCHAR(255) NOT NULL,

    description TEXT,

    price DECIMAL(10,2) NOT NULL,

    stock INT NOT NULL DEFAULT 0,

    low_stock_threshold INT NOT NULL DEFAULT 5,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP
);
