import os
import json

import boto3
import pymysql


# ============================================================
# AWS CLIENTS
# ============================================================

ssm = boto3.client("ssm")


# ============================================================
# SSM PARAMETER
# ============================================================

def get_parameter(name):
    return ssm.get_parameter(
        Name=name,
        WithDecryption=False
    )["Parameter"]["Value"]


# ============================================================
# DATABASE CONNECTION
# ============================================================

def get_database_connection():

    port_parameter = os.environ.get(
        "DB_PORT_PARAMETER"
    )

    port = (
        int(get_parameter(port_parameter))
        if port_parameter
        else 3306
    )

    return pymysql.connect(
        host=get_parameter(
            os.environ["DB_HOST_PARAMETER"]
        ),
        user=get_parameter(
            os.environ["DB_USERNAME_PARAMETER"]
        ),
        password=get_parameter(
            os.environ["DB_PASSWORD_PARAMETER"]
        ),
        database=get_parameter(
            os.environ["DB_NAME_PARAMETER"]
        ),
        port=port,
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=10,
        autocommit=False
    )


# ============================================================
# SCHEMA HELPERS
# ============================================================

def column_exists(cursor, table_name, column_name):

    cursor.execute(
        """
        SELECT COUNT(*) AS count
        FROM information_schema.columns
        WHERE table_schema = DATABASE()
          AND table_name = %s
          AND column_name = %s
        """,
        (
            table_name,
            column_name
        )
    )

    return cursor.fetchone()["count"] > 0


def index_exists(cursor, table_name, index_name):

    cursor.execute(
        """
        SELECT COUNT(*) AS count
        FROM information_schema.statistics
        WHERE table_schema = DATABASE()
          AND table_name = %s
          AND index_name = %s
        """,
        (
            table_name,
            index_name
        )
    )

    return cursor.fetchone()["count"] > 0


def foreign_key_exists(
    cursor,
    table_name,
    constraint_name
):

    cursor.execute(
        """
        SELECT COUNT(*) AS count
        FROM information_schema.table_constraints
        WHERE constraint_schema = DATABASE()
          AND table_name = %s
          AND constraint_name = %s
          AND constraint_type = 'FOREIGN KEY'
        """,
        (
            table_name,
            constraint_name
        )
    )

    return cursor.fetchone()["count"] > 0


def get_foreign_keys(
    cursor,
    table_name,
    referenced_table=None
):
    """Return foreign-key constraints for a table."""

    query = """
        SELECT DISTINCT
            kcu.CONSTRAINT_NAME AS constraint_name,
            kcu.REFERENCED_TABLE_NAME AS referenced_table_name,
            kcu.REFERENCED_COLUMN_NAME AS referenced_column_name
        FROM information_schema.KEY_COLUMN_USAGE AS kcu
        WHERE kcu.TABLE_SCHEMA = DATABASE()
          AND kcu.TABLE_NAME = %s
          AND kcu.REFERENCED_TABLE_NAME IS NOT NULL
    """

    parameters = [table_name]

    if referenced_table:
        query += """
          AND kcu.REFERENCED_TABLE_NAME = %s
        """
        parameters.append(referenced_table)

    cursor.execute(query, parameters)

    return cursor.fetchall()


def drop_foreign_keys_referencing(
    cursor,
    table_name,
    referenced_table
):
    """Drop foreign keys on table_name referencing referenced_table."""

    foreign_keys = get_foreign_keys(
        cursor,
        table_name,
        referenced_table
    )

    for foreign_key in foreign_keys:
        constraint_name = (
            foreign_key.get("constraint_name")
            or foreign_key.get("CONSTRAINT_NAME")
        )

        if not constraint_name:
            raise RuntimeError(
                f"Could not determine foreign-key constraint name for "
                f"{table_name} -> {referenced_table}"
            )

        cursor.execute(
            f"""
            ALTER TABLE `{table_name}`
            DROP FOREIGN KEY `{constraint_name}`
            """
        )


def ensure_index(
    cursor,
    table_name,
    index_name,
    column_name
):

    if index_exists(
        cursor,
        table_name,
        index_name
    ):
        return

    cursor.execute(
        f"""
        ALTER TABLE `{table_name}`
        ADD INDEX `{index_name}` (`{column_name}`)
        """
    )


# ============================================================
# AUTH TOKEN SEED
# ============================================================

def seed_token(
    cursor,
    customer_id,
    token,
    role
):

    if customer_id is None:

        cursor.execute(
            """
            SELECT token_id
            FROM customer_auth_tokens
            WHERE token_hash = SHA2(%s, 256)
              AND role = %s
            LIMIT 1
            """,
            (
                token,
                role
            )
        )

    else:

        cursor.execute(
            """
            SELECT token_id
            FROM customer_auth_tokens
            WHERE customer_id = %s
              AND token_hash = SHA2(%s, 256)
              AND role = %s
            LIMIT 1
            """,
            (
                customer_id,
                token,
                role
            )
        )

    if cursor.fetchone():
        return

    cursor.execute(
        """
        INSERT INTO customer_auth_tokens
        (
            customer_id,
            token_hash,
            role,
            is_active
        )
        VALUES
        (
            %s,
            SHA2(%s, 256),
            %s,
            TRUE
        )
        """,
        (
            customer_id,
            token,
            role
        )
    )


# ============================================================
# PRODUCT SEED
# ============================================================

def seed_products_if_empty(cursor):

    cursor.execute(
        """
        SELECT COUNT(*) AS count
        FROM products
        """
    )

    if cursor.fetchone()["count"] > 0:
        return

    products = [

        (
            "Apple iPhone 15",
            "Apple iPhone 15 128GB smartphone",
            69999.00,
            25,
            5
        ),

        (
            "Samsung Galaxy S24",
            "Samsung Galaxy S24 256GB smartphone",
            74999.00,
            20,
            5
        ),

        (
            "OnePlus 12",
            "OnePlus 12 256GB 5G smartphone",
            64999.00,
            18,
            5
        ),

        (
            "Apple MacBook Air M2",
            "MacBook Air M2 13-inch laptop",
            99999.00,
            10,
            3
        ),

        (
            "Dell Inspiron 15",
            "Dell Inspiron 15 performance laptop",
            58999.00,
            12,
            3
        ),

        (
            "Samsung Galaxy Tab S9 FE",
            "Samsung Galaxy Tab S9 FE tablet",
            36999.00,
            15,
            5
        ),

        (
            "Sony WH-1000XM5",
            "Sony wireless noise cancelling headphones",
            29999.00,
            20,
            5
        ),

        (
            "JBL Flip 6",
            "JBL portable Bluetooth speaker",
            11999.00,
            30,
            5
        ),

        (
            "Logitech MX Master 3S",
            "Wireless productivity mouse",
            8999.00,
            25,
            5
        ),

        (
            "Apple AirPods Pro 2",
            "Apple AirPods Pro 2 wireless earbuds",
            24999.00,
            22,
            5
        )
    ]

    cursor.executemany(
        """
        INSERT INTO products
        (
            name,
            description,
            price,
            stock,
            low_stock_threshold,
            is_active
        )
        VALUES
        (
            %s,
            %s,
            %s,
            %s,
            %s,
            TRUE
        )
        """,
        products
    )


# ============================================================
# HANDLER
# ============================================================

def lambda_handler(event, context):

    connection = None

    try:

        connection = get_database_connection()

        with connection.cursor() as cursor:

            # =================================================
            # PRODUCTS
            # =================================================

            cursor.execute(
                """
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
                COLLATE=utf8mb4_unicode_ci
                """
            )

            # Make sure product ID is BIGINT.
            #
            # order_items foreign key is temporarily removed
            # before modifying the referenced primary key.

            if column_exists(
                cursor,
                "products",
                "id"
            ):

                drop_foreign_keys_referencing(
                    cursor,
                    "order_items",
                    "products"
                )

                cursor.execute(
                    """
                    ALTER TABLE products
                    MODIFY id BIGINT
                    NOT NULL AUTO_INCREMENT
                    """
                )

            if not column_exists(
                cursor,
                "products",
                "is_active"
            ):

                cursor.execute(
                    """
                    ALTER TABLE products
                    ADD COLUMN is_active BOOLEAN
                    NOT NULL DEFAULT TRUE
                    AFTER low_stock_threshold
                    """
                )

            seed_products_if_empty(cursor)

            # =================================================
            # CUSTOMERS
            # =================================================

            cursor.execute(
                """
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
                    UNIQUE KEY uq_customers_email (email)
                )
                ENGINE=InnoDB
                DEFAULT CHARSET=utf8mb4
                COLLATE=utf8mb4_unicode_ci
                """
            )

            cursor.execute(
                """
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
                    status = VALUES(status)
                """
            )

            # =================================================
            # CUSTOMER AUTH TOKENS
            # =================================================

            cursor.execute(
                """
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
                COLLATE=utf8mb4_unicode_ci
                """
            )

            if not column_exists(
                cursor,
                "customer_auth_tokens",
                "role"
            ):

                cursor.execute(
                    """
                    ALTER TABLE customer_auth_tokens
                    ADD COLUMN role
                    ENUM('customer', 'admin')
                    NOT NULL DEFAULT 'customer'
                    AFTER token_hash
                    """
                )

            cursor.execute(
                """
                ALTER TABLE customer_auth_tokens
                MODIFY customer_id VARCHAR(100) NULL
                """
            )

            # -------------------------------------------------
            # Remove any UNIQUE index that uses token_hash.
            #
            # token_hash is intentionally NOT UNIQUE.
            # -------------------------------------------------

            cursor.execute(
                """
                SELECT DISTINCT index_name
                FROM information_schema.statistics
                WHERE table_schema = DATABASE()
                  AND table_name = 'customer_auth_tokens'
                  AND column_name = 'token_hash'
                  AND non_unique = 0
                  AND index_name <> 'PRIMARY'
                """
            )

            unique_token_indexes = (
                cursor.fetchall()
            )

            for index_row in unique_token_indexes:

                index_name = index_row["index_name"]

                cursor.execute(
                    f"""
                    ALTER TABLE customer_auth_tokens
                    DROP INDEX `{index_name}`
                    """
                )

            ensure_index(
                cursor,
                "customer_auth_tokens",
                "idx_customer_auth_token_hash",
                "token_hash"
            )

            # =================================================
            # ORDER STATUS
            # =================================================

            cursor.execute(
                """
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
                COLLATE=utf8mb4_unicode_ci
                """
            )

            # Make status_id consistently INT.

            drop_foreign_keys_referencing(
                cursor,
                "orders",
                "order_status"
            )

            cursor.execute(
                """
                ALTER TABLE order_status
                MODIFY status_id INT
                NOT NULL AUTO_INCREMENT
                """
            )

            cursor.execute(
                """
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
                    description = VALUES(description)
                """
            )

            # =================================================
            # ORDERS
            # =================================================

            cursor.execute(
                """
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
                        (status_id)
                )
                ENGINE=InnoDB
                DEFAULT CHARSET=utf8mb4
                COLLATE=utf8mb4_unicode_ci
                """
            )

            # Remove existing order_items -> orders FK
            # before changing orders.order_id.

            drop_foreign_keys_referencing(
                cursor,
                "order_items",
                "orders"
            )

            cursor.execute(
                """
                ALTER TABLE orders
                MODIFY order_id BIGINT
                NOT NULL AUTO_INCREMENT
                """
            )

            cursor.execute(
                """
                ALTER TABLE orders
                MODIFY customer_id VARCHAR(100)
                NOT NULL
                """
            )

            cursor.execute(
                """
                ALTER TABLE orders
                MODIFY total_amount DECIMAL(12,2)
                NOT NULL
                """
            )

            cursor.execute(
                """
                ALTER TABLE orders
                MODIFY status_id INT
                NOT NULL
                """
            )

            cursor.execute(
                """
                ALTER TABLE orders
                MODIFY failure_reason VARCHAR(1000) NULL
                """
            )

            ensure_index(
                cursor,
                "orders",
                "idx_orders_customer_id",
                "customer_id"
            )

            ensure_index(
                cursor,
                "orders",
                "idx_orders_status_id",
                "status_id"
            )

            # =================================================
            # ORDER ITEMS
            # =================================================

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS order_items
                (
                    order_item_id BIGINT
                    NOT NULL AUTO_INCREMENT,

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
                        (product_id)
                )
                ENGINE=InnoDB
                DEFAULT CHARSET=utf8mb4
                COLLATE=utf8mb4_unicode_ci
                """
            )

            # -------------------------------------------------
            # Remove existing FKs before changing column types.
            # -------------------------------------------------

            drop_foreign_keys_referencing(
                cursor,
                "order_items",
                "orders"
            )

            drop_foreign_keys_referencing(
                cursor,
                "order_items",
                "products"
            )

            # -------------------------------------------------
            # Standardize all order_items ID types.
            # -------------------------------------------------

            cursor.execute(
                """
                ALTER TABLE order_items
                MODIFY order_item_id BIGINT
                NOT NULL AUTO_INCREMENT
                """
            )

            cursor.execute(
                """
                ALTER TABLE order_items
                MODIFY order_id BIGINT
                NOT NULL
                """
            )

            cursor.execute(
                """
                ALTER TABLE order_items
                MODIFY product_id BIGINT
                NOT NULL
                """
            )

            cursor.execute(
                """
                ALTER TABLE order_items
                MODIFY quantity INT
                NOT NULL
                """
            )

            cursor.execute(
                """
                ALTER TABLE order_items
                MODIFY unit_price DECIMAL(10,2)
                NOT NULL
                """
            )

            cursor.execute(
                """
                ALTER TABLE order_items
                MODIFY line_total DECIMAL(12,2)
                NOT NULL
                """
            )

            ensure_index(
                cursor,
                "order_items",
                "idx_order_items_order",
                "order_id"
            )

            ensure_index(
                cursor,
                "order_items",
                "idx_order_items_product",
                "product_id"
            )

            # -------------------------------------------------
            # Recreate Orders -> Order Status FK
            # -------------------------------------------------

            if not foreign_key_exists(
                cursor,
                "orders",
                "fk_orders_status"
            ):

                cursor.execute(
                    """
                    ALTER TABLE orders
                    ADD CONSTRAINT fk_orders_status
                    FOREIGN KEY (status_id)
                    REFERENCES order_status(status_id)
                    """
                )

            # -------------------------------------------------
            # Recreate Order Items -> Orders FK
            # -------------------------------------------------

            if not foreign_key_exists(
                cursor,
                "order_items",
                "fk_order_items_order"
            ):

                cursor.execute(
                    """
                    ALTER TABLE order_items
                    ADD CONSTRAINT fk_order_items_order
                    FOREIGN KEY (order_id)
                    REFERENCES orders(order_id)
                    ON DELETE CASCADE
                    """
                )

            # -------------------------------------------------
            # Recreate Order Items -> Products FK
            # -------------------------------------------------

            if not foreign_key_exists(
                cursor,
                "order_items",
                "fk_order_items_product"
            ):

                cursor.execute(
                    """
                    ALTER TABLE order_items
                    ADD CONSTRAINT fk_order_items_product
                    FOREIGN KEY (product_id)
                    REFERENCES products(id)
                    """
                )

            # =================================================
            # SEED CUSTOMER TOKENS
            # =================================================

            seed_token(
                cursor,
                "CUST001",
                "6A0JLpPl3uM7pb_Uv73FaxC2LuI_WhKbFNEXUddy_VM",
                "customer"
            )

            seed_token(
                cursor,
                "CUST002",
                "txk-wMbwQziK1TDu4HB4R7Nu7lj8wF1kASxkgQtHWa0",
                "customer"
            )

            seed_token(
                cursor,
                "CUST003",
                "bVIS4olBt9xVuvKS-Fxw1nOf1tXmgN7AhG59qYB2-9k",
                "customer"
            )

            # =================================================
            # DEMO ADMIN TOKEN
            #
            # Only SHA-256 hash is stored.
            # No admin token is stored in SSM.
            # =================================================

            seed_token(
                cursor,
                None,
                "CloudMartAdmin@2026!",
                "admin"
            )

        connection.commit()

        message = (
            "Products, customers, authentication and "
            "order tables created or migrated successfully"
        )

        print(
            json.dumps(
                {
                    "message": message,
                    "environment": os.environ.get(
                        "ENVIRONMENT"
                    )
                }
            )
        )

        return {
            "statusCode": 200,
            "body": json.dumps(
                {
                    "message": message
                }
            )
        }

    except Exception as error:

        if connection:
            connection.rollback()

        print(
            json.dumps(
                {
                    "level": "ERROR",
                    "message": "Schema initialization failed",
                    "error": str(error)
                }
            )
        )

        raise

    finally:

        if connection:
            connection.close()