import csv
import io
import logging
import os
from datetime import datetime, timezone

import boto3
import pymysql
from botocore.config import Config


# ============================================================
# LOGGING
# ============================================================

logger = logging.getLogger()
logger.setLevel(logging.INFO)


# ============================================================
# AWS CLIENT CONFIGURATION
# ============================================================

aws_config = Config(
    connect_timeout=5,
    read_timeout=10,
    retries={
        "max_attempts": 2,
        "mode": "standard",
    },
)


s3 = boto3.client(
    "s3",
    config=aws_config,
)

ssm = boto3.client(
    "ssm",
    config=aws_config,
)


# ============================================================
# ENVIRONMENT VARIABLES
# ============================================================

ENVIRONMENT = os.environ.get(
    "ENVIRONMENT",
    "dev",
)

REPORT_BUCKET = os.environ["REPORT_BUCKET"]

REPORT_PREFIX = os.environ.get(
    "REPORT_PREFIX",
    "reports/",
)

DB_HOST_PARAMETER = os.environ[
    "DB_HOST_PARAMETER"
]

DB_PORT_PARAMETER = os.environ.get(
    "DB_PORT_PARAMETER"
)

DB_NAME_PARAMETER = os.environ[
    "DB_NAME_PARAMETER"
]

DB_USERNAME_PARAMETER = os.environ[
    "DB_USERNAME_PARAMETER"
]

DB_PASSWORD_PARAMETER = os.environ[
    "DB_PASSWORD_PARAMETER"
]


# ============================================================
# SSM PARAMETER
# ============================================================

def get_parameter(name):

    logger.info(
        "Reading SSM parameter: %s",
        name,
    )

    try:

        response = ssm.get_parameter(
            Name=name,
            WithDecryption=False,
        )

        value = response[
            "Parameter"
        ][
            "Value"
        ]

        logger.info(
            "Successfully read SSM parameter: %s",
            name,
        )

        return value

    except Exception:

        logger.exception(
            "Failed to read SSM parameter: %s",
            name,
        )

        raise


# ============================================================
# DATABASE CONNECTION
# ============================================================

def get_connection():

    logger.info(
        "Starting database connection setup"
    )

    host = get_parameter(
        DB_HOST_PARAMETER
    )

    logger.info(
        "Database host parameter retrieved"
    )

    if DB_PORT_PARAMETER:

        port = int(
            get_parameter(
                DB_PORT_PARAMETER
            )
        )

    else:

        port = 3306

    logger.info(
        "Database port: %s",
        port,
    )

    username = get_parameter(
        DB_USERNAME_PARAMETER
    )

    logger.info(
        "Database username retrieved"
    )

    password = get_parameter(
        DB_PASSWORD_PARAMETER
    )

    logger.info(
        "Database password retrieved"
    )

    database = get_parameter(
        DB_NAME_PARAMETER
    )

    logger.info(
        "Database name retrieved: %s",
        database,
    )

    logger.info(
        "Connecting to RDS: %s:%s/%s",
        host,
        port,
        database,
    )

    connection = pymysql.connect(
        host=host,
        port=port,
        user=username,
        password=password,
        database=database,
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=10,
        autocommit=True,
    )

    logger.info(
        "RDS connection established successfully"
    )

    return connection


# ============================================================
# BUILD REPORT
# ============================================================

def build_report(connection):

    logger.info(
        "Starting report generation"
    )

    with connection.cursor() as cursor:

        # ----------------------------------------------------
        # PRODUCTS
        # ----------------------------------------------------

        logger.info(
            "Querying products"
        )

        cursor.execute(
            """
            SELECT
                id,
                name,
                stock,
                low_stock_threshold,
                is_active,
                updated_at
            FROM products
            ORDER BY id
            """
        )

        products = cursor.fetchall()

        logger.info(
            "Products retrieved: %s",
            len(products),
        )

        # ----------------------------------------------------
        # ORDERS
        # ----------------------------------------------------

        logger.info(
            "Querying recent orders"
        )

        cursor.execute(
            """
            SELECT
                o.order_id,
                o.customer_id,
                o.total_amount,
                os.status_name AS status,
                o.failure_reason,
                o.created_at,
                o.updated_at
            FROM orders o
            JOIN order_status os
              ON o.status_id = os.status_id
            ORDER BY o.created_at DESC
            LIMIT 50
            """
        )

        orders = cursor.fetchall()

        logger.info(
            "Orders retrieved: %s",
            len(orders),
        )

    # --------------------------------------------------------
    # CSV
    # --------------------------------------------------------

    output = io.StringIO()

    writer = csv.writer(
        output
    )

    writer.writerow(
        [
            "record_type",
            "product_id",
            "product_name",
            "stock",
            "low_stock_threshold",
            "is_active",
            "order_id",
            "customer_id",
            "total_amount",
            "status",
            "failure_reason",
            "created_at",
            "updated_at",
        ]
    )

    # --------------------------------------------------------
    # PRODUCT ROWS
    # --------------------------------------------------------

    for product in products:

        writer.writerow(
            [
                "PRODUCT",
                product["id"],
                product["name"],
                product["stock"],
                product[
                    "low_stock_threshold"
                ],
                product["is_active"],
                "",
                "",
                "",
                "",
                "",
                "",
                product["updated_at"],
            ]
        )

    # --------------------------------------------------------
    # ORDER ROWS
    # --------------------------------------------------------

    for order in orders:

        writer.writerow(
            [
                "ORDER",
                "",
                "",
                "",
                "",
                "",
                order["order_id"],
                order["customer_id"],
                order["total_amount"],
                order["status"],
                order[
                    "failure_reason"
                ] or "",
                order["created_at"],
                order["updated_at"],
            ]
        )

    report = output.getvalue().encode(
        "utf-8"
    )

    logger.info(
        "Report generated successfully: %s bytes",
        len(report),
    )

    return report


# ============================================================
# LAMBDA HANDLER
# ============================================================

def lambda_handler(
    event,
    context,
):

    connection = None

    report_date = datetime.now(
        timezone.utc
    ).strftime(
        "%Y-%m-%d"
    )

    key = (
        f"{REPORT_PREFIX.rstrip('/')}"
        f"/daily-report-{report_date}.csv"
    )

    logger.info(
        "================================================"
    )

    logger.info(
        "Starting CloudMart daily report"
    )

    logger.info(
        "Environment: %s",
        ENVIRONMENT,
    )

    logger.info(
        "Report bucket: %s",
        REPORT_BUCKET,
    )

    logger.info(
        "Report key: %s",
        key,
    )

    logger.info(
        "================================================"
    )

    try:

        # ----------------------------------------------------
        # DATABASE
        # ----------------------------------------------------

        connection = get_connection()

        # ----------------------------------------------------
        # REPORT
        # ----------------------------------------------------

        report = build_report(
            connection
        )

        # ----------------------------------------------------
        # S3
        # ----------------------------------------------------

        logger.info(
            "Uploading report to S3"
        )

        s3.put_object(
            Bucket=REPORT_BUCKET,
            Key=key,
            Body=report,
            ContentType="text/csv",
            ServerSideEncryption="AES256",
        )

        logger.info(
            "Daily report written successfully to "
            "s3://%s/%s",
            REPORT_BUCKET,
            key,
        )

        return {
            "statusCode": 200,
            "bucket": REPORT_BUCKET,
            "key": key,
        }

    except Exception:

        logger.exception(
            "Daily report generation failed"
        )

        raise

    finally:

        if connection:

            connection.close()

            logger.info(
                "Database connection closed"
            )