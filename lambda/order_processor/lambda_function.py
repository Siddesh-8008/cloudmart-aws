import json
import os
import boto3
import pymysql

ssm = boto3.client("ssm")
events = boto3.client("events")


def get_parameter(name, secure=False):
    return ssm.get_parameter(Name=name, WithDecryption=secure)["Parameter"]["Value"]


def get_database_connection():
    return pymysql.connect(
        host=get_parameter(os.environ["DB_HOST_PARAMETER"]),
        user=get_parameter(os.environ["DB_USERNAME_PARAMETER"], secure=True),
        password=get_parameter(os.environ["DB_PASSWORD_PARAMETER"], secure=True),
        database=get_parameter(os.environ["DB_NAME_PARAMETER"]),
        port=int(get_parameter(os.environ.get("DB_PORT_PARAMETER", "3306"))),
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=10,
        autocommit=False,
    )


def publish_event(detail_type, detail):
    result = events.put_events(
        Entries=[
            {
                "EventBusName": os.environ["EVENT_BUS_NAME"],
                "Source": "cloudmart.orders",
                "DetailType": detail_type,
                "Detail": json.dumps(detail, default=str),
            }
        ]
    )
    if result.get("FailedEntryCount", 0):
        raise RuntimeError(f"EventBridge failed to publish {detail_type}: {result}")


def set_failed(order_id, reason):
    connection = None
    try:
        connection = get_database_connection()
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT status_id FROM order_status WHERE status_name = 'FAILED'"
            )
            failed_status = cursor.fetchone()
            if not failed_status:
                raise RuntimeError("FAILED status does not exist")
            cursor.execute(
                """
                UPDATE orders
                SET status_id = %s,
                    failure_reason = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE order_id = %s
                """,
                (failed_status["status_id"], str(reason)[:1000], order_id),
            )
        connection.commit()
    finally:
        if connection:
            connection.close()


def process_order(order_id, context):
    connection = None
    order_detail = None
    try:
        connection = get_database_connection()
        with connection.cursor() as cursor:
            # Lock the order so two processor executions cannot confirm it twice.
            cursor.execute(
                """
                SELECT
                    o.order_id,
                    o.customer_id,
                    o.total_amount,
                    s.status_name AS status
                FROM orders o
                JOIN order_status s ON s.status_id = o.status_id
                WHERE o.order_id = %s
                FOR UPDATE
                """,
                (order_id,),
            )
            order = cursor.fetchone()
            if not order:
                raise RuntimeError(f"Order {order_id} not found")

            # Idempotency: an already completed/failed order is not processed again.
            if order["status"] != "PENDING":
                connection.rollback()
                print(json.dumps({
                    "level": "INFO",
                    "message": "Order already processed",
                    "orderId": order_id,
                    "status": order["status"],
                }))
                return

            cursor.execute(
                """
                SELECT order_item_id, product_id, quantity, unit_price, line_total
                FROM order_items
                WHERE order_id = %s
                ORDER BY order_item_id
                """,
                (order_id,),
            )
            items = cursor.fetchall()
            if not items:
                raise RuntimeError("Order has no items")

            # Lock all inventory rows before checking/deducting stock.
            for item in items:
                cursor.execute(
                    """
                    SELECT id, name, stock, low_stock_threshold
                    FROM products
                    WHERE id = %s
                    FOR UPDATE
                    """,
                    (item["product_id"],),
                )
                product = cursor.fetchone()
                if not product:
                    raise RuntimeError(f"Product {item['product_id']} not found")
                if product["stock"] < item["quantity"]:
                    raise RuntimeError(
                        f"Insufficient stock for product {product['id']} "
                        f"({product['name']}): requested {item['quantity']}, available {product['stock']}"
                    )

            # Deduct inventory only after every item has passed validation.
            for item in items:
                cursor.execute(
                    "UPDATE products SET stock = stock - %s WHERE id = %s",
                    (item["quantity"], item["product_id"]),
                )

            cursor.execute(
                "SELECT status_id FROM order_status WHERE status_name = 'CONFIRMED'"
            )
            confirmed_status = cursor.fetchone()
            if not confirmed_status:
                raise RuntimeError("CONFIRMED status does not exist")

            cursor.execute(
                """
                UPDATE orders
                SET status_id = %s,
                    failure_reason = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE order_id = %s
                """,
                (confirmed_status["status_id"], order_id),
            )

            order_detail = {
                "orderId": order["order_id"],
                "customerId": str(order["customer_id"]),
                "totalAmount": order["total_amount"],
                "status": "CONFIRMED",
                "items": [
                    {"productId": item["product_id"], "quantity": item["quantity"]}
                    for item in items
                ],
            }

        # Inventory deduction and status change are atomic.
        connection.commit()

        # EventBridge -> SNS is the single notification path.
        publish_event("OrderConfirmed", order_detail)
        print(json.dumps({"level": "INFO", "message": "Order confirmed", "orderId": order_id}))

    except Exception as error:
        if connection:
            connection.rollback()
        reason = str(error)
        print(json.dumps({
            "level": "ERROR",
            "message": "Order processing failed",
            "orderId": order_id,
            "error": reason,
            "requestId": context.aws_request_id,
        }))

        # Persist the failure in RDS because this architecture intentionally does
        # not use SQS/DLQ.
        try:
            set_failed(order_id, reason)
            publish_event(
                "OrderFailed",
                {
                    "orderId": order_id,
                    "status": "FAILED",
                    "reason": reason,
                },
            )
        except Exception as failure_record_error:
            print(json.dumps({
                "level": "ERROR",
                "message": "Could not record/publish order failure",
                "orderId": order_id,
                "error": str(failure_record_error),
            }))
        # Do not re-raise: failure is intentionally retained in RDS rather than DLQ.
    finally:
        if connection:
            connection.close()


def lambda_handler(event, context):
    print(json.dumps({"level": "INFO", "message": "Order Processor invoked", "event": event}))
    order_id = event.get("orderId")
    if not order_id:
        raise ValueError("orderId is required")
    process_order(int(order_id), context)
    return {"status": "completed", "orderId": int(order_id)}
