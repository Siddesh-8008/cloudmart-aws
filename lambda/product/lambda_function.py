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


ENVIRONMENT = os.environ.get(
    "ENVIRONMENT",
    "dev"
)

EVENT_BUS_NAME = os.environ.get(
    "EVENT_BUS_NAME",
    "cloudmart-dev-event-bus"
)


# ============================================================
# DATABASE CONFIGURATION
# ============================================================

def get_parameter(name, secure=False):

    response = ssm.get_parameter(
        Name=name,
        WithDecryption=secure
    )

    return response["Parameter"]["Value"]


def get_database_connection():

    host = get_parameter(
        os.environ["DB_HOST_PARAMETER"]
    )

    database = get_parameter(
        os.environ["DB_NAME_PARAMETER"]
    )

    username = get_parameter(
        os.environ["DB_USERNAME_PARAMETER"],
        secure=True
    )

    password = get_parameter(
        os.environ["DB_PASSWORD_PARAMETER"],
        secure=True
    )

    # Use Parameter Store port if configured.
    # Otherwise use default MySQL port 3306.
    db_port_parameter = os.environ.get(
        "DB_PORT_PARAMETER"
    )

    if db_port_parameter:

        port = int(
            get_parameter(db_port_parameter)
        )

    else:

        port = 3306


    connection = pymysql.connect(
        host=host,
        user=username,
        password=password,
        database=database,
        port=port,
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=10,
        autocommit=False
    )

    return connection


# ============================================================
# JSON RESPONSE
# ============================================================

def response(status_code, body):

    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json"
        },
        "body": json.dumps(
            body,
            default=str
        )
    }


# ============================================================
# REQUEST BODY PARSER
# ============================================================

def parse_body(event):

    body = event.get("body")

    if not body:
        return {}

    if isinstance(body, str):

        try:

            parsed_body = json.loads(body)

        except json.JSONDecodeError:

            raise ValueError(
                "Request body must contain valid JSON"
            )

        if not isinstance(parsed_body, dict):

            raise ValueError(
                "Request body must be a JSON object"
            )

        return parsed_body

    if isinstance(body, dict):

        return body

    raise ValueError(
        "Invalid request body"
    )


# ============================================================
# EVENTBRIDGE - LOW STOCK EVENT
# ============================================================

def publish_low_stock_event(
    product_id,
    product_name,
    stock,
    low_stock_threshold
):

    event_detail = {
        "productId": int(product_id),
        "productName": product_name,
        "stock": int(stock),
        "lowStockThreshold": int(
            low_stock_threshold
        ),
        "environment": ENVIRONMENT
    }


    event_response = events.put_events(
        Entries=[
            {
                "EventBusName": EVENT_BUS_NAME,
                "Source": "cloudmart.product",
                "DetailType": "Low Stock Alert",
                "Detail": json.dumps(
                    event_detail
                )
            }
        ]
    )


    # Check EventBridge response
    if event_response.get(
        "FailedEntryCount",
        0
    ) > 0:

        logger.error(
            json.dumps({
                "level": "ERROR",
                "message": "Failed to publish low stock event",
                "product_id": product_id,
                "response": event_response
            })
        )

        raise Exception(
            "Failed to publish low stock event"
        )


    logger.info(
        json.dumps({
            "level": "INFO",
            "message": "Low stock event published",
            "product_id": product_id,
            "product_name": product_name,
            "stock": stock,
            "threshold": low_stock_threshold,
            "event_bus": EVENT_BUS_NAME
        })
    )


# ============================================================
# LAMBDA HANDLER
# ============================================================

def lambda_handler(event, context):

    logger.info(
        json.dumps({
            "level": "INFO",
            "message": "Product Lambda invoked",
            "environment": ENVIRONMENT,
            "request_id": context.aws_request_id,
            "http_method": event.get("httpMethod"),
            "path": event.get("path")
        })
    )


    connection = None


    try:

        # ====================================================
        # REQUEST INFORMATION
        # ====================================================

        method = (
            event.get(
                "httpMethod",
                ""
            )
            .upper()
        )


        path_parameters = (
            event.get("pathParameters")
            or {}
        )


        product_id = path_parameters.get(
            "id"
        )


        # ====================================================
        # REQUEST BODY
        # ====================================================

        body = parse_body(event)


        # ====================================================
        # POST /products
        # CREATE PRODUCT
        # ====================================================

        if method == "POST":

            name = body.get("name")

            description = body.get(
                "description"
            )

            price = body.get("price")

            stock = body.get(
                "stock",
                0
            )

            low_stock_threshold = body.get(
                "lowStockThreshold",
                5
            )


            # --------------------------------------------
            # REQUIRED FIELD VALIDATION
            # --------------------------------------------

            if not name or price is None:

                return response(
                    400,
                    {
                        "message": (
                            "name and price are required"
                        )
                    }
                )


            # --------------------------------------------
            # NUMERIC VALIDATION
            # --------------------------------------------

            try:

                price = float(price)

                stock = int(stock)

                low_stock_threshold = int(
                    low_stock_threshold
                )

            except (
                TypeError,
                ValueError
            ):

                return response(
                    400,
                    {
                        "message": (
                            "price, stock and "
                            "lowStockThreshold "
                            "must be numeric"
                        )
                    }
                )


            # --------------------------------------------
            # NEGATIVE VALUE VALIDATION
            # --------------------------------------------

            if price < 0:

                return response(
                    400,
                    {
                        "message": (
                            "price cannot be negative"
                        )
                    }
                )


            if stock < 0:

                return response(
                    400,
                    {
                        "message": (
                            "stock cannot be negative"
                        )
                    }
                )


            if low_stock_threshold < 0:

                return response(
                    400,
                    {
                        "message": (
                            "lowStockThreshold "
                            "cannot be negative"
                        )
                    }
                )


            # --------------------------------------------
            # DATABASE INSERT
            # --------------------------------------------

            connection = get_database_connection()


            with connection.cursor() as cursor:

                cursor.execute(
                    """
                    INSERT INTO products
                    (
                        name,
                        description,
                        price,
                        stock,
                        low_stock_threshold
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
                        name,
                        description,
                        price,
                        stock,
                        low_stock_threshold
                    )
                )


                new_product_id = cursor.lastrowid


            connection.commit()


            logger.info(
                json.dumps({
                    "level": "INFO",
                    "message": "Product created",
                    "product_id": new_product_id
                })
            )


            return response(
                201,
                {
                    "message": (
                        "Product created successfully"
                    ),
                    "productId": new_product_id
                }
            )


        # ====================================================
        # GET /products
        # GET ALL PRODUCTS
        # ====================================================

        if method == "GET" and not product_id:

            connection = get_database_connection()


            with connection.cursor() as cursor:

                cursor.execute(
                    """
                    SELECT
                        id,
                        name,
                        description,
                        price,
                        stock,
                        low_stock_threshold,
                        created_at,
                        updated_at
                    FROM products
                    ORDER BY id
                    """
                )


                products = cursor.fetchall()


            return response(
                200,
                {
                    "products": products
                }
            )


        # ====================================================
        # GET /products/{id}
        # GET PRODUCT BY ID
        # ====================================================

        if method == "GET" and product_id:

            connection = get_database_connection()


            with connection.cursor() as cursor:

                cursor.execute(
                    """
                    SELECT
                        id,
                        name,
                        description,
                        price,
                        stock,
                        low_stock_threshold,
                        created_at,
                        updated_at
                    FROM products
                    WHERE id = %s
                    """,
                    (product_id,)
                )


                product = cursor.fetchone()


            if not product:

                return response(
                    404,
                    {
                        "message": (
                            "Product not found"
                        )
                    }
                )


            return response(
                200,
                product
            )


        # ====================================================
        # PUT /products/{id}
        # UPDATE PRODUCT
        # ====================================================

        if method == "PUT" and product_id:

            connection = get_database_connection()


            with connection.cursor() as cursor:

                # ----------------------------------------
                # GET CURRENT PRODUCT
                # ----------------------------------------

                cursor.execute(
                    """
                    SELECT
                        id,
                        name,
                        stock,
                        low_stock_threshold
                    FROM products
                    WHERE id = %s
                    """,
                    (product_id,)
                )


                existing_product = (
                    cursor.fetchone()
                )


                if not existing_product:

                    return response(
                        404,
                        {
                            "message": (
                                "Product not found"
                            )
                        }
                    )


                old_stock = (
                    existing_product["stock"]
                )


                product_name = (
                    existing_product["name"]
                )


                old_threshold = (
                    existing_product[
                        "low_stock_threshold"
                    ]
                )


                # ----------------------------------------
                # VALIDATE NAME
                # ----------------------------------------

                if "name" in body:

                    if not body["name"]:

                        return response(
                            400,
                            {
                                "message": (
                                    "name cannot be empty"
                                )
                            }
                        )


                # ----------------------------------------
                # VALIDATE PRICE
                # ----------------------------------------

                if "price" in body:

                    try:

                        body["price"] = float(
                            body["price"]
                        )

                    except (
                        TypeError,
                        ValueError
                    ):

                        return response(
                            400,
                            {
                                "message": (
                                    "price must be numeric"
                                )
                            }
                        )


                    if body["price"] < 0:

                        return response(
                            400,
                            {
                                "message": (
                                    "price cannot be negative"
                                )
                            }
                        )


                # ----------------------------------------
                # VALIDATE STOCK
                # ----------------------------------------

                if "stock" in body:

                    try:

                        body["stock"] = int(
                            body["stock"]
                        )

                    except (
                        TypeError,
                        ValueError
                    ):

                        return response(
                            400,
                            {
                                "message": (
                                    "stock must be numeric"
                                )
                            }
                        )


                    if body["stock"] < 0:

                        return response(
                            400,
                            {
                                "message": (
                                    "stock cannot be negative"
                                )
                            }
                        )


                # ----------------------------------------
                # VALIDATE LOW STOCK THRESHOLD
                # ----------------------------------------

                if "lowStockThreshold" in body:

                    try:

                        body[
                            "lowStockThreshold"
                        ] = int(
                            body[
                                "lowStockThreshold"
                            ]
                        )

                    except (
                        TypeError,
                        ValueError
                    ):

                        return response(
                            400,
                            {
                                "message": (
                                    "lowStockThreshold "
                                    "must be numeric"
                                )
                            }
                        )


                    if (
                        body[
                            "lowStockThreshold"
                        ] < 0
                    ):

                        return response(
                            400,
                            {
                                "message": (
                                    "lowStockThreshold "
                                    "cannot be negative"
                                )
                            }
                        )


                # ----------------------------------------
                # BUILD UPDATE QUERY
                # ----------------------------------------

                fields = []

                values = []


                if "name" in body:

                    fields.append(
                        "name = %s"
                    )

                    values.append(
                        body["name"]
                    )

                    product_name = (
                        body["name"]
                    )


                if "description" in body:

                    fields.append(
                        "description = %s"
                    )

                    values.append(
                        body["description"]
                    )


                if "price" in body:

                    fields.append(
                        "price = %s"
                    )

                    values.append(
                        body["price"]
                    )


                if "stock" in body:

                    fields.append(
                        "stock = %s"
                    )

                    values.append(
                        body["stock"]
                    )


                if "lowStockThreshold" in body:

                    fields.append(
                        "low_stock_threshold = %s"
                    )

                    values.append(
                        body[
                            "lowStockThreshold"
                        ]
                    )


                # ----------------------------------------
                # NOTHING TO UPDATE
                # ----------------------------------------

                if not fields:

                    return response(
                        400,
                        {
                            "message": (
                                "No fields to update"
                            )
                        }
                    )


                # ----------------------------------------
                # DETERMINE NEW STOCK/THRESHOLD
                # ----------------------------------------

                new_stock = body.get(
                    "stock",
                    old_stock
                )


                new_threshold = body.get(
                    "lowStockThreshold",
                    old_threshold
                )


                # ----------------------------------------
                # UPDATE DATABASE
                # ----------------------------------------

                values.append(
                    product_id
                )


                sql = f"""
                    UPDATE products
                    SET {", ".join(fields)}
                    WHERE id = %s
                """


                cursor.execute(
                    sql,
                    values
                )


            connection.commit()


            # =================================================
            # LOW STOCK EVENT
            # =================================================

            # Trigger only when stock moves from ABOVE
            # threshold to AT or BELOW threshold.

            if (
                "stock" in body
                and old_stock > new_threshold
                and new_stock <= new_threshold
            ):

                try:

                    publish_low_stock_event(
                        product_id=product_id,
                        product_name=product_name,
                        stock=new_stock,
                        low_stock_threshold=new_threshold
                    )

                except Exception as event_error:

                    logger.error(
                        json.dumps({
                            "level": "ERROR",
                            "message": (
                                "Failed to publish "
                                "low stock event"
                            ),
                            "product_id": product_id,
                            "error": str(
                                event_error
                            )
                        })
                    )


            return response(
                200,
                {
                    "message": (
                        "Product updated successfully"
                    ),
                    "productId": product_id
                }
            )


        # ====================================================
        # DELETE /products/{id}
        # DELETE PRODUCT
        # ====================================================

        if method == "DELETE" and product_id:

            connection = get_database_connection()


            with connection.cursor() as cursor:

                cursor.execute(
                    """
                    DELETE FROM products
                    WHERE id = %s
                    """,
                    (product_id,)
                )


                affected_rows = cursor.rowcount


            connection.commit()


            if affected_rows == 0:

                return response(
                    404,
                    {
                        "message": (
                            "Product not found"
                        )
                    }
                )


            logger.info(
                json.dumps({
                    "level": "INFO",
                    "message": "Product deleted",
                    "product_id": product_id
                })
            )


            return response(
                200,
                {
                    "message": (
                        "Product deleted successfully"
                    ),
                    "productId": product_id
                }
            )


        # ====================================================
        # UNSUPPORTED REQUEST
        # ====================================================

        return response(
            405,
            {
                "message": (
                    "Method or path not supported"
                )
            }
        )


    # ========================================================
    # INVALID REQUEST
    # ========================================================

    except ValueError as error:

        if connection:

            connection.rollback()


        logger.error(
            json.dumps({
                "level": "ERROR",
                "message": "Invalid request",
                "error": str(error),
                "request_id": context.aws_request_id
            })
        )


        return response(
            400,
            {
                "message": str(error)
            }
        )


    # ========================================================
    # GENERAL ERROR
    # ========================================================

    except Exception as error:

        if connection:

            connection.rollback()


        logger.error(
            json.dumps({
                "level": "ERROR",
                "message": "Product Lambda failed",
                "error": str(error),
                "request_id": context.aws_request_id
            })
        )


        return response(
            500,
            {
                "message": "Internal server error",
                "requestId": context.aws_request_id
            }
        )


    # ========================================================
    # CLOSE DATABASE CONNECTION
    # ========================================================

    finally:

        if connection:

            connection.close()
