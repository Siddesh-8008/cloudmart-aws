import csv
import io
import logging
import os
from datetime import datetime, timezone

import boto3
import pymysql


logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3 = boto3.client("s3")
ssm = boto3.client("ssm")

ENVIRONMENT = os.environ.get("ENVIRONMENT", "dev")
REPORT_BUCKET = os.environ["REPORT_BUCKET"]
REPORT_PREFIX = os.environ.get("REPORT_PREFIX", "reports/")
DB_HOST_PARAMETER = os.environ["DB_HOST_PARAMETER"]
DB_PORT_PARAMETER = os.environ.get("DB_PORT_PARAMETER")
DB_NAME_PARAMETER = os.environ["DB_NAME_PARAMETER"]
DB_USERNAME_PARAMETER = os.environ["DB_USERNAME_PARAMETER"]
DB_PASSWORD_PARAMETER = os.environ["DB_PASSWORD_PARAMETER"]


def get_parameter(name):
    return ssm.get_parameter(Name=name, WithDecryption=False)["Parameter"]["Value"]


def get_connection():
    return pymysql.connect(
        host=get_parameter(DB_HOST_PARAMETER),
        port=int(get_parameter(DB_PORT_PARAMETER)) if DB_PORT_PARAMETER else 3306,
        user=get_parameter(DB_USERNAME_PARAMETER),
        password=get_parameter(DB_PASSWORD_PARAMETER),
        database=get_parameter(DB_NAME_PARAMETER),
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=10,
        autocommit=True,
    )


def build_report(connection):
    with connection.cursor() as cursor:
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
            "updated_at",
        ]
    )

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
                product["updated_at"],
            ]
        )

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
                order["updated_at"],
            ]
        )

    return output.getvalue().encode("utf-8")


def lambda_handler(event, context):
    connection = None
    report_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    key = f"{REPORT_PREFIX.rstrip('/')}/daily-report-{report_date}.csv"

    try:
        connection = get_connection()
        report = build_report(connection)

        s3.put_object(
            Bucket=REPORT_BUCKET,
            Key=key,
            Body=report,
            ContentType="text/csv",
            ServerSideEncryption="AES256",
        )

        logger.info(
            "Daily report written to s3://%s/%s",
            REPORT_BUCKET,
            key,
        )

        return {
            "statusCode": 200,
            "bucket": REPORT_BUCKET,
            "key": key,
        }

    except Exception:
        logger.exception("Daily report generation failed")
        raise

    finally:
        if connection:
            connection.close()
