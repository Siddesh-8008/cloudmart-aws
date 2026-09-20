import csv
import io
import logging
import os
from datetime import datetime, timezone

import boto3
import pymysql


# ============================================================
# LOGGING
# ============================================================

logger = logging.getLogger()
logger.setLevel(logging.INFO)


# ============================================================
# AWS CLIENTS
# ============================================================

ssm = boto3.client("ssm")
s3 = boto3.client("s3")


# ============================================================
# ENVIRONMENT VARIABLES
# ============================================================

ENVIRONMENT = os.environ.get("ENVIRONMENT", "dev")

REPORT_BUCKET = os.environ["REPORT_BUCKET"]
REPORT_PREFIX = os.environ.get("REPORT_PREFIX", "reports/")

DB_HOST_PARAMETER = os.environ["DB_HOST_PARAMETER"]
DB_PORT_PARAMETER = os.environ["DB_PORT_PARAMETER"]
DB_NAME_PARAMETER = os.environ["DB_NAME_PARAMETER"]
DB_USERNAME_PARAMETER = os.environ["DB_USERNAME_PARAMETER"]
DB_PASSWORD_PARAMETER = os.environ["DB_PASSWORD_PARAMETER"]


# ============================================================
# READ SSM PARAMETER
# ============================================================

def get_parameter(parameter_name):
    response = ssm.get_parameter(
        Name=parameter_name,
        WithDecryption=False
    )

    return response["Parameter"]["Value"]


# ============================================================
# DATABASE CONNECTION
# ============================================================

def get_connection():

    host = get_parameter(DB_HOST_PARAMETER)
    port = int(get_parameter(DB_PORT_PARAMETER))
    username = get_parameter(DB_USERNAME_PARAMETER)
    password = get_parameter(DB_PASSWORD_PARAMETER)
    database = get_parameter(DB_NAME_PARAMETER)

    logger.info(
        "Connecting to RDS database %s on port %s",
        database,
        port
    )

    connection = pymysql.connect(
        host=host,
        port=port,
        user=username,
        password=password,
        database=database,
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=10,
        read_timeout=30,
        write_timeout=30,
        autocommit=True
    )

    logger.info("RDS connection established")

    return connection


# ============================================================
# BUILD CSV REPORT
# ============================================================

def build_report(connection):

    with connection.cursor() as cursor:

        # ----------------------------------------------------
        # PRODUCTS
        # ----------------------------------------------------

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
            len(products)
        )

        # ----------------------------------------------------
        # RECENT ORDERS
        # ----------------------------------------------------

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
            len(orders)
        )

    # --------------------------------------------------------
    # CREATE CSV
    # --------------------------------------------------------

    output = io.StringIO()

    writer = csv.writer(output)

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
            "updated_at"
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
                product["low_stock_threshold"],
                product["is_active"],
                "",
                "",
                "",
                "",
                "",
                "",
                product["updated_at"]
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
                order["failure_reason"] or "",
                order["created_at"],
                order["updated_at"]
            ]
        )

    return output.getvalue().encode("utf-8")


# ============================================================
# LAMBDA HANDLER
# ============================================================

def lambda_handler(event, context):

    connection = None

    report_date = datetime.now(
        timezone.utc
    ).strftime("%Y-%m-%d")

    key = (
        f"{REPORT_PREFIX.rstrip('/')}"
        f"/daily-report-{report_date}.csv"
    )

    logger.info(
        "Starting CloudMart daily report"
    )

    logger.info(
        "Report destination: s3://%s/%s",
        REPORT_BUCKET,
        key
    )

    try:

        # ----------------------------------------------------
        # CONNECT TO RDS
        # ----------------------------------------------------

        connection = get_connection()

        # ----------------------------------------------------
        # GENERATE REPORT
        # ----------------------------------------------------

        report = build_report(connection)

        logger.info(
            "Report generated: %s bytes",
            len(report)
        )

        # ----------------------------------------------------
        # UPLOAD REPORT TO S3
        # ----------------------------------------------------

        logger.info(
            "Uploading report to S3"
        )

        s3.put_object(
            Bucket=REPORT_BUCKET,
            Key=key,
            Body=report,
            ContentType="text/csv",
            ServerSideEncryption="AES256"
        )

        logger.info(
            "Report uploaded successfully to s3://%s/%s",
            REPORT_BUCKET,
            key
        )

        return {
            "statusCode": 200,
            "bucket": REPORT_BUCKET,
            "key": key
        }

    except Exception:

        logger.exception(
            "Daily report generation failed"
        )

        raise

    finally:

        if connection is not None:

            connection.close()

            logger.info(
                "RDS connection closed"
            )