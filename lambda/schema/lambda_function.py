import os
import json
import boto3
import pymysql


ssm = boto3.client("ssm")


def get_parameter(name, secure=False):
    return ssm.get_parameter(
        Name=name,
        WithDecryption=secure
    )["Parameter"]["Value"]


def get_database_connection():

    db_port_parameter = os.environ.get("DB_PORT_PARAMETER")

    if db_port_parameter:
        db_port = int(get_parameter(db_port_parameter))
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

        autocommit=False,
    )


def lambda_handler(event, context):

    print(
        json.dumps(
            {
                "message": "Schema Lambda invoked",
                "request_id": context.aws_request_id
            }
        )
    )

    connection = None

    try:

        connection = get_database_connection()

        with connection.cursor() as cursor:

            # ====================================================
            # PRODUCTS TABLE
            # ====================================================

            cursor.execute(
                """
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
                COLLATE=utf8mb4_unicode_ci
                """
            )


            # ====================================================
            # ORDER STATUS TABLE
            # ====================================================

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS order_status (

                    status_id TINYINT NOT NULL AUTO_INCREMENT,

                    status_name VARCHAR(30) NOT NULL,

                    description VARCHAR(255) NULL,

                    PRIMARY KEY (status_id),

                    UNIQUE KEY uq_order_status_name (status_name)

                ) ENGINE=InnoDB
                DEFAULT CHARSET=utf8mb4
                COLLATE=utf8mb4_unicode_ci
                """
            )


            # ====================================================
            # INSERT ORDER STATUSES
            # ====================================================

            cursor.executemany(
                """
                INSERT INTO order_status (
                    status_name,
                    description
                )

                VALUES (%s, %s)

                ON DUPLICATE KEY UPDATE
                    description = VALUES(description)
                """,

                [
                    (
                        "PENDING",
                        "Order created and waiting for processing"
                    ),

                    (
                        "CONFIRMED",
                        "Order processed and inventory deducted"
                    ),

                    (
                        "FAILED",
                        "Order processing failed"
                    ),
                ],
            )


            # ====================================================
            # ORDERS TABLE
            # ====================================================

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS orders (

                    order_id BIGINT NOT NULL AUTO_INCREMENT,

                    customer_id VARCHAR(100) NOT NULL,

                    total_amount DECIMAL(12,2) NOT NULL,

                    status_id TINYINT NOT NULL,

                    failure_reason VARCHAR(1000) NULL,

                    created_at TIMESTAMP NOT NULL
                        DEFAULT CURRENT_TIMESTAMP,

                    updated_at TIMESTAMP NOT NULL
                        DEFAULT CURRENT_TIMESTAMP
                        ON UPDATE CURRENT_TIMESTAMP,

                    PRIMARY KEY (order_id),

                    KEY idx_orders_customer_created (
                        customer_id,
                        created_at
                    ),

                    KEY idx_orders_status (
                        status_id
                    ),

                    CONSTRAINT fk_orders_status
                        FOREIGN KEY (status_id)
                        REFERENCES order_status(status_id)

                ) ENGINE=InnoDB
                DEFAULT CHARSET=utf8mb4
                COLLATE=utf8mb4_unicode_ci
                """
            )


            # ====================================================
            # ORDER ITEMS TABLE
            # ====================================================

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS order_items (

                    order_item_id BIGINT NOT NULL AUTO_INCREMENT,

                    order_id BIGINT NOT NULL,

                    product_id BIGINT NOT NULL,

                    quantity INT NOT NULL,

                    unit_price DECIMAL(10,2) NOT NULL,

                    line_total DECIMAL(12,2) NOT NULL,

                    created_at TIMESTAMP NOT NULL
                        DEFAULT CURRENT_TIMESTAMP,

                    PRIMARY KEY (order_item_id),

                    KEY idx_order_items_order (
                        order_id
                    ),

                    KEY idx_order_items_product (
                        product_id
                    ),

                    CONSTRAINT fk_order_items_order
                        FOREIGN KEY (order_id)
                        REFERENCES orders(order_id)
                        ON DELETE CASCADE,

                    CONSTRAINT fk_order_items_product
                        FOREIGN KEY (product_id)
                        REFERENCES products(id)

                ) ENGINE=InnoDB
                DEFAULT CHARSET=utf8mb4
                COLLATE=utf8mb4_unicode_ci
                """
            )


        # ========================================================
        # COMMIT
        # ========================================================

        connection.commit()


        return {
            "statusCode": 200,

            "body": json.dumps(
                {
                    "message":
                        "Products and order tables created successfully"
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

