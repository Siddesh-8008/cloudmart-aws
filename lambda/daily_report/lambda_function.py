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
# ENVIRONMENT
# ============================================================

ENVIRONMENT = os.environ.get(
    "ENVIRONMENT",
    "dev"
)

REPORT_BUCKET = os.environ["REPORT_BUCKET"]


# ============================================================
# DATABASE PARAMETERS
# ============================================================

DB_HOST_PARAMETER = os.environ[
    "DB_HOST_PARAMETER"
]

DB_PORT_PARAMETER = os.environ[
    "DB_PORT_PARAMETER"
]

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

    return ssm.get_parameter(
        Name=name,
        WithDecryption=True
    )["Parameter"]["Value"]


# ============================================================
# DATABASE CONNECTION
# ============================================================

def get_connection():

    return pymysql.connect(
        host=get_parameter(
            DB_HOST_PARAMETER
        ),

        port=int(
            get_parameter(
                DB_PORT_PARAMETER
            )
        ),

        user=get_parameter(
            DB_USERNAME_PARAMETER
        ),

        password=get_parameter(
            DB_PASSWORD_PARAMETER
        ),

        database=get_parameter(
            DB_NAME_PARAMETER
        ),

        cursorclass=pymysql.cursors.DictCursor,

        connect_timeout=10,

        read_timeout=30,

        write_timeout=30,

        autocommit=True
    )


# ============================================================
# BUILD DAILY REPORT
# ============================================================

def build_report():

    generated_at = datetime.now(
        timezone.utc
    )

    report_date = generated_at.date()

    connection = get_connection()

    try:

        with connection.cursor() as cursor:

            # ------------------------------------------------
            # CURRENT INVENTORY
            # ------------------------------------------------

            cursor.execute(
                """
                SELECT
                    p.id,
                    p.name,
                    p.stock,
                    p.low_stock_threshold,

                    CASE
                        WHEN p.stock <= p.low_stock_threshold
                        THEN 'LOW'
                        ELSE 'OK'
                    END AS inventory_status

                FROM products p

                WHERE p.is_active = TRUE

                ORDER BY p.id
                """
            )

            inventory = cursor.fetchall()


            # ------------------------------------------------
            # TODAY'S ORDERS
            # ------------------------------------------------

            cursor.execute(
                """
                SELECT
                    o.order_id,
                    o.customer_id,
                    o.total_amount,
                    s.status_name AS status,
                    o.failure_reason,
                    o.created_at

                FROM orders o

                INNER JOIN order_status s
                    ON s.status_id = o.status_id

                WHERE DATE(o.created_at) = %s

                ORDER BY o.created_at DESC
                """,
                (
                    report_date,
                )
            )

            orders = cursor.fetchall()


            # ------------------------------------------------
            # ORDER SUMMARY
            # ------------------------------------------------

            cursor.execute(
                """
                SELECT
                    s.status_name AS status,
                    COUNT(*) AS order_count,
                    COALESCE(
                        SUM(o.total_amount),
                        0
                    ) AS total_amount

                FROM orders o

                INNER JOIN order_status s
                    ON s.status_id = o.status_id

                WHERE DATE(o.created_at) = %s

                GROUP BY s.status_name

                ORDER BY s.status_name
                """,
                (
                    report_date,
                )
            )

            summary = cursor.fetchall()


        # ====================================================
        # CREATE CSV
        # ====================================================

        output = io.StringIO()

        writer = csv.writer(
            output
        )


        writer.writerow(
            [
                "CloudMart Daily Operations Report"
            ]
        )

        writer.writerow(
            [
                "environment",
                ENVIRONMENT
            ]
        )

        writer.writerow(
            [
                "report_date",
                report_date.isoformat()
            ]
        )

        writer.writerow(
            [
                "generated_at_utc",
                generated_at.isoformat()
            ]
        )


        # ====================================================
        # ORDER SUMMARY
        # ====================================================

        writer.writerow([])

        writer.writerow(
            [
                "ORDER_SUMMARY"
            ]
        )

        writer.writerow(
            [
                "status",
                "order_count",
                "total_amount"
            ]
        )


        for row in summary:

            writer.writerow(
                [
                    row["status"],
                    row["order_count"],
                    row["total_amount"]
                ]
            )


        # ====================================================
        # ORDERS
        # ====================================================

        writer.writerow([])

        writer.writerow(
            [
                "ORDERS"
            ]
        )

        writer.writerow(
            [
                "order_id",
                "customer_id",
                "total_amount",
                "status",
                "failure_reason",
                "created_at"
            ]
        )


        for row in orders:

            writer.writerow(
                [
                    row["order_id"],
                    row["customer_id"],
                    row["total_amount"],
                    row["status"],
                    row["failure_reason"] or "",
                    row["created_at"]
                ]
            )


        # ====================================================
        # INVENTORY
        # ====================================================

        writer.writerow([])

        writer.writerow(
            [
                "INVENTORY"
            ]
        )

        writer.writerow(
            [
                "product_id",
                "product_name",
                "stock",
                "low_stock_threshold",
                "inventory_status"
            ]
        )


        for row in inventory:

            writer.writerow(
                [
                    row["id"],
                    row["name"],
                    row["stock"],
                    row["low_stock_threshold"],
                    row["inventory_status"]
                ]
            )


        return output.getvalue()


    finally:

        connection.close()


# ============================================================
# LAMBDA HANDLER
# ============================================================

def lambda_handler(
    event,
    context
):

    generated_at = datetime.now(
        timezone.utc
    )

    report_date = generated_at.date()


    try:

        csv_content = build_report()


        key = (
            f"daily/"
            f"{report_date.isoformat()}/"
            f"cloudmart-daily-report-"
            f"{generated_at.strftime('%Y%m%dT%H%M%SZ')}"
            f".csv"
        )


        s3.put_object(
            Bucket=REPORT_BUCKET,

            Key=key,

            Body=csv_content.encode(
                "utf-8"
            ),

            ContentType="text/csv",

            ServerSideEncryption="AES256"
        )


        logger.info(
            "Daily report created successfully: "
            "s3://%s/%s",
            REPORT_BUCKET,
            key
        )


        return {
            "statusCode": 200,

            "bucket": REPORT_BUCKET,

            "key": key
        }


    except Exception as exc:

        logger.exception(
            "Daily report generation failed"
        )

        raise exc