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
            # IMPORTANT:
            # Only SHA-256 token hashes are stored here.
            # The actual customer token is never stored.
            # =================================================

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS customer_auth_tokens (

                    token_id BIGINT NOT NULL AUTO_INCREMENT,

                    customer_id VARCHAR(100) NOT NULL,

                    token_hash CHAR(64) NOT NULL,

                    is_active BOOLEAN NOT NULL DEFAULT TRUE,

                    created_at TIMESTAMP
                        DEFAULT CURRENT_TIMESTAMP,

                    expires_at TIMESTAMP NULL,

                    last_used_at TIMESTAMP NULL,

                    PRIMARY KEY (
                        token_id
                    ),

                    UNIQUE KEY uq_customer_token_hash (
                        token_hash
                    ),

                    KEY idx_customer_auth_customer (
                        customer_id
                    ),

                    CONSTRAINT fk_customer_auth_customer

                        FOREIGN KEY (
                            customer_id
                        )

                        REFERENCES customers(
                            customer_id
                        )

                        ON DELETE CASCADE

                )
                ENGINE=InnoDB
                DEFAULT CHARSET=utf8mb4
                COLLATE=utf8mb4_unicode_ci
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
                )
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
                    "Products, customers, authentication "
                    "and order tables created successfully"
                )
            })
        )


        return {

            "statusCode": 200,

            "body": json.dumps({

                "message": (
                    "Products, customers, authentication "
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
