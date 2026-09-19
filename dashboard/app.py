import os
from datetime import datetime, timezone

import boto3
import pymysql
from flask import Flask, render_template_string

app = Flask(__name__)

REGION = os.environ.get("AWS_REGION", "ap-south-1")
ENVIRONMENT = os.environ.get("ENVIRONMENT", "dev")
REPORT_BUCKET = os.environ["REPORT_BUCKET"]
REPORT_PREFIX = os.environ.get("REPORT_PREFIX", "reports/")
DB_HOST_PARAMETER = os.environ["DB_HOST_PARAMETER"]
DB_PORT_PARAMETER = os.environ.get("DB_PORT_PARAMETER")
DB_NAME_PARAMETER = os.environ["DB_NAME_PARAMETER"]
DB_USERNAME_PARAMETER = os.environ["DB_USERNAME_PARAMETER"]
DB_PASSWORD_PARAMETER = os.environ["DB_PASSWORD_PARAMETER"]

ssm = boto3.client("ssm", region_name=REGION)
s3 = boto3.client("s3", region_name=REGION)

TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>CloudMart Operations Dashboard</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 0; background: #f4f6f8; color: #1f2937; }
        header { background: #111827; color: white; padding: 24px 32px; }
        main { padding: 24px 32px; max-width: 1400px; margin: auto; }
        .cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 16px; margin-bottom: 24px; }
        .card { background: white; border-radius: 10px; padding: 18px; box-shadow: 0 2px 8px rgba(0,0,0,.08); }
        .card h3 { margin: 0 0 8px; font-size: 14px; color: #6b7280; }
        .card p { margin: 0; font-size: 28px; font-weight: bold; }
        section { background: white; border-radius: 10px; padding: 20px; margin-bottom: 24px; box-shadow: 0 2px 8px rgba(0,0,0,.08); overflow-x: auto; }
        table { width: 100%; border-collapse: collapse; min-width: 700px; }
        th, td { padding: 10px; border-bottom: 1px solid #e5e7eb; text-align: left; }
        th { background: #f9fafb; }
        .low { font-weight: bold; }
        .report { display: inline-block; padding: 10px 14px; background: #2563eb; color: white; text-decoration: none; border-radius: 6px; }
        .muted { color: #6b7280; }
        .error { color: #b91c1c; font-weight: bold; }
    </style>
</head>
<body>
<header>
    <h1>CloudMart Operations Dashboard</h1>
    <div>Environment: {{ environment }} | Generated: {{ generated_at }}</div>
</header>
<main>
    {% if error %}
        <section><div class="error">{{ error }}</div></section>
    {% else %}
        <div class="cards">
            <div class="card"><h3>Products</h3><p>{{ product_count }}</p></div>
            <div class="card"><h3>Active Products</h3><p>{{ active_product_count }}</p></div>
            <div class="card"><h3>Low Stock Products</h3><p>{{ low_stock_count }}</p></div>
            <div class="card"><h3>Recent Orders</h3><p>{{ orders|length }}</p></div>
        </div>

        <section>
            <h2>Current Product Inventory</h2>
            <table>
                <thead><tr><th>ID</th><th>Product</th><th>Stock</th><th>Threshold</th><th>Active</th><th>Updated</th></tr></thead>
                <tbody>
                {% for p in products %}
                    <tr>
                        <td>{{ p.id }}</td>
                        <td>{{ p.name }}</td>
                        <td class="{% if p.stock <= p.low_stock_threshold %}low{% endif %}">{{ p.stock }}</td>
                        <td>{{ p.low_stock_threshold }}</td>
                        <td>{{ "YES" if p.is_active else "NO" }}</td>
                        <td>{{ p.updated_at }}</td>
                    </tr>
                {% endfor %}
                </tbody>
            </table>
        </section>

        <section>
            <h2>Recent Orders</h2>
            <table>
                <thead><tr><th>Order ID</th><th>Customer</th><th>Total</th><th>Status</th><th>Created</th></tr></thead>
                <tbody>
                {% for o in orders %}
                    <tr>
                        <td>{{ o.order_id }}</td>
                        <td>{{ o.customer_id }}</td>
                        <td>₹{{ "%.2f"|format(o.total_amount|float) }}</td>
                        <td>{{ o.status }}</td>
                        <td>{{ o.created_at }}</td>
                    </tr>
                {% endfor %}
                </tbody>
            </table>
        </section>

        <section>
            <h2>Latest S3 Daily Report</h2>
            {% if report_url %}
                <a class="report" href="{{ report_url }}" target="_blank" rel="noopener">Open latest CSV report</a>
                <p class="muted">{{ report_key }}</p>
            {% else %}
                <p class="muted">No daily report has been written to S3 yet.</p>
            {% endif %}
        </section>
    {% endif %}
</main>
</body>
</html>
"""


def parameter(name):
    return ssm.get_parameter(Name=name, WithDecryption=False)["Parameter"]["Value"]


def connection():
    return pymysql.connect(
        host=parameter(DB_HOST_PARAMETER),
        port=int(parameter(DB_PORT_PARAMETER)) if DB_PORT_PARAMETER else 3306,
        user=parameter(DB_USERNAME_PARAMETER),
        password=parameter(DB_PASSWORD_PARAMETER),
        database=parameter(DB_NAME_PARAMETER),
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=10,
        autocommit=True,
    )


def latest_report():
    result = s3.list_objects_v2(Bucket=REPORT_BUCKET, Prefix=REPORT_PREFIX)
    objects = result.get("Contents", [])
    if not objects:
        return None, None
    latest = max(objects, key=lambda item: item["LastModified"])
    url = s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": REPORT_BUCKET, "Key": latest["Key"]},
        ExpiresIn=3600,
    )
    return latest["Key"], url


@app.get("/")
def index():
    db = None
    try:
        db = connection()
        with db.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, name, stock, low_stock_threshold, is_active, updated_at
                FROM products
                ORDER BY id
                """
            )
            products = cursor.fetchall()

            cursor.execute(
                """
                SELECT o.order_id, o.customer_id, o.total_amount,
                       os.status_name AS status, o.created_at
                FROM orders o
                JOIN order_status os ON o.status_id = os.status_id
                ORDER BY o.created_at DESC
                LIMIT 20
                """
            )
            orders = cursor.fetchall()

        report_key, report_url = latest_report()
        return render_template_string(
            TEMPLATE,
            environment=ENVIRONMENT,
            generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
            products=products,
            orders=orders,
            product_count=len(products),
            active_product_count=sum(1 for p in products if p["is_active"]),
            low_stock_count=sum(
                1 for p in products
                if p["is_active"] and p["stock"] <= p["low_stock_threshold"]
            ),
            report_key=report_key,
            report_url=report_url,
            error=None,
        )
    except Exception as exc:
        app.logger.exception("Dashboard request failed")
        return render_template_string(
            TEMPLATE,
            environment=ENVIRONMENT,
            generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
            products=[],
            orders=[],
            product_count=0,
            active_product_count=0,
            low_stock_count=0,
            report_key=None,
            report_url=None,
            error=f"Dashboard error: {exc}",
        ), 500
    finally:
        if db:
            db.close()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
