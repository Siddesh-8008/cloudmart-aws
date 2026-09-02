
import json
import os

import boto3
import pymysql


ssm = boto3.client("ssm")
events = boto3.client("events")
lambda_client = boto3.client("lambda")


def response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json"
        },
        "body": json.dumps(body, default=str)
    }


def get_parameter(name, secure=False):
    return ssm.get_parameter(
        Name=name,
        WithDecryption=secure
    )["Parameter"]["Value"]


def get_connection():
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
        autocommit=False
    )


def publish_event(detail_type, detail):
    result = events.put_events(
        Entries=[
            {
                "EventBusName": os.environ["EVENT_BUS_NAME"],
                "Source": "cloudmart.orders",
                "DetailType": detail_type,
                "Detail": json.dumps(
                    detail,
                    default=str
                )
            }
        ]
    )

    if result.get("FailedEntryCount", 0):
        print(
            "EventBridge publish failure:",
            result
        )

    else:
        print(
            json.dumps(
                {
                    "level": "INFO",
                    "message": "EventBridge event published",
                    "detailType": detail_type,
                    "result": result
                },
                default=str
            )
        )


def parse_body(event):
    body = event.get("body") or "{}"

    if isinstance(body, str):
        return json.loads(body)

    return body


def create_order(event, context):

    body = parse_body(event)

    customer_id = body.get("customerId")
    items = body.get("items")

    if not customer_id or not isinstance(items, list) or not items:
        return response(
            400,
            {
                "message": (
                    "customerId and a non-empty "
                    "items array are required"
                )
            }
        )

    connection = None

    try:

        connection = get_connection()

        total = 0.0

        normalized_items = []

        seen_products = set()

        with connection.cursor() as cursor:

            # ---------------------------------------------------------
            # Validate every item and get current product information
            # ---------------------------------------------------------
            for item in items:

                try:
                    product_id = int(
                        item["productId"]
                    )

                    quantity = int(
                        item["quantity"]
                    )

                except (
                    KeyError,
                    TypeError,
                    ValueError
                ):

                    connection.rollback()

                    return response(
                        400,
                        {
                            "message": (
                                "Each item requires numeric "
                                "productId and quantity"
                            )
                        }
                    )

                if quantity <= 0:

                    connection.rollback()

                    return response(
                        400,
                        {
                            "message": (
                                "quantity must be "
                                "greater than zero"
                            )
                        }
                    )

                if product_id in seen_products:

                    connection.rollback()

                    return response(
                        400,
                        {
                            "message": (
                                "Duplicate productId is "
                                "not allowed in the same order"
                            )
                        }
                    )

                seen_products.add(product_id)

                cursor.execute(
                    """
                    SELECT
                        id,
                        name,
                        price,
                        stock
                    FROM products
                    WHERE id = %s
                    """,
                    (product_id,)
                )

                product = cursor.fetchone()

                if not product:

                    connection.rollback()

                    return response(
                        404,
                        {
                            "message": (
                                f"Product {product_id} "
                                "not found"
                            )
                        }
                    )

                unit_price = float(
                    product["price"]
                )

                line_total = round(
                    unit_price * quantity,
                    2
                )

                total += line_total

                normalized_items.append(
                    {
                        "productId": product_id,
                        "productName": product["name"],
                        "quantity": quantity,
                        "unitPrice": unit_price,
                        "lineTotal": line_total
                    }
                )

            # ---------------------------------------------------------
            # Create order as PENDING
            # ---------------------------------------------------------
            cursor.execute(
                """
                INSERT INTO orders
                    (
                        customer_id,
                        total_amount,
                        status_id
                    )
                SELECT
                    %s,
                    %s,
                    status_id
                FROM order_status
                WHERE status_name = 'PENDING'
                """,
                (
                    str(customer_id),
                    round(total, 2)
                )
            )

            order_id = cursor.lastrowid

            if not order_id:
                raise RuntimeError(
                    "Could not create order"
                )

            # ---------------------------------------------------------
            # Insert order items
            # ---------------------------------------------------------
            for item in normalized_items:

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
                        item["productId"],
                        item["quantity"],
                        item["unitPrice"],
                        item["lineTotal"]
                    )
                )

        # Commit the PENDING order.
        connection.commit()

        # -------------------------------------------------------------
        # EventBridge OrderPlaced event
        # -------------------------------------------------------------
        order_detail = {
            "orderId": order_id,
            "customerId": str(customer_id),
            "totalAmount": round(total, 2),
            "items": normalized_items
        }

        publish_event(
            "OrderPlaced",
            order_detail
        )

        # -------------------------------------------------------------
        # Invoke Order Processor asynchronously
        # -------------------------------------------------------------
        invoke_result = lambda_client.invoke(
            FunctionName=os.environ[
                "ORDER_PROCESSOR_FUNCTION"
            ],
            InvocationType="Event",
            Payload=json.dumps(
                {
                    "orderId": order_id
                }
            ).encode("utf-8")
        )

        print(
            json.dumps(
                {
                    "level": "INFO",
                    "message": (
                        "Order Processor invoked "
                        "asynchronously"
                    ),
                    "orderId": order_id,
                    "invokeStatusCode": (
                        invoke_result.get(
                            "StatusCode"
                        )
                    )
                },
                default=str
            )
        )

        # -------------------------------------------------------------
        # Return immediately.
        #
        # Processor will later change PENDING -> CONFIRMED/FAILED.
        # -------------------------------------------------------------
        return response(
            201,
            {
                "message": "Order created",
                "orderId": order_id,
                "status": "PENDING",
                "totalAmount": round(
                    total,
                    2
                )
            }
        )

    except Exception as exc:

        if connection:
            connection.rollback()

        print(
            json.dumps(
                {
                    "level": "ERROR",
                    "message": "Create order failed",
                    "error": str(exc),
                    "requestId": context.aws_request_id
                },
                default=str
            )
        )

        return response(
            500,
            {
                "message": "Internal server error",
                "requestId": context.aws_request_id
            }
        )

    finally:

        if connection:
            connection.close()


def get_orders(event, context):

    customer_id = (
        event.get("queryStringParameters") or {}
    ).get("customerId")

    connection = None

    try:

        connection = get_connection()

        with connection.cursor() as cursor:

            if customer_id:

                cursor.execute(
                    """
                    SELECT
                        o.order_id,
                        o.customer_id,
                        o.total_amount,
                        s.status_name AS status,
                        o.failure_reason,
                        o.created_at,
                        o.updated_at
                    FROM orders o
                    JOIN order_status s
                        ON s.status_id = o.status_id
                    WHERE o.customer_id = %s
                    ORDER BY o.created_at DESC
                    """,
                    (str(customer_id),)
                )

            else:

                cursor.execute(
                    """
                    SELECT
                        o.order_id,
                        o.customer_id,
                        o.total_amount,
                        s.status_name AS status,
                        o.failure_reason,
                        o.created_at,
                        o.updated_at
                    FROM orders o
                    JOIN order_status s
                        ON s.status_id = o.status_id
                    ORDER BY o.created_at DESC
                    """
                )

            orders = cursor.fetchall()

            for order in orders:

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
                    JOIN products p
                        ON p.id = oi.product_id
                    WHERE oi.order_id = %s
                    ORDER BY oi.order_item_id
                    """,
                    (order["order_id"],)
                )

                order["items"] = cursor.fetchall()

        return response(
            200,
            {
                "orders": orders
            }
        )

    except Exception as exc:

        print(
            json.dumps(
                {
                    "level": "ERROR",
                    "message": "Get orders failed",
                    "error": str(exc),
                    "requestId": context.aws_request_id
                },
                default=str
            )
        )

        return response(
            500,
            {
                "message": "Internal server error",
                "requestId": context.aws_request_id
            }
        )

    finally:

        if connection:
            connection.close()


def get_order_by_id(event, context):

    path_parameters = (
        event.get("pathParameters") or {}
    )

    order_id = path_parameters.get("id")

    if not order_id:

        return response(
            400,
            {
                "message": "Order id is required"
            }
        )

    try:
        order_id = int(order_id)

    except ValueError:

        return response(
            400,
            {
                "message": "Order id must be numeric"
            }
        )

    connection = None

    try:

        connection = get_connection()

        with connection.cursor() as cursor:

            cursor.execute(
                """
                SELECT
                    o.order_id,
                    o.customer_id,
                    o.total_amount,
                    s.status_name AS status,
                    o.failure_reason,
                    o.created_at,
                    o.updated_at
                FROM orders o
                JOIN order_status s
                    ON s.status_id = o.status_id
                WHERE o.order_id = %s
                """,
                (order_id,)
            )

            order = cursor.fetchone()

            if not order:

                return response(
                    404,
                    {
                        "message": (
                            f"Order {order_id} "
                            "not found"
                        )
                    }
                )

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
                JOIN products p
                    ON p.id = oi.product_id
                WHERE oi.order_id = %s
                ORDER BY oi.order_item_id
                """,
                (order_id,)
            )

            order["items"] = cursor.fetchall()

        return response(
            200,
            order
        )

    except Exception as exc:

        print(
            json.dumps(
                {
                    "level": "ERROR",
                    "message": (
                        "Get order by id failed"
                    ),
                    "orderId": order_id,
                    "error": str(exc),
                    "requestId": context.aws_request_id
                },
                default=str
            )
        )

        return response(
            500,
            {
                "message": "Internal server error",
                "requestId": context.aws_request_id
            }
        )

    finally:

        if connection:
            connection.close()


def lambda_handler(event, context):

    print(
        json.dumps(
            {
                "level": "INFO",
                "message": "Order Lambda invoked",
                "event": event
            },
            default=str
        )
    )

    http_method = (
        event.get("httpMethod")
        or event.get("requestContext", {})
        .get("http", {})
        .get("method")
        or ""
    ).upper()

    path_parameters = (
        event.get("pathParameters") or {}
    )

    # POST /orders
    if http_method == "POST":
        return create_order(
            event,
            context
        )

    # GET /orders/{id}
    if http_method == "GET" and path_parameters.get("id"):
        return get_order_by_id(
            event,
            context
        )

    # GET /orders
    if http_method == "GET":
        return get_orders(
            event,
            context
        )

    return response(
        405,
        {
            "message": "Method not allowed"
        }
    )

