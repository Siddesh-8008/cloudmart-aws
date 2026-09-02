import json
import os

import boto3
import pymysql


ssm = boto3.client("ssm")
events = boto3.client("events")


def get_parameter(name, secure=False):
    return ssm.get_parameter(
        Name=name,
        WithDecryption=secure
    )["Parameter"]["Value"]


def get_database_connection():

    db_port_parameter = os.environ.get(
        "DB_PORT_PARAMETER"
    )

    if db_port_parameter:
        db_port = int(
            get_parameter(db_port_parameter)
        )
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
                "EventBusName": os.environ[
                    "EVENT_BUS_NAME"
                ],
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

        raise RuntimeError(
            f"EventBridge failed to publish "
            f"{detail_type}: {result}"
        )

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


def set_failed(order_id, reason):

    connection = None

    try:

        connection = get_database_connection()

        with connection.cursor() as cursor:

            cursor.execute(
                """
                SELECT status_id
                FROM order_status
                WHERE status_name = 'FAILED'
                """
            )

            failed_status = cursor.fetchone()

            if not failed_status:

                raise RuntimeError(
                    "FAILED status does not exist"
                )

            cursor.execute(
                """
                UPDATE orders
                SET
                    status_id = %s,
                    failure_reason = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE order_id = %s
                """,
                (
                    failed_status["status_id"],
                    str(reason)[:1000],
                    order_id
                )
            )

        connection.commit()

    finally:

        if connection:
            connection.close()


def process_order(order_id, context):

    connection = None

    order_detail = None

    low_stock_products = []

    try:

        connection = get_database_connection()

        with connection.cursor() as cursor:

            # =========================================================
            # 1. Get the order and lock it
            # =========================================================
            cursor.execute(
                """
                SELECT
                    o.order_id,
                    o.customer_id,
                    o.total_amount,
                    s.status_name AS status
                FROM orders o
                JOIN order_status s
                    ON s.status_id = o.status_id
                WHERE o.order_id = %s
                FOR UPDATE
                """,
                (order_id,)
            )

            order = cursor.fetchone()

            if not order:

                raise RuntimeError(
                    f"Order {order_id} not found"
                )

            # Prevent duplicate processing.
            if order["status"] != "PENDING":

                connection.rollback()

                print(
                    json.dumps(
                        {
                            "level": "INFO",
                            "message": (
                                "Order already processed"
                            ),
                            "orderId": order_id,
                            "status": order["status"]
                        },
                        default=str
                    )
                )

                return

            # =========================================================
            # 2. Get order items
            # =========================================================
            cursor.execute(
                """
                SELECT
                    order_item_id,
                    product_id,
                    quantity,
                    unit_price,
                    line_total
                FROM order_items
                WHERE order_id = %s
                ORDER BY order_item_id
                """,
                (order_id,)
            )

            items = cursor.fetchall()

            if not items:

                raise RuntimeError(
                    "Order has no items"
                )

            # =========================================================
            # 3. Check ALL products before changing ANY stock
            # =========================================================
            product_details = []

            for item in items:

                cursor.execute(
                    """
                    SELECT
                        id,
                        name,
                        stock,
                        low_stock_threshold
                    FROM products
                    WHERE id = %s
                    FOR UPDATE
                    """,
                    (item["product_id"],)
                )

                product = cursor.fetchone()

                if not product:

                    raise RuntimeError(
                        f"Product {item['product_id']} "
                        "not found"
                    )

                old_stock = int(
                    product["stock"]
                )

                quantity = int(
                    item["quantity"]
                )

                threshold = int(
                    product["low_stock_threshold"]
                )

                print(
                    json.dumps(
                        {
                            "level": "INFO",
                            "message": (
                                "Checking product stock"
                            ),
                            "orderId": order_id,
                            "productId": product["id"],
                            "productName": product["name"],
                            "oldStock": old_stock,
                            "requestedQuantity": quantity,
                            "lowStockThreshold": threshold
                        },
                        default=str
                    )
                )

                # =====================================================
                # Insufficient stock
                # =====================================================
                if old_stock < quantity:

                    raise RuntimeError(
                        f"Insufficient stock for "
                        f"product {product['id']} "
                        f"({product['name']}): "
                        f"requested {quantity}, "
                        f"available {old_stock}"
                    )

                new_stock = (
                    old_stock - quantity
                )

                product_details.append(
                    {
                        "productId": product["id"],
                        "productName": product["name"],
                        "oldStock": old_stock,
                        "quantity": quantity,
                        "newStock": new_stock,
                        "lowStockThreshold": threshold
                    }
                )

            # =========================================================
            # 4. Deduct stock
            # =========================================================
            for product in product_details:

                cursor.execute(
                    """
                    UPDATE products
                    SET
                        stock = stock - %s,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                    """,
                    (
                        product["quantity"],
                        product["productId"]
                    )
                )

                print(
                    json.dumps(
                        {
                            "level": "INFO",
                            "message": "Stock updated",
                            "orderId": order_id,
                            "productId": (
                                product["productId"]
                            ),
                            "oldStock": (
                                product["oldStock"]
                            ),
                            "quantityOrdered": (
                                product["quantity"]
                            ),
                            "newStock": (
                                product["newStock"]
                            )
                        },
                        default=str
                    )
                )

                # =====================================================
                # 5. Detect transition into low-stock state
                #
                # Example:
                #
                # 10 -> 8, threshold 5 = no email
                #  8 -> 5, threshold 5 = email
                #  5 -> 4, threshold 5 = no new email
                # =====================================================
                if (
                    product["oldStock"]
                    > product["lowStockThreshold"]
                    and
                    product["newStock"]
                    <= product["lowStockThreshold"]
                ):

                    low_stock_products.append(
                        {
                            "productId": (
                                product["productId"]
                            ),
                            "productName": (
                                product["productName"]
                            ),
                            "oldStock": (
                                product["oldStock"]
                            ),
                            "currentStock": (
                                product["newStock"]
                            ),
                            "lowStockThreshold": (
                                product[
                                    "lowStockThreshold"
                                ]
                            )
                        }
                    )

            # =========================================================
            # 6. Get CONFIRMED status
            # =========================================================
            cursor.execute(
                """
                SELECT status_id
                FROM order_status
                WHERE status_name = 'CONFIRMED'
                """
            )

            confirmed_status = cursor.fetchone()

            if not confirmed_status:

                raise RuntimeError(
                    "CONFIRMED status does not exist"
                )

            # =========================================================
            # 7. Change order to CONFIRMED
            # =========================================================
            cursor.execute(
                """
                UPDATE orders
                SET
                    status_id = %s,
                    failure_reason = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE order_id = %s
                """,
                (
                    confirmed_status["status_id"],
                    order_id
                )
            )

            order_detail = {
                "orderId": order["order_id"],
                "customerId": str(
                    order["customer_id"]
                ),
                "totalAmount": order[
                    "total_amount"
                ],
                "status": "CONFIRMED",
                "items": [
                    {
                        "productId": item[
                            "product_id"
                        ],
                        "quantity": item[
                            "quantity"
                        ]
                    }
                    for item in items
                ]
            }

        # =============================================================
        # 8. Commit stock + CONFIRMED status
        # =============================================================
        connection.commit()

        print(
            json.dumps(
                {
                    "level": "INFO",
                    "message": (
                        "Order transaction committed"
                    ),
                    "orderId": order_id,
                    "status": "CONFIRMED"
                },
                default=str
            )
        )

        # =============================================================
        # 9. Publish OrderConfirmed
        #
        # Your existing EventBridge rule should send this to SNS,
        # which sends the confirmation email.
        # =============================================================
        publish_event(
            "OrderConfirmed",
            order_detail
        )

        print(
            json.dumps(
                {
                    "level": "INFO",
                    "message": "Order confirmed",
                    "orderId": order_id
                },
                default=str
            )
        )

        # =============================================================
        # 10. Publish Low Stock Alert
        #
        # Your existing EventBridge rule should send this to SNS,
        # which sends the low-stock email.
        # =============================================================
        for product in low_stock_products:

            low_stock_detail = {
                "orderId": order_id,
                "productId": (
                    product["productId"]
                ),
                "productName": (
                    product["productName"]
                ),
                "oldStock": (
                    product["oldStock"]
                ),
                "currentStock": (
                    product["currentStock"]
                ),
                "lowStockThreshold": (
                    product["lowStockThreshold"]
                ),
                "message": (
                    f"Product "
                    f"{product['productName']} "
                    f"(ID {product['productId']}) "
                    f"is low on stock. "
                    f"Current stock: "
                    f"{product['currentStock']}. "
                    f"Threshold: "
                    f"{product['lowStockThreshold']}."
                )
            }

            publish_event(
                "Low Stock Alert",
                low_stock_detail
            )

            print(
                json.dumps(
                    {
                        "level": "INFO",
                        "message": (
                            "Low stock event published"
                        ),
                        "orderId": order_id,
                        "productId": (
                            product["productId"]
                        ),
                        "currentStock": (
                            product["currentStock"]
                        ),
                        "threshold": (
                            product[
                                "lowStockThreshold"
                            ]
                        )
                    },
                    default=str
                )
            )

    except Exception as error:

        # =============================================================
        # Roll back the stock/order transaction.
        # =============================================================
        if connection:
            connection.rollback()

        reason = str(error)

        print(
            json.dumps(
                {
                    "level": "ERROR",
                    "message": (
                        "Order processing failed"
                    ),
                    "orderId": order_id,
                    "error": reason,
                    "requestId": context.aws_request_id
                },
                default=str
            )
        )

        try:

            # =========================================================
            # Mark order FAILED.
            # =========================================================
            set_failed(
                order_id,
                reason
            )

            # =========================================================
            # Publish OrderFailed event.
            # =========================================================
            publish_event(
                "OrderFailed",
                {
                    "orderId": order_id,
                    "status": "FAILED",
                    "reason": reason
                }
            )

        except Exception as failure_record_error:

            print(
                json.dumps(
                    {
                        "level": "ERROR",
                        "message": (
                            "Could not record/"
                            "publish order failure"
                        ),
                        "orderId": order_id,
                        "error": str(
                            failure_record_error
                        )
                    },
                    default=str
                )
            )

    finally:

        if connection:
            connection.close()


def lambda_handler(event, context):

    print(
        json.dumps(
            {
                "level": "INFO",
                "message": (
                    "Order Processor invoked"
                ),
                "event": event
            },
            default=str
        )
    )

    order_id = event.get("orderId")

    if not order_id:

        raise ValueError(
            "orderId is required"
        )

    process_order(
        int(order_id),
        context
    )

    return {
        "status": "completed",
        "orderId": int(order_id)
    }

