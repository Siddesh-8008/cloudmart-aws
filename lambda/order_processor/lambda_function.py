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
# SSM PARAMETER HELPER
# ============================================================

def get_parameter(name, with_decryption=False):
    result = ssm.get_parameter(
        Name=name,
        WithDecryption=with_decryption
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

    username = get_parameter(
        DB_USERNAME_PARAMETER,
        with_decryption=True
    )

    password = get_parameter(
        DB_PASSWORD_PARAMETER,
        with_decryption=True
    )

    return pymysql.connect(
        host=host,
        port=port,
        user=username,
        password=password,
        database=database,
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,
        connect_timeout=10
    )


# ============================================================
# API GATEWAY AUTHORIZER CONTEXT
# ============================================================

def get_authorizer_context(event):

    request_context = event.get(
        "requestContext",
        {}
    )

    authorizer = request_context.get(
        "authorizer",
        {}
    )

    # REST API Lambda authorizer
    if isinstance(authorizer, dict):
        return authorizer

    return {}


# ============================================================
# AUTHENTICATED CUSTOMER ID
# ============================================================

def get_authenticated_customer_id(event):

    context = get_authorizer_context(event)

    customer_id = context.get(
        "customerId"
    )

    if customer_id is None:
        return None

    return str(customer_id)


# ============================================================
# AUTHENTICATED ROLE
# ============================================================

def get_authenticated_role(event):

    context = get_authorizer_context(event)

    role = context.get(
        "role"
    )

    if role is None:
        return None

    return str(role).lower()


# ============================================================
# EVENTBRIDGE PUBLISH
# ============================================================

def publish_event(detail_type, detail):

    try:

        result = events.put_events(
            Entries=[
                {
                    "EventBusName": EVENT_BUS_NAME,
                    "Source": "cloudmart.order",
                    "DetailType": detail_type,
                    "Detail": json.dumps(
                        detail,
                        default=str
                    )
                }
            ]
        )

        logger.info(
            "Published EventBridge event: %s",
            result
        )

        return result

    except Exception as exc:

        logger.exception(
            "Failed to publish EventBridge event: %s",
            exc
        )

        # Do not fail the database transaction
        # because EventBridge publishing failed.
        return None


# ============================================================
# REQUEST BODY
# ============================================================

def get_request_body(event):

    body = event.get("body")

    if body is None:
        return {}

    if isinstance(body, dict):
        return body

    try:

        return json.loads(body)

    except json.JSONDecodeError:

        raise ValueError(
            "Invalid JSON request body"
        )


# ============================================================
# VALIDATE ORDER ITEMS
# ============================================================

def validate_items(items):

    if not isinstance(items, list):

        raise ValueError(
            "items must be an array"
        )

    if len(items) == 0:

        raise ValueError(
            "At least one item is required"
        )

    for item in items:

        if not isinstance(item, dict):

            raise ValueError(
                "Each item must be an object"
            )

        if "productId" not in item:

            raise ValueError(
                "productId is required for every item"
            )

        if "quantity" not in item:

            raise ValueError(
                "quantity is required for every item"
            )

        try:

            product_id = int(
                item["productId"]
            )

            quantity = int(
                item["quantity"]
            )

        except (ValueError, TypeError):

            raise ValueError(
                "productId and quantity must be integers"
            )

        if product_id <= 0:

            raise ValueError(
                "productId must be greater than 0"
            )

        if quantity <= 0:

            raise ValueError(
                "quantity must be greater than 0"
            )


# ============================================================
# CREATE ORDER
# POST /orders
# ============================================================

def create_order(event):

    connection = None
    order_id = None

    try:

        # ----------------------------------------------------
        # AUTHENTICATION
        # ----------------------------------------------------

        role = get_authenticated_role(event)

        authenticated_customer_id = (
            get_authenticated_customer_id(event)
        )

        if role not in (
            "admin",
            "customer"
        ):

            return response(
                403,
                {
                    "message": "Unauthorized role"
                }
            )

        if (
            role == "customer"
            and not authenticated_customer_id
        ):

            return response(
                403,
                {
                    "message":
                        "Customer identity not found "
                        "in authorization context"
                }
            )

        # ----------------------------------------------------
        # REQUEST BODY
        # ----------------------------------------------------

        body = get_request_body(event)

        if "customerId" not in body:

            return response(
                400,
                {
                    "message":
                        "customerId is required"
                }
            )

        requested_customer_id = str(
            body["customerId"]
        ).strip()

        if not requested_customer_id:

            return response(
                400,
                {
                    "message":
                        "customerId cannot be empty"
                }
            )

        # ----------------------------------------------------
        # CUSTOMER OWNERSHIP CHECK
        # ----------------------------------------------------

        if role == "customer":

            # Customer can only place order
            # for the customer associated with token.

            if (
                requested_customer_id
                != authenticated_customer_id
            ):

                logger.warning(
                    "Customer ownership violation. "
                    "Token customer=%s, requested customer=%s",
                    authenticated_customer_id,
                    requested_customer_id
                )

                return response(
                    403,
                    {
                        "message":
                            "You can only place orders "
                            "for your own customerId",
                        "authenticatedCustomerId":
                            authenticated_customer_id,
                        "requestedCustomerId":
                            requested_customer_id
                    }
                )

            customer_id = authenticated_customer_id

        else:

            # Admin can create order for any customer.
            customer_id = requested_customer_id

        # ----------------------------------------------------
        # ITEMS
        # ----------------------------------------------------

        items = body.get("items")

        validate_items(items)

        # ----------------------------------------------------
        # DATABASE
        # ----------------------------------------------------

        connection = get_db_connection()

        with connection.cursor() as cursor:

            # ------------------------------------------------
            # VERIFY CUSTOMER
            # ------------------------------------------------

            cursor.execute(
                """
                SELECT customer_id, status
                FROM customers
                WHERE customer_id = %s
                """,
                (customer_id,)
            )

            customer = cursor.fetchone()

            if not customer:

                return response(
                    404,
                    {
                        "message":
                            "Customer not found",
                        "customerId":
                            customer_id
                    }
                )

            if customer["status"] != "ACTIVE":

                return response(
                    409,
                    {
                        "message":
                            "Customer is not active",
                        "customerId":
                            customer_id
                    }
                )

            # ------------------------------------------------
            # GET PENDING STATUS
            # ------------------------------------------------

            cursor.execute(
                """
                SELECT status_id
                FROM order_status
                WHERE status_name = 'PENDING'
                LIMIT 1
                """
            )

            pending_status = cursor.fetchone()

            if not pending_status:

                raise ValueError(
                    "PENDING order status does not exist"
                )

            pending_status_id = (
                pending_status["status_id"]
            )

            # ------------------------------------------------
            # CREATE ORDER
            # ------------------------------------------------

            cursor.execute(
                """
                INSERT INTO orders (
                    customer_id,
                    total_amount,
                    status_id,
                    failure_reason
                )
                VALUES (%s, %s, %s, NULL)
                """,
                (
                    customer_id,
                    0,
                    pending_status_id
                )
            )

            order_id = cursor.lastrowid

            logger.info(
                "Created PENDING order %s for customer %s",
                order_id,
                customer_id
            )

            # ------------------------------------------------
            # SAVEPOINT
            # ------------------------------------------------

            cursor.execute(
                "SAVEPOINT order_processing"
            )

            total_amount = 0

            low_stock_products = []

            # ------------------------------------------------
            # PROCESS ITEMS
            # ------------------------------------------------

            for item in items:

                product_id = int(
                    item["productId"]
                )

                quantity = int(
                    item["quantity"]
                )

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
                        low_stock_threshold,
                        is_active
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

                if not product["is_active"]:

                    raise ValueError(
                        f"Product {product_id} is inactive"
                    )

                current_stock = int(
                    product["stock"]
                )

                if current_stock < quantity:

                    raise ValueError(
                        f"Insufficient stock for product "
                        f"{product_id}. Available: "
                        f"{current_stock}, Requested: "
                        f"{quantity}"
                    )

                price = float(
                    product["price"]
                )

                item_total = (
                    price * quantity
                )

                total_amount += item_total

                # ------------------------------------------------
                # INSERT ORDER ITEM
                #
                # Database column is line_total.
                # ------------------------------------------------

                cursor.execute(
                    """
                    INSERT INTO order_items (
                        order_id,
                        product_id,
                        quantity,
                        unit_price,
                        line_total
                    )
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        order_id,
                        product_id,
                        quantity,
                        price,
                        item_total
                    )
                )

                # ------------------------------------------------
                # DEDUCT STOCK
                # ------------------------------------------------

                new_stock = (
                    current_stock - quantity
                )

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
                # LOW STOCK CHECK
                # ------------------------------------------------

                threshold = int(
                    product["low_stock_threshold"]
                )

                if new_stock <= threshold:

                    low_stock_products.append(
                        {
                            "productId":
                                product_id,
                            "productName":
                                product["name"],
                            "stock":
                                new_stock,
                            "lowStockThreshold":
                                threshold
                        }
                    )

            # ------------------------------------------------
            # GET CONFIRMED STATUS
            # ------------------------------------------------

            cursor.execute(
                """
                SELECT status_id
                FROM order_status
                WHERE status_name = 'CONFIRMED'
                LIMIT 1
                """
            )

            confirmed_status = (
                cursor.fetchone()
            )

            if not confirmed_status:

                raise ValueError(
                    "CONFIRMED order status does not exist"
                )

            confirmed_status_id = (
                confirmed_status["status_id"]
            )

            # ------------------------------------------------
            # CONFIRM ORDER
            # ------------------------------------------------

            cursor.execute(
                """
                UPDATE orders
                SET
                    total_amount = %s,
                    status_id = %s,
                    failure_reason = NULL
                WHERE order_id = %s
                """,
                (
                    total_amount,
                    confirmed_status_id,
                    order_id
                )
            )

            connection.commit()

            logger.info(
                "Order %s confirmed successfully",
                order_id
            )

            # ------------------------------------------------
            # ORDER CONFIRMED EVENT
            # ------------------------------------------------

            publish_event(
                "OrderConfirmed",
                {
                    "orderId":
                        order_id,
                    "customerId":
                        customer_id,
                    "totalAmount":
                        total_amount,
                    "status":
                        "CONFIRMED",
                    "items":
                        items
                }
            )

            # ------------------------------------------------
            # LOW STOCK EVENTS
            # ------------------------------------------------

            for product in low_stock_products:

                publish_event(
                    "Low Stock Alert",
                    {
                        "productId":
                            product["productId"],
                        "productName":
                            product["productName"],
                        "stock":
                            product["stock"],
                        "lowStockThreshold":
                            product[
                                "lowStockThreshold"
                            ]
                    }
                )

            # ------------------------------------------------
            # RESPONSE
            # ------------------------------------------------

            return response(
                201,
                {
                    "message":
                        "Order placed successfully",
                    "orderId":
                        order_id,
                    "customerId":
                        customer_id,
                    "totalAmount":
                        total_amount,
                    "status":
                        "CONFIRMED",
                    "items":
                        items
                }
            )

    # ========================================================
    # BUSINESS FAILURE
    # ========================================================

    except ValueError as exc:

        logger.warning(
            "Order processing failed: %s",
            exc
        )

        if connection and order_id:

            try:

                with connection.cursor() as cursor:

                    cursor.execute(
                        """
                        ROLLBACK TO SAVEPOINT
                        order_processing
                        """
                    )

                    cursor.execute(
                        """
                        SELECT status_id
                        FROM order_status
                        WHERE status_name = 'FAILED'
                        LIMIT 1
                        """
                    )

                    failed_status = (
                        cursor.fetchone()
                    )

                    if failed_status:

                        cursor.execute(
                            """
                            UPDATE orders
                            SET
                                status_id = %s,
                                failure_reason = %s
                            WHERE order_id = %s
                            """,
                            (
                                failed_status[
                                    "status_id"
                                ],
                                str(exc),
                                order_id
                            )
                        )

                    connection.commit()

                publish_event(
                    "OrderFailed",
                    {
                        "orderId":
                            order_id,
                        "reason":
                            str(exc)
                    }
                )

            except Exception:

                logger.exception(
                    "Failed to update order as FAILED"
                )

        return response(
            409,
            {
                "message":
                    str(exc),
                "orderId":
                    order_id
            }
        )

    # ========================================================
    # UNEXPECTED ERROR
    # ========================================================

    except Exception as exc:

        logger.exception(
            "Unexpected error while creating order"
        )

        if connection:

            try:
                connection.rollback()
            except Exception:
                pass

        return response(
            500,
            {
                "message":
                    "Internal server error"
            }
        )

    finally:

        if connection:

            try:
                connection.close()
            except Exception:
                pass


# ============================================================
# GET ORDER BY ID
# GET /orders/{id}
# ============================================================

def get_order_by_id(event):

    connection = None

    try:

        # ----------------------------------------------------
        # AUTHENTICATION
        # ----------------------------------------------------

        role = get_authenticated_role(event)

        authenticated_customer_id = (
            get_authenticated_customer_id(event)
        )

        if role not in (
            "admin",
            "customer"
        ):

            return response(
                403,
                {
                    "message":
                        "Unauthorized role"
                }
            )

        if (
            role == "customer"
            and not authenticated_customer_id
        ):

            return response(
                403,
                {
                    "message":
                        "Customer identity not found"
                }
            )

        # ----------------------------------------------------
        # ORDER ID
        # ----------------------------------------------------

        path_parameters = (
            event.get("pathParameters")
            or {}
        )

        order_id_value = (
            path_parameters.get("id")
        )

        if not order_id_value:

            return response(
                400,
                {
                    "message":
                        "Order id is required"
                }
            )

        try:

            order_id = int(
                order_id_value
            )

        except (ValueError, TypeError):

            return response(
                400,
                {
                    "message":
                        "Order id must be an integer"
                }
            )

        # ----------------------------------------------------
        # DATABASE
        # ----------------------------------------------------

        connection = get_db_connection()

        with connection.cursor() as cursor:

            # ------------------------------------------------
            # GET ORDER
            # ------------------------------------------------

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
                WHERE o.order_id = %s
                """,
                (order_id,)
            )

            order = cursor.fetchone()

            if not order:

                return response(
                    404,
                    {
                        "message":
                            "Order not found"
                    }
                )

            # ------------------------------------------------
            # CUSTOMER OWNERSHIP CHECK
            # ------------------------------------------------

            if role == "customer":

                if (
                    str(order["customer_id"])
                    != str(authenticated_customer_id)
                ):

                    logger.warning(
                        "Customer %s attempted to access "
                        "order %s belonging to customer %s",
                        authenticated_customer_id,
                        order_id,
                        order["customer_id"]
                    )

                    return response(
                        403,
                        {
                            "message":
                                "You are not authorized "
                                "to access this order"
                        }
                    )

            # ------------------------------------------------
            # GET ORDER ITEMS
            #
            # Database column is line_total.
            # ------------------------------------------------

            cursor.execute(
                """
                SELECT
                    oi.product_id,
                    p.name AS product_name,
                    oi.quantity,
                    oi.unit_price,
                    oi.line_total
                FROM order_items oi
                JOIN products p
                    ON oi.product_id = p.id
                WHERE oi.order_id = %s
                ORDER BY oi.product_id
                """,
                (order_id,)
            )

            items = cursor.fetchall()

            order["items"] = items

            return response(
                200,
                order
            )

    except Exception:

        logger.exception(
            "Failed to get order"
        )

        return response(
            500,
            {
                "message":
                    "Internal server error"
            }
        )

    finally:

        if connection:

            try:
                connection.close()
            except Exception:
                pass


# ============================================================
# GET ORDERS
# GET /orders
# GET /orders?customerId=CUST001
# ============================================================

def get_orders_by_customer(event):

    connection = None

    try:

        # ----------------------------------------------------
        # AUTHENTICATION
        # ----------------------------------------------------

        role = get_authenticated_role(event)

        authenticated_customer_id = (
            get_authenticated_customer_id(event)
        )

        if role not in (
            "admin",
            "customer"
        ):

            return response(
                403,
                {
                    "message":
                        "Unauthorized role"
                }
            )

        # ----------------------------------------------------
        # QUERY PARAMETERS
        # ----------------------------------------------------

        query_parameters = (
            event.get(
                "queryStringParameters"
            )
            or {}
        )

        requested_customer_id = (
            query_parameters.get(
                "customerId"
            )
        )

        if requested_customer_id:

            requested_customer_id = str(
                requested_customer_id
            ).strip()

        # ----------------------------------------------------
        # CUSTOMER
        # ----------------------------------------------------
        #
        # Customer does NOT need to provide customerId.
        # The customerId comes from the authorizer token.
        #
        # GET /orders
        # Authorization: Bearer CUST001_TOKEN
        #
        # -> Returns all CUST001 orders.
        #
        # GET /orders?customerId=CUST001
        # Authorization: Bearer CUST001_TOKEN
        #
        # -> Still returns CUST001 orders.
        #
        # GET /orders?customerId=CUST002
        # Authorization: Bearer CUST001_TOKEN
        #
        # -> 403 Forbidden.
        # ----------------------------------------------------

        if role == "customer":

            if not authenticated_customer_id:

                return response(
                    403,
                    {
                        "message":
                            "Customer identity not found"
                    }
                )

            # If customerId was supplied, it must match
            # the customer associated with the token.

            if (
                requested_customer_id
                and requested_customer_id
                != authenticated_customer_id
            ):

                logger.warning(
                    "Customer %s attempted to query "
                    "orders for customer %s",
                    authenticated_customer_id,
                    requested_customer_id
                )

                return response(
                    403,
                    {
                        "message":
                            "You can only access "
                            "your own orders",
                        "authenticatedCustomerId":
                            authenticated_customer_id,
                        "requestedCustomerId":
                            requested_customer_id
                    }
                )

            # Use customerId from authorizer token.
            customer_id = (
                authenticated_customer_id
            )

        # ----------------------------------------------------
        # ADMIN
        # ----------------------------------------------------
        #
        # Admin can:
        #
        # GET /orders
        # -> ALL orders
        #
        # GET /orders?customerId=CUST001
        # -> Only CUST001 orders.
        # ----------------------------------------------------

        else:

            customer_id = (
                requested_customer_id
            )

        # ----------------------------------------------------
        # DATABASE
        # ----------------------------------------------------

        connection = get_db_connection()

        with connection.cursor() as cursor:

            # ------------------------------------------------
            # ADMIN WITHOUT customerId
            #
            # Return ALL orders.
            # ------------------------------------------------

            if role == "admin" and not customer_id:

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
                    """
                )

            # ------------------------------------------------
            # CUSTOMER
            #
            # OR
            #
            # ADMIN WITH customerId
            #
            # Return orders for that customer.
            # ------------------------------------------------

            else:

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
                    WHERE o.customer_id = %s
                    ORDER BY o.created_at DESC
                    """,
                    (customer_id,)
                )

            orders = cursor.fetchall()

            # ------------------------------------------------
            # GET ITEMS FOR EACH ORDER
            # ------------------------------------------------

            for order in orders:

                cursor.execute(
                    """
                    SELECT
                        oi.product_id,
                        p.name AS product_name,
                        oi.quantity,
                        oi.unit_price,
                        oi.line_total
                    FROM order_items oi
                    JOIN products p
                        ON oi.product_id = p.id
                    WHERE oi.order_id = %s
                    ORDER BY oi.product_id
                    """,
                    (order["order_id"],)
                )

                order["items"] = (
                    cursor.fetchall()
                )

            # ------------------------------------------------
            # RESPONSE
            # ------------------------------------------------

            # Admin requested ALL orders.
            if role == "admin" and not customer_id:

                return response(
                    200,
                    {
                        "orders":
                            orders
                    }
                )

            # Customer or admin requested a
            # particular customer's orders.
            return response(
                200,
                {
                    "customerId":
                        customer_id,
                    "orders":
                        orders
                }
            )

    except Exception:

        logger.exception(
            "Failed to get orders"
        )

        return response(
            500,
            {
                "message":
                    "Internal server error"
            }
        )

    finally:

        if connection:

            try:
                connection.close()
            except Exception:
                pass


# ============================================================
# CANCEL ORDER
# PATCH /orders/{id}
# ============================================================

def cancel_order(event):

    connection = None

    try:

        # ----------------------------------------------------
        # AUTHENTICATION
        # ----------------------------------------------------

        role = get_authenticated_role(event)

        authenticated_customer_id = (
            get_authenticated_customer_id(event)
        )

        if role not in (
            "admin",
            "customer"
        ):

            return response(
                403,
                {
                    "message":
                        "Unauthorized role"
                }
            )

        if (
            role == "customer"
            and not authenticated_customer_id
        ):

            return response(
                403,
                {
                    "message":
                        "Customer identity not found"
                }
            )

        # ----------------------------------------------------
        # ORDER ID
        # ----------------------------------------------------

        path_parameters = (
            event.get("pathParameters")
            or {}
        )

        order_id_value = (
            path_parameters.get("id")
        )

        if not order_id_value:

            return response(
                400,
                {
                    "message":
                        "Order id is required"
                }
            )

        try:

            order_id = int(
                order_id_value
            )

        except (ValueError, TypeError):

            return response(
                400,
                {
                    "message":
                        "Order id must be an integer"
                }
            )

        # ----------------------------------------------------
        # REQUEST BODY
        # ----------------------------------------------------

        body = get_request_body(event)

        requested_status = body.get(
            "status"
        )

        if requested_status is None:

            return response(
                400,
                {
                    "message":
                        "status is required"
                }
            )

        if (
            str(requested_status).upper()
            != "CANCELLED"
        ):

            return response(
                400,
                {
                    "message":
                        "Only status CANCELLED is "
                        "supported for this operation"
                }
            )

        # ----------------------------------------------------
        # DATABASE
        # ----------------------------------------------------

        connection = get_db_connection()

        with connection.cursor() as cursor:

            # ------------------------------------------------
            # GET STATUS IDs
            # ------------------------------------------------

            cursor.execute(
                """
                SELECT
                    status_id,
                    status_name
                FROM order_status
                WHERE status_name IN (
                    'CONFIRMED',
                    'CANCELLED'
                )
                """
            )

            status_rows = (
                cursor.fetchall()
            )

            status_map = {
                row["status_name"]:
                    row["status_id"]
                for row in status_rows
            }

            if "CONFIRMED" not in status_map:

                raise ValueError(
                    "CONFIRMED order status does not exist"
                )

            if "CANCELLED" not in status_map:

                raise ValueError(
                    "CANCELLED order status does not exist. "
                    "Add CANCELLED to order_status table first."
                )

            confirmed_status_id = (
                status_map["CONFIRMED"]
            )

            cancelled_status_id = (
                status_map["CANCELLED"]
            )

            # ------------------------------------------------
            # LOCK ORDER
            # ------------------------------------------------

            cursor.execute(
                """
                SELECT
                    o.order_id,
                    o.customer_id,
                    o.total_amount,
                    o.status_id,
                    os.status_name AS status
                FROM orders o
                JOIN order_status os
                    ON o.status_id = os.status_id
                WHERE o.order_id = %s
                FOR UPDATE
                """,
                (order_id,)
            )

            order = cursor.fetchone()

            if not order:

                return response(
                    404,
                    {
                        "message":
                            "Order not found"
                    }
                )

            # ------------------------------------------------
            # CUSTOMER OWNERSHIP CHECK
            # ------------------------------------------------

            if role == "customer":

                if (
                    str(order["customer_id"])
                    != str(authenticated_customer_id)
                ):

                    logger.warning(
                        "Customer %s attempted to cancel "
                        "order %s belonging to customer %s",
                        authenticated_customer_id,
                        order_id,
                        order["customer_id"]
                    )

                    return response(
                        403,
                        {
                            "message":
                                "You are not authorized "
                                "to cancel this order"
                        }
                    )

            # ------------------------------------------------
            # STATUS CHECK
            # ------------------------------------------------

            if (
                order["status_id"]
                != confirmed_status_id
            ):

                return response(
                    409,
                    {
                        "message":
                            "Only CONFIRMED orders "
                            "can be cancelled",
                        "orderId":
                            order_id,
                        "currentStatus":
                            order["status"]
                    }
                )

            # ------------------------------------------------
            # LOCK ORDER ITEMS
            # ------------------------------------------------

            cursor.execute(
                """
                SELECT
                    oi.product_id,
                    oi.quantity
                FROM order_items oi
                WHERE oi.order_id = %s
                FOR UPDATE
                """,
                (order_id,)
            )

            order_items = (
                cursor.fetchall()
            )

            if not order_items:

                raise ValueError(
                    "Order has no items"
                )

            # ------------------------------------------------
            # RESTORE PRODUCT STOCK
            # ------------------------------------------------

            for item in order_items:

                product_id = (
                    item["product_id"]
                )

                quantity = int(
                    item["quantity"]
                )

                cursor.execute(
                    """
                    UPDATE products
                    SET stock = stock + %s
                    WHERE id = %s
                    """,
                    (
                        quantity,
                        product_id
                    )
                )

                if cursor.rowcount == 0:

                    raise ValueError(
                        f"Product {product_id} "
                        f"not found while restoring stock"
                    )

            # ------------------------------------------------
            # UPDATE ORDER STATUS
            # ------------------------------------------------

            cancelled_by = (
                "admin"
                if role == "admin"
                else "customer"
            )

            cursor.execute(
                """
                UPDATE orders
                SET
                    status_id = %s,
                    failure_reason = %s
                WHERE order_id = %s
                """,
                (
                    cancelled_status_id,
                    f"Order cancelled by {cancelled_by}",
                    order_id
                )
            )

            connection.commit()

            logger.info(
                "Order %s cancelled successfully by %s",
                order_id,
                cancelled_by
            )

            # ------------------------------------------------
            # ORDER CANCELLED EVENT
            # ------------------------------------------------

            publish_event(
                "OrderCancelled",
                {
                    "orderId":
                        order_id,
                    "customerId":
                        order["customer_id"],
                    "totalAmount":
                        float(
                            order["total_amount"]
                        ),
                    "status":
                        "CANCELLED",
                    "cancelledBy":
                        cancelled_by
                }
            )

            # ------------------------------------------------
            # RESPONSE
            # ------------------------------------------------

            return response(
                200,
                {
                    "message":
                        "Order cancelled successfully",
                    "orderId":
                        order_id,
                    "customerId":
                        order["customer_id"],
                    "status":
                        "CANCELLED"
                }
            )

    # ========================================================
    # BUSINESS FAILURE
    # ========================================================

    except ValueError as exc:

        logger.warning(
            "Order cancellation failed: %s",
            exc
        )

        if connection:

            try:
                connection.rollback()
            except Exception:
                pass

        return response(
            409,
            {
                "message":
                    str(exc),
                "orderId":
                    order_id
            }
        )

    # ========================================================
    # UNEXPECTED ERROR
    # ========================================================

    except Exception:

        logger.exception(
            "Failed to cancel order"
        )

        if connection:

            try:
                connection.rollback()
            except Exception:
                pass

        return response(
            500,
            {
                "message":
                    "Internal server error"
            }
        )

    finally:

        if connection:

            try:
                connection.close()
            except Exception:
                pass


# ============================================================
# LAMBDA HANDLER
# ============================================================

def lambda_handler(event, context):

    logger.info(
        "Received event: %s",
        json.dumps(
            event,
            default=str
        )
    )

    http_method = (
        event.get(
            "httpMethod",
            ""
        ).upper()
    )

    resource = event.get(
        "resource",
        ""
    )

    # ========================================================
    # POST /orders
    # ========================================================

    if (
        http_method == "POST"
        and resource == "/orders"
    ):

        return create_order(event)

    # ========================================================
    # GET /orders/{id}
    # ========================================================

    if (
        http_method == "GET"
        and resource == "/orders/{id}"
    ):

        return get_order_by_id(event)

    # ========================================================
    # GET /orders
    # ========================================================

    if (
        http_method == "GET"
        and resource == "/orders"
    ):

        return get_orders_by_customer(event)

    # ========================================================
    # PATCH /orders/{id}
    # CANCEL ORDER
    # ========================================================

    if (
        http_method == "PATCH"
        and resource == "/orders/{id}"
    ):

        return cancel_order(event)

    # ========================================================
    # UNSUPPORTED ROUTE
    # ========================================================

    return response(
        404,
        {
            "message":
                "Route not found"
        }
    )