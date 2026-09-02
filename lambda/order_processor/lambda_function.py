import json
import logging
import os

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
events = boto3.client("events")


# ============================================================
# ENVIRONMENT VARIABLES
# ============================================================

EVENT_BUS_NAME = os.environ.get(
    "EVENT_BUS_NAME",
    "cloudmart-dev-event-bus"
)

DB_HOST_PARAMETER = os.environ["DB_HOST_PARAMETER"]
DB_PORT_PARAMETER = os.environ.get("DB_PORT_PARAMETER")
DB_NAME_PARAMETER = os.environ["DB_NAME_PARAMETER"]
DB_USERNAME_PARAMETER = os.environ["DB_USERNAME_PARAMETER"]
DB_PASSWORD_PARAMETER = os.environ["DB_PASSWORD_PARAMETER"]


# ============================================================
# RESPONSE HELPER
# ============================================================

def response(status_code, body):

    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json"
        },
        "body": json.dumps(body, default=str)
    }


# ============================================================
# SSM PARAMETER
# ============================================================

def get_parameter(name):

    result = ssm.get_parameter(
        Name=name,
        WithDecryption=True
    )

    return result["Parameter"]["Value"]


# ============================================================
# DATABASE CONNECTION
# ============================================================

def get_db_connection():

    host = get_parameter(DB_HOST_PARAMETER)

    if DB_PORT_PARAMETER:
        port = int(get_parameter(DB_PORT_PARAMETER))
    else:
        port = 3306

    database = get_parameter(DB_NAME_PARAMETER)
    username = get_parameter(DB_USERNAME_PARAMETER)
    password = get_parameter(DB_PASSWORD_PARAMETER)

    return pymysql.connect(
        host=host,
        port=port,
        user=username,
        password=password,
        database=database,
        connect_timeout=10,
        read_timeout=10,
        write_timeout=10,
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False
    )


# ============================================================
# EVENTBRIDGE
# ============================================================

def publish_event(detail_type, detail):

    try:

        result = events.put_events(
            Entries=[
                {
                    "Source": "cloudmart.order",
                    "DetailType": detail_type,
                    "Detail": json.dumps(detail),
                    "EventBusName": EVENT_BUS_NAME
                }
            ]
        )

        if result.get("FailedEntryCount", 0) > 0:

            logger.error(
                json.dumps({
                    "action": "event_publish_failed",
                    "detail_type": detail_type,
                    "response": result
                })
            )

            return False

        logger.info(
            json.dumps({
                "action": "event_published",
                "detail_type": detail_type,
                "detail": detail
            })
        )

        return True

    except Exception as error:

        logger.error(
            json.dumps({
                "action": "event_publish_exception",
                "detail_type": detail_type,
                "error": str(error)
            })
        )

        return False


# ============================================================
# REQUEST BODY
# ============================================================

def get_request_body(event):

    body = event.get("body")

    if body is None:
        return event

    if isinstance(body, str):

        if not body.strip():
            return {}

        return json.loads(body)

    if isinstance(body, dict):
        return body

    return {}


# ============================================================
# VALIDATE ORDER ITEMS
# ============================================================

def validate_items(items):

    if not isinstance(items, list) or len(items) == 0:

        return False, "items must contain at least one product"

    for item in items:

        if not isinstance(item, dict):

            return False, "Each item must be an object"

        if "productId" not in item:

            return False, "productId is required"

        if "quantity" not in item:

            return False, "quantity is required"

        try:
            product_id = int(item["productId"])
            quantity = int(item["quantity"])

        except (TypeError, ValueError):

            return False, "productId and quantity must be numbers"

        if product_id <= 0:

            return False, "productId must be greater than zero"

        if quantity <= 0:

            return False, "quantity must be greater than zero"

    return True, None


# ============================================================
# POST /orders
# ============================================================

def create_order(event):

    connection = None

    try:

        logger.info(
            json.dumps({
                "action": "order_creation_started"
            })
        )

        # ----------------------------------------------------
        # READ BODY
        # ----------------------------------------------------

        try:

            request = get_request_body(event)

        except json.JSONDecodeError:

            return response(
                400,
                {
                    "message": "Request body must contain valid JSON"
                }
            )

        customer_id = request.get("customerId")
        items = request.get("items")

        # ----------------------------------------------------
        # VALIDATE CUSTOMER
        # ----------------------------------------------------

        if customer_id is None or str(customer_id).strip() == "":

            return response(
                400,
                {
                    "message": "customerId is required"
                }
            )

        # ----------------------------------------------------
        # VALIDATE ITEMS
        # ----------------------------------------------------

        valid, error_message = validate_items(items)

        if not valid:

            return response(
                400,
                {
                    "message": error_message
                }
            )

        # ----------------------------------------------------
        # DATABASE CONNECTION
        # ----------------------------------------------------

        connection = get_db_connection()

        with connection.cursor() as cursor:

            # =================================================
            # GET PENDING / CONFIRMED / FAILED STATUS IDS
            # =================================================

            cursor.execute(
                """
                SELECT status_id, status_name
                FROM order_status
                WHERE status_name IN ('PENDING', 'CONFIRMED', 'FAILED')
                """
            )

            statuses = cursor.fetchall()

            status_map = {
                row["status_name"]: row["status_id"]
                for row in statuses
            }

            if "PENDING" not in status_map:
                raise Exception("PENDING order status not found")

            if "CONFIRMED" not in status_map:
                raise Exception("CONFIRMED order status not found")

            if "FAILED" not in status_map:
                raise Exception("FAILED order status not found")

            pending_status_id = status_map["PENDING"]
            confirmed_status_id = status_map["CONFIRMED"]

            # =================================================
            # CREATE ORDER AS PENDING
            # =================================================

            cursor.execute(
                """
                INSERT INTO orders
                (
                    customer_id,
                    total_amount,
                    status_id
                )
                VALUES
                (
                    %s,
                    %s,
                    %s
                )
                """,
                (
                    customer_id,
                    0,
                    pending_status_id
                )
            )

            order_id = cursor.lastrowid

            total_amount = 0
            low_stock_products = []

            # =================================================
            # PROCESS EACH ITEM
            # =================================================

            for item in items:

                product_id = int(item["productId"])
                quantity = int(item["quantity"])

                # ------------------------------------------------
                # LOCK PRODUCT ROW
                # ------------------------------------------------

                cursor.execute(
                    """
                    SELECT
                        id,
                        name,
                        price,
                        stock,
                        low_stock_threshold
                    FROM products
                    WHERE id = %s
                    FOR UPDATE
                    """,
                    (product_id,)
                )

                product = cursor.fetchone()

                if not product:

                    raise ValueError(
                        f"Product {product_id} not found"
                    )

                current_stock = int(product["stock"])
                price = float(product["price"])
                threshold = int(
                    product["low_stock_threshold"]
                )

                # ------------------------------------------------
                # CHECK STOCK
                # ------------------------------------------------

                if current_stock < quantity:

                    raise ValueError(
                        f"Insufficient stock for product "
                        f"{product_id}. Available: "
                        f"{current_stock}, requested: "
                        f"{quantity}"
                    )

                # ------------------------------------------------
                # CALCULATE TOTAL
                # ------------------------------------------------

                line_total = price * quantity

                total_amount += line_total

                # ------------------------------------------------
                # INSERT ORDER ITEM
                # ------------------------------------------------

                cursor.execute(
                    """
                    INSERT INTO order_items
                    (
                        order_id,
                        product_id,
                        quantity,
                        unit_price,
                        line_total
                    )
                    VALUES
                    (
                        %s,
                        %s,
                        %s,
                        %s,
                        %s
                    )
                    """,
                    (
                        order_id,
                        product_id,
                        quantity,
                        price,
                        line_total
                    )
                )

                # ------------------------------------------------
                # DEDUCT STOCK
                # ------------------------------------------------

                new_stock = current_stock - quantity

                cursor.execute(
                    """
                    UPDATE products
                    SET stock = %s
                    WHERE id = %s
                    """,
                    (
                        new_stock,
                        product_id
                    )
                )

                # ------------------------------------------------
                # LOW STOCK DETECTION
                # ------------------------------------------------

                if (
                    current_stock > threshold
                    and new_stock <= threshold
                ):

                    low_stock_products.append(
                        {
                            "productId": product_id,
                            "productName": product["name"],
                            "oldStock": current_stock,
                            "newStock": new_stock,
                            "lowStockThreshold": threshold
                        }
                    )

            # =================================================
            # UPDATE ORDER TOTAL
            # =================================================

            cursor.execute(
                """
                UPDATE orders
                SET
                    total_amount = %s,
                    status_id = %s
                WHERE order_id = %s
                """,
                (
                    total_amount,
                    confirmed_status_id,
                    order_id
                )
            )

        # ====================================================
        # COMMIT
        # ====================================================

        connection.commit()

        logger.info(
            json.dumps({
                "action": "order_confirmed",
                "order_id": order_id,
                "customer_id": customer_id,
                "total_amount": total_amount
            })
        )

        # ====================================================
        # ORDER CONFIRMED EVENT
        # ====================================================

        publish_event(
            "OrderConfirmed",
            {
                "orderId": order_id,
                "customerId": customer_id,
                "totalAmount": total_amount,
                "status": "CONFIRMED"
            }
        )

        # ====================================================
        # LOW STOCK EVENTS
        # ====================================================

        for product in low_stock_products:

            publish_event(
                "Low Stock Alert",
                {
                    "orderId": order_id,
                    "productId": product["productId"],
                    "productName": product["productName"],
                    "oldStock": product["oldStock"],
                    "newStock": product["newStock"],
                    "lowStockThreshold": product["lowStockThreshold"]
                }
            )

        # ====================================================
        # RESPONSE
        # ====================================================

        return response(
            201,
            {
                "message": "Order confirmed successfully",
                "orderId": order_id,
                "customerId": customer_id,
                "totalAmount": total_amount,
                "status": "CONFIRMED",
                "items": items
            }
        )

    except ValueError as error:

        if connection:
            connection.rollback()

        logger.warning(
            json.dumps({
                "action": "order_failed",
                "reason": str(error)
            })
        )

        return response(
            409,
            {
                "message": str(error)
            }
        )

    except Exception as error:

        if connection:
            connection.rollback()

        logger.error(
            json.dumps({
                "action": "order_processing_failed",
                "error": str(error)
            })
        )

        return response(
            500,
            {
                "message": "Order processing failed",
                "error": str(error)
            }
        )

    finally:

        if connection:
            connection.close()


# ============================================================
# GET /orders/{id}
# ============================================================

def get_order_by_id(event):

    connection = None

    try:

        path_parameters = event.get("pathParameters") or {}

        order_id = path_parameters.get("id")

        if order_id is None:

            return response(
                400,
                {
                    "message": "Order id is required"
                }
            )

        try:

            order_id = int(order_id)

        except (TypeError, ValueError):

            return response(
                400,
                {
                    "message": "Order id must be a number"
                }
            )

        if order_id <= 0:

            return response(
                400,
                {
                    "message": "Order id must be greater than zero"
                }
            )

        connection = get_db_connection()

        with connection.cursor() as cursor:

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
                INNER JOIN order_status os
                    ON o.status_id = os.status_id
                WHERE o.order_id = %s
                """,
                (order_id,)
            )

            order = cursor.fetchone()

            if not order:

                return response(
                    404,
                    {
                        "message": "Order not found"
                    }
                )

            # ------------------------------------------------
            # GET ITEMS
            # ------------------------------------------------

            cursor.execute(
                """
                SELECT
                    oi.order_item_id,
                    oi.product_id,
                    p.name AS product_name,
                    oi.quantity,
                    oi.unit_price,
                    oi.line_total
                FROM order_items oi
                INNER JOIN products p
                    ON oi.product_id = p.id
                WHERE oi.order_id = %s
                ORDER BY oi.order_item_id
                """,
                (order_id,)
            )

            items = cursor.fetchall()

        order["items"] = items

        return response(
            200,
            order
        )

    except Exception as error:

        logger.error(
            json.dumps({
                "action": "get_order_failed",
                "error": str(error)
            })
        )

        return response(
            500,
            {
                "message": "Failed to retrieve order",
                "error": str(error)
            }
        )

    finally:

        if connection:
            connection.close()


# ============================================================
# GET /orders?customerId=X
# ============================================================

def get_orders_by_customer(event):

    connection = None

    try:

        query_parameters = (
            event.get("queryStringParameters") or {}
        )

        customer_id = query_parameters.get("customerId")

        if (
            customer_id is None
            or str(customer_id).strip() == ""
        ):

            return response(
                400,
                {
                    "message":
                    "customerId query parameter is required"
                }
            )

        connection = get_db_connection()

        with connection.cursor() as cursor:

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
                INNER JOIN order_status os
                    ON o.status_id = os.status_id
                WHERE o.customer_id = %s
                ORDER BY o.created_at DESC
                """,
                (customer_id,)
            )

            orders = cursor.fetchall()

        return response(
            200,
            {
                "customerId": customer_id,
                "orders": orders,
                "count": len(orders)
            }
        )

    except Exception as error:

        logger.error(
            json.dumps({
                "action": "get_customer_orders_failed",
                "error": str(error)
            })
        )

        return response(
            500,
            {
                "message": "Failed to retrieve customer orders",
                "error": str(error)
            }
        )

    finally:

        if connection:
            connection.close()


# ============================================================
# MAIN HANDLER
# ============================================================

def lambda_handler(event, context):

    try:

        http_method = (
            event.get("httpMethod", "")
            .upper()
        )

        resource = event.get("resource", "")

        path = event.get("path", "")

        logger.info(
            json.dumps({
                "action": "request_received",
                "http_method": http_method,
                "resource": resource,
                "path": path
            })
        )

        # ----------------------------------------------------
        # POST /orders
        # ----------------------------------------------------

        if (
            http_method == "POST"
            and resource == "/orders"
        ):

            return create_order(event)

        # ----------------------------------------------------
        # GET /orders/{id}
        # ----------------------------------------------------

        if (
            http_method == "GET"
            and resource == "/orders/{id}"
        ):

            return get_order_by_id(event)

        # ----------------------------------------------------
        # GET /orders?customerId=X
        # ----------------------------------------------------

        if (
            http_method == "GET"
            and resource == "/orders"
        ):

            return get_orders_by_customer(event)

        # ----------------------------------------------------
        # UNKNOWN ROUTE
        # ----------------------------------------------------

        return response(
            404,
            {
                "message": "Order API route not found"
            }
        )

    except Exception as error:

        logger.error(
            json.dumps({
                "action": "request_failed",
                "error": str(error)
            })
        )

        return response(
            500,
            {
                "message": "Internal server error"
            }
        )
