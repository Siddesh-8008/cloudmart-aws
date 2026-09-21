
import os
from datetime import datetime, timezone

import boto3
import pymysql
from flask import Flask, render_template


# ============================================================
# FLASK APPLICATION
# ============================================================

app = Flask(__name__)


# ============================================================
# ENVIRONMENT
# ============================================================

ENVIRONMENT = os.environ.get(
    "ENVIRONMENT",
    "dev"
)

AWS_REGION = os.environ.get(
    "AWS_REGION",
    "ap-south-1"
)


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
# REPORT BUCKET
# ============================================================

REPORT_BUCKET = os.environ[
    "REPORT_BUCKET"
]


# ============================================================
# AWS CLIENTS
# ============================================================

ssm = boto3.client(
    "ssm",
    region_name=AWS_REGION
)

s3 = boto3.client(
    "s3",
    region_name=AWS_REGION
)


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

        connect_timeout=5,

        read_timeout=10,

        write_timeout=10,

        autocommit=True
    )


# ============================================================
# LOAD DASHBOARD DATA
# ============================================================

def load_dashboard_data():

    connection = get_connection()

    try:

        with connection.cursor() as cursor:

            # ------------------------------------------------
            # INVENTORY
            # ------------------------------------------------

            cursor.execute(
                """
                SELECT
                    id,
                    name,
                    price,
                    stock,
                    low_stock_threshold,

                    CASE
                        WHEN stock <= low_stock_threshold
                        THEN 'LOW'
                        ELSE 'HEALTHY'
                    END AS inventory_status

                FROM products

                WHERE is_active = TRUE

                ORDER BY
                    CASE
                        WHEN stock <= low_stock_threshold
                        THEN 0
                        ELSE 1
                    END,

                    stock ASC,

                    id ASC
                """
            )

            products = cursor.fetchall()


            # ------------------------------------------------
            # RECENT ORDERS
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

                ORDER BY o.created_at DESC

                LIMIT 12
                """
            )

            recent_orders = cursor.fetchall()


            # ------------------------------------------------
            # PRODUCT COUNT
            # ------------------------------------------------

            cursor.execute(
                """
                SELECT COUNT(*) AS value

                FROM products

                WHERE is_active = TRUE
                """
            )

            product_count = (
                cursor.fetchone()["value"]
            )


            # ------------------------------------------------
            # LOW STOCK COUNT
            # ------------------------------------------------

            cursor.execute(
                """
                SELECT COUNT(*) AS value

                FROM products

                WHERE is_active = TRUE

                  AND stock <= low_stock_threshold
                """
            )

            low_stock_count = (
                cursor.fetchone()["value"]
            )


            # ------------------------------------------------
            # TODAY'S ORDERS
            # ------------------------------------------------

            cursor.execute(
                """
                SELECT COUNT(*) AS value

                FROM orders

                WHERE DATE(created_at)
                    = CURRENT_DATE
                """
            )

            today_orders = (
                cursor.fetchone()["value"]
            )


            # ------------------------------------------------
            # TODAY'S FAILED ORDERS
            # ------------------------------------------------

            cursor.execute(
                """
                SELECT COUNT(*) AS value

                FROM orders o

                INNER JOIN order_status s
                    ON s.status_id = o.status_id

                WHERE DATE(o.created_at)
                    = CURRENT_DATE

                  AND s.status_name = 'FAILED'
                """
            )

            today_failed = (
                cursor.fetchone()["value"]
            )


        return {
            "products": products,

            "recent_orders":
                recent_orders,

            "stats": {
                "product_count":
                    product_count,

                "low_stock_count":
                    low_stock_count,

                "today_orders":
                    today_orders,

                "today_failed":
                    today_failed
            },

            "database_ok":
                True
        }


    finally:

        connection.close()


# ============================================================
# GET LATEST S3 REPORT
# ============================================================

def get_latest_report():

    paginator = s3.get_paginator(
        "list_objects_v2"
    )

    latest = None


    for page in paginator.paginate(
        Bucket=REPORT_BUCKET,
        Prefix="daily/"
    ):

        for item in page.get(
            "Contents",
            []
        ):

            if not item[
                "Key"
            ].endswith(".csv"):

                continue


            if (
                latest is None
                or item["LastModified"]
                > latest["LastModified"]
            ):

                latest = item


    if latest is None:

        return None


    download_url = (
        s3.generate_presigned_url(
            "get_object",

            Params={
                "Bucket":
                    REPORT_BUCKET,

                "Key":
                    latest["Key"]
            },

            ExpiresIn=900
        )
    )


    return {
        "key":
            latest["Key"],

        "name":
            latest["Key"].split("/")[-1],

        "generated_at":
            latest["LastModified"],

        "download_url":
            download_url
    }


# ============================================================
# MAIN DASHBOARD
# ============================================================

@app.route("/")
def dashboard():

    database_error = None


    data = {

        "products": [],

        "recent_orders": [],

        "stats": {

            "product_count": 0,

            "low_stock_count": 0,

            "today_orders": 0,

            "today_failed": 0
        },

        "database_ok": False
    }


    try:

        data = load_dashboard_data()


    except Exception as exc:

        database_error = str(
            exc
        )


    try:

        latest_report = (
            get_latest_report()
        )


    except Exception:

        latest_report = None


    return render_template(
        "index.html",

        environment=ENVIRONMENT,

        updated_at=datetime.now(
            timezone.utc
        ),

        latest_report=
            latest_report,

        database_error=
            database_error,

        **data
    )


# ============================================================
# HEALTH CHECK
# ============================================================

@app.get("/health")
def health():

    try:

        connection = (
            get_connection()
        )

        connection.close()


        return {
            "status": "ok",
            "environment":
                ENVIRONMENT
        }, 200


    except Exception as exc:

        return {

            "status": "error",

            "environment":
                ENVIRONMENT,

            "message":
                str(exc)

        }, 503


# ============================================================
# LOCAL DEVELOPMENT
# ============================================================

if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=8000,
        debug=False
    )

