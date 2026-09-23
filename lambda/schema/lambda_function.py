import os
import json
import boto3
import pymysql


# ============================================================
# AWS CLIENT
# ============================================================

ssm = boto3.client("ssm")


# ============================================================
# SSM PARAMETER HELPER
# ============================================================

def get_parameter(name, secure=False):

    return ssm.get_parameter(
        Name=name,
        WithDecryption=secure
    )["Parameter"]["Value"]


# ============================================================
# DATABASE CONNECTION
# ============================================================

def get_database_connection():

    db_port_parameter = os.environ.get(
        "DB_PORT_PARAMETER"
    )

    if db_port_parameter:

        db_port = int(
            get_parameter(
                db_port_parameter
            )
        )

    else:

        db_port = 3306


    return pymysql.connect(

        host=get_parameter(
            os.environ["DB_HOST_PARAMETER"]
        ),

        user=get_parameter(
            os.environ["DB_USERNAME_PARAMETER"],
            secure=True
        ),

        password=get_parameter(
            os.environ["DB_PASSWORD_PARAMETER"],
            secure=True
        ),

        database=get_parameter(
            os.environ["DB_NAME_PARAMETER"]
        ),

        port=db_port,

        cursorclass=pymysql.cursors.DictCursor,

        connect_timeout=10,

        autocommit=False
    )


# ============================================================
# LAMBDA HANDLER
# ============================================================

def lambda_handler(event, context):

    print(
        json.dumps({
            "message": "Schema Lambda invoked",
            "request_id": context.aws_request_id
        })
    )


    connection = None


    try:

        connection = get_database_connection()


        with connection.cursor() as cursor:

            # =================================================
            # PRODUCTS TABLE
            # =================================================

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS products (

                    id INT AUTO_INCREMENT PRIMARY KEY,

                    name VARCHAR(255) NOT NULL,

                    description TEXT,

                    price DECIMAL(10,2) NOT NULL,

                    stock INT NOT NULL DEFAULT 0,

                    low_stock_threshold INT NOT NULL DEFAULT 5,

                    is_active BOOLEAN NOT NULL DEFAULT TRUE,

                    created_at TIMESTAMP
                        DEFAULT CURRENT_TIMESTAMP,

                    updated_at TIMESTAMP
                        DEFAULT CURRENT_TIMESTAMP
                        ON UPDATE CURRENT_TIMESTAMP

                )
                """
            )


            # =================================================
            # SEED PRODUCTS
            #
            # INSERT IGNORE keeps existing product rows and their
            # current stock unchanged. If the RDS database is newly
            # created, all ten standard CloudMart products are
            # inserted automatically.
            # =================================================

            cursor.execute(
                """
                INSERT IGNORE INTO products
                (
                    id,
                    name,
                    description,
                    price,
                    stock,
                    low_stock_threshold,
                    is_active
                )
                VALUES
                (
                    1,
                    'Apple iPhone 15',
                    'Apple iPhone 15 128GB smartphone',
                    69999.00,
                    25,
                    5,
                    TRUE
                ),
                (
                    2,
                    'Samsung Galaxy S24',
                    'Samsung Galaxy S24 256GB smartphone',
                    74999.00,
                    20,
                    5,
                    TRUE
                ),
                (
                    3,
                    'OnePlus 12',
                    'OnePlus 12 256GB 5G smartphone',
                    64999.00,
                    18,
                    5,
                    TRUE
                ),
                (
                    4,
                    'Apple MacBook Air M2',
                    'MacBook Air M2 13-inch laptop',
                    99999.00,
                    10,
                    3,
                    TRUE
                ),
                (
                    5,
                    'Dell Inspiron 15',
                    'Dell Inspiron 15 performance laptop',
                    58999.00,
                    12,
                    3,
                    TRUE
                ),
                (
                    6,
                    'Samsung Galaxy Tab S9 FE',
                    'Samsung Galaxy Tab S9 FE tablet',
                    36999.00,
                    15,
                    5,
                    TRUE
                ),
                (
                    7,
                    'Sony WH-1000XM5',
                    'Sony wireless noise cancelling headphones',
                    29999.00,
                    20,
                    5,
                    TRUE
                ),
                (
                    8,
                    'JBL Flip 6',
                    'JBL portable Bluetooth speaker',
                    11999.00,
                    29,
                    5,
                    TRUE
                ),
                (
                    9,
                    'Logitech MX Master 3S',
                    'Wireless productivity mouse',
                    8999.00,
                    25,
                    5,
                    TRUE
                ),
                (
                    10,
                    'Apple AirPods Pro 2',
                    'Apple AirPods Pro 2 wireless earbuds',
                    24999.00,
                    21,
                    5,
                    TRUE
                )
                """
            )


            # =================================================
            # CUSTOMER TABLE
            # =================================================

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS customers (

                    customer_id VARCHAR(100) NOT NULL,

                    name VARCHAR(255) NOT NULL,

                    email VARCHAR(255) NOT NULL,

                    status ENUM(
                        'ACTIVE',
                        'INACTIVE'
                    ) NOT NULL DEFAULT 'ACTIVE',

                    created_at TIMESTAMP
                        DEFAULT CURRENT_TIMESTAMP,

                    updated_at TIMESTAMP
                        DEFAULT CURRENT_TIMESTAMP
                        ON UPDATE CURRENT_TIMESTAMP,

                    PRIMARY KEY (
                        customer_id
                    ),

                    UNIQUE KEY uq_customers_email (
                        email
                    )

                )
                ENGINE=InnoDB
                DEFAULT CHARSET=utf8mb4
                COLLATE=utf8mb4_unicode_ci
                """
            )


            # =================================================
            # CUSTOMER AUTH TOKENS TABLE
            #
            # customer_id is required for customer rows.
            # admin_id is required for admin rows.
            # role identifies customer/admin.
            # Only SHA-256 token hashes are stored.
            #

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS customer_auth_tokens (

                    token_id BIGINT NOT NULL AUTO_INCREMENT,

                    customer_id VARCHAR(100) NULL,

                    admin_id VARCHAR(100) NULL,

                    token_hash CHAR(64) NOT NULL,

                    role ENUM('customer', 'admin')
                        NOT NULL DEFAULT 'customer',

                    is_active BOOLEAN NOT NULL DEFAULT TRUE,

                    created_at TIMESTAMP
                        DEFAULT CURRENT_TIMESTAMP,

                    expires_at TIMESTAMP NULL,

                    last_used_at TIMESTAMP NULL,

                    PRIMARY KEY (token_id),

                    KEY idx_customer_auth_customer (customer_id),

                    KEY idx_customer_auth_admin (admin_id),

                    KEY idx_customer_auth_token_hash (token_hash),

                    CONSTRAINT fk_customer_auth_customer
                        FOREIGN KEY (customer_id)
                        REFERENCES customers(customer_id)
                        ON DELETE CASCADE,

                    CONSTRAINT chk_customer_auth_identity_role
                        CHECK (
                            (role = 'customer'
                                AND customer_id IS NOT NULL
                                AND admin_id IS NULL)
                            OR
                            (role = 'admin'
                                AND admin_id IS NOT NULL
                                AND customer_id IS NULL)
                        )

                )
                ENGINE=InnoDB
                DEFAULT CHARSET=utf8mb4
                COLLATE=utf8mb4_unicode_ci
                """
            )


            # MIGRATE AN EXISTING AUTH TABLE

            cursor.execute(
                """
                SELECT COUNT(*) AS column_count
                FROM information_schema.columns
                WHERE table_schema = DATABASE()
                  AND table_name = 'customer_auth_tokens'
                  AND column_name = 'admin_id'
                """
            )

            if cursor.fetchone()["column_count"] == 0:
                cursor.execute(
                    """
                    ALTER TABLE customer_auth_tokens
                    ADD COLUMN admin_id VARCHAR(100) NULL
                    AFTER customer_id
                    """
                )

            cursor.execute(
                """
                SELECT COUNT(*) AS column_count
                FROM information_schema.columns
                WHERE table_schema = DATABASE()
                  AND table_name = 'customer_auth_tokens'
                  AND column_name = 'role'
                """
            )

            if cursor.fetchone()["column_count"] == 0:
                cursor.execute(
                    """
                    ALTER TABLE customer_auth_tokens
                    ADD COLUMN role ENUM('customer', 'admin')
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

            cursor.execute(
                '''
                SELECT COUNT(*) AS constraint_count
                FROM information_schema.table_constraints
                WHERE table_schema = DATABASE()
                  AND table_name = 'customer_auth_tokens'
                  AND constraint_name = 'chk_customer_auth_identity_role'
                  AND constraint_type = 'CHECK'
                '''
            )

            if cursor.fetchone()["constraint_count"] == 0:
                cursor.execute(
                    '''
                    ALTER TABLE customer_auth_tokens
                    ADD CONSTRAINT chk_customer_auth_identity_role
                    CHECK (
                        (role = 'customer'
                            AND customer_id IS NOT NULL
                            AND admin_id IS NULL)
                        OR
                        (role = 'admin'
                            AND admin_id IS NOT NULL
                            AND customer_id IS NULL)
                    )
                    '''
                )


            # Composite lookup index used by customer authentication.

            cursor.execute(
                """
                SELECT COUNT(*) AS index_count
                FROM information_schema.statistics
                WHERE table_schema = DATABASE()
                  AND table_name = 'customer_auth_tokens'
                  AND index_name = 'idx_customer_auth_customer_token'
                """
            )

            if cursor.fetchone()["index_count"] == 0:
                cursor.execute(
                    """
                    ALTER TABLE customer_auth_tokens
                    ADD INDEX idx_customer_auth_customer_token
                    (customer_id, token_hash)
                    """
                )


            # =================================================
            # SEED CUSTOMERS
            #
            # These customers are used for testing.
            # =================================================

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
            # SEED CUSTOMER AUTH TOKENS
            #
            # Only SHA-256 hashes are stored in RDS.
            #

            cursor.execute(
                '''
                INSERT INTO customer_auth_tokens
                (
                    customer_id,
                    admin_id,
                    token_hash,
                    role,
                    is_active
                )
                SELECT
                    'CUST001',
                    NULL,
                    SHA2(
                        '6A0JLpPl3uM7pb_Uv73FaxC2LuI_WhKbFNEXUddy_VM',
                        256
                    ),
                    'customer',
                    TRUE
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM customer_auth_tokens
                    WHERE customer_id = 'CUST001'
                      AND role = 'customer'
                )
                '''
            )

            cursor.execute(
                '''
                INSERT INTO customer_auth_tokens
                (
                    customer_id,
                    admin_id,
                    token_hash,
                    role,
                    is_active
                )
                SELECT
                    'CUST002',
                    NULL,
                    SHA2(
                        'txk-wMbwQziK1TDu4HB4R7Nu7lj8wF1kASxkgQtHWa0',
                        256
                    ),
                    'customer',
                    TRUE
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM customer_auth_tokens
                    WHERE customer_id = 'CUST002'
                      AND role = 'customer'
                )
                '''
            )

            cursor.execute(
                '''
                INSERT INTO customer_auth_tokens
                (
                    customer_id,
                    admin_id,
                    token_hash,
                    role,
                    is_active
                )
                SELECT
                    'CUST003',
                    NULL,
                    SHA2(
                        'bVIS4olBt9xVuvKS-Fxw1nOf1tXmgN7AhG59qYB2-9k',
                        256
                    ),
                    'customer',
                    TRUE
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM customer_auth_tokens
                    WHERE customer_id = 'CUST003'
                      AND role = 'customer'
                )
                '''
            )


            # =================================================
            # ADMIN TOKEN
            #
            # GitHub Actions supplies the plaintext token only
            # in the Lambda invocation payload. RDS stores only
            # its SHA-256 hash.
            # =================================================

            event_admin_id = str(
                event.get("admin_id", "")
            ).strip()

            event_admin_token = str(
                event.get("admin_token", "")
            ).strip()

            if event_admin_id and event_admin_token:

                import hashlib

                admin_token_hash = hashlib.sha256(
                    event_admin_token.encode("utf-8")
                ).hexdigest()

                cursor.execute(
                    '''
                    SELECT token_id
                    FROM customer_auth_tokens
                    WHERE admin_id = %s
                      AND role = 'admin'
                    ORDER BY token_id
                    LIMIT 1
                    ''',
                    (event_admin_id,)
                )

                existing_admin = cursor.fetchone()

                if existing_admin:
                    cursor.execute(
                        '''
                        UPDATE customer_auth_tokens
                        SET customer_id = NULL,
                            token_hash = %s,
                            role = 'admin',
                            is_active = TRUE,
                            last_used_at = NULL
                        WHERE token_id = %s
                        ''',
                        (
                            admin_token_hash,
                            existing_admin["token_id"]
                        )
                    )
                else:
                    cursor.execute(
                        '''
                        INSERT INTO customer_auth_tokens
                        (
                            customer_id,
                            admin_id,
                            token_hash,
                            role,
                            is_active
                        )
                        VALUES
                        (
                            NULL,
                            %s,
                            %s,
                            'admin',
                            TRUE
                        )
                        ''',
                        (
                            event_admin_id,
                            admin_token_hash
                        )
                    )

                # There must be only one active admin record for
                # the configured admin ID.
                cursor.execute(
                    '''
                    UPDATE customer_auth_tokens
                    SET is_active = FALSE
                    WHERE role = 'admin'
                      AND admin_id = %s
                      AND token_hash <> %s
                    ''',
                    (
                        event_admin_id,
                        admin_token_hash
                    )
                )

                print(
                    json.dumps({
                        "message": "Admin authentication record updated",
                        "admin_id": event_admin_id,
                        "role": "admin"
                    })
                )



            # =================================================
            # ORDER STATUS TABLE
            # =================================================

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS order_status (

                    status_id INT AUTO_INCREMENT PRIMARY KEY,

                    status_name VARCHAR(50)
                        NOT NULL UNIQUE

                )
                """
            )


            # =================================================
            # SEED ORDER STATUS
            # =================================================

            cursor.execute(
                """
                INSERT IGNORE INTO order_status
                (
                    status_name
                )
                VALUES
                (
                    'PENDING'
                ),
                (
                    'CONFIRMED'
                ),
                (
                    'FAILED'
                ),
                (
                    'CANCELLED'
                )
                """
            )


            # =================================================
            # ORDERS TABLE
            # =================================================

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS orders (

                    order_id INT AUTO_INCREMENT PRIMARY KEY,

                    customer_id VARCHAR(255) NOT NULL,

                    total_amount DECIMAL(10,2) NOT NULL,

                    status_id INT NOT NULL,

                    failure_reason TEXT NULL,

                    created_at TIMESTAMP
                        DEFAULT CURRENT_TIMESTAMP,

                    updated_at TIMESTAMP
                        DEFAULT CURRENT_TIMESTAMP
                        ON UPDATE CURRENT_TIMESTAMP,

                    CONSTRAINT fk_orders_status

                        FOREIGN KEY (
                            status_id
                        )

                        REFERENCES order_status(
                            status_id
                        ),

                    INDEX idx_orders_customer_id
                        (customer_id),

                    INDEX idx_orders_status_id
                        (status_id)

                )
                """
            )


            # =================================================
            # ORDER ITEMS TABLE
            # =================================================

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS order_items (

                    order_item_id INT AUTO_INCREMENT PRIMARY KEY,

                    order_id INT NOT NULL,

                    product_id INT NOT NULL,

                    quantity INT NOT NULL,

                    unit_price DECIMAL(10,2) NOT NULL,

                    line_total DECIMAL(10,2) NOT NULL,

                    CONSTRAINT fk_order_items_order

                        FOREIGN KEY (
                            order_id
                        )

                        REFERENCES orders(
                            order_id
                        )

                        ON DELETE CASCADE,

                    CONSTRAINT fk_order_items_product

                        FOREIGN KEY (
                            product_id
                        )

                        REFERENCES products(
                            id
                        ),

                    INDEX idx_order_items_order_id
                        (order_id),

                    INDEX idx_order_items_product_id
                        (product_id)

                )
                """
            )


        # =====================================================
        # COMMIT
        # =====================================================

        connection.commit()


        print(
            json.dumps({
                "message": (
                    "Products (with seed data), customers, authentication "
                    "and order tables created successfully"
                )
            })
        )


        return {

            "statusCode": 200,

            "body": json.dumps({

                "message": (
                    "Products (with seed data), customers, authentication "
                    "and order tables created successfully"
                )

            })

        }


    except Exception as error:

        if connection:

            connection.rollback()


        print(
            json.dumps({

                "level": "ERROR",

                "message": (
                    "Schema initialization failed"
                ),

                "error": str(error)

            })
        )


        raise


    finally:

        if connection:

            connection.close()
