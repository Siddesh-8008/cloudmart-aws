import json
import os

import boto3
import pymysql


# ============================================================
# AWS CLIENTS
# ============================================================

ssm = boto3.client("ssm")
events = boto3.client("events")

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

    port = 3306

    connection = pymysql.connect(
        host=host,
        user=username,
        password=password,
        database=database,
        port=port,
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=10
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
        "body": json.dumps(body, default=str)
    }


# ============================================================
# LAMBDA HANDLER
# ============================================================

def lambda_handler(event, context):

    print(json.dumps({
        "level": "INFO",
        "message": "Product Lambda invoked",
        "environment": os.environ.get("ENVIRONMENT"),
        "request_id": context.aws_request_id,
        "http_method": event.get("httpMethod"),
        "path": event.get("path")
    }))

    method = event.get("httpMethod")

    path_parameters = event.get("pathParameters") or {}

    product_id = path_parameters.get("id")


    try:

        # ====================================================
        # CREATE PRODUCT
        # POST /products
        # ====================================================

        if method == "POST":

            body = json.loads(
                event.get("body") or "{}"
            )

            name = body.get("name")
            description = body.get("description")
            price = body.get("price")
            stock = body.get("stock", 0)

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
                        "message": "name and price are required"
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

            except (TypeError, ValueError):

                return response(
                    400,
                    {
                        "message": (
                            "price, stock and "
                            "lowStockThreshold must be numeric"
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
                        "message": "price cannot be negative"
                    }
                )


            if stock < 0:

                return response(
                    400,
                    {
                        "message": "stock cannot be negative"
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

            try:

                with connection.cursor() as cursor:

                    sql = """
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
                    """

                    cursor.execute(
                        sql,
                        (
                            name,
                            description,
                            price,
                            stock,
                            low_stock_threshold
                        )
                    )

                    product_id = cursor.lastrowid

                connection.commit()

            finally:

                connection.close()


            print(json.dumps({
                "level": "INFO",
                "message": "Product created",
                "product_id": product_id
            }))


            return response(
                201,
                {
                    "message": "Product created",
                    "productId": product_id
                }
            )


        # ====================================================
        # GET ALL PRODUCTS
        # GET /products
        # ====================================================

        if method == "GET" and not product_id:

            connection = get_database_connection()

            try:

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

            finally:

                connection.close()


            return response(
                200,
                {
                    "products": products
                }
            )


        # ====================================================
        # GET PRODUCT BY ID
        # GET /products/{id}
        # ====================================================

        if method == "GET" and product_id:

            connection = get_database_connection()

            try:

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

            finally:

                connection.close()


            if not product:

                return response(
                    404,
                    {
                        "message": "Product not found"
                    }
                )


            return response(
                200,
                product
            )


        # ====================================================
        # UPDATE PRODUCT
        # PUT /products/{id}
        # ====================================================

        if method == "PUT" and product_id:

            body = json.loads(
                event.get("body") or "{}"
            )


            # --------------------------------------------
            # VALIDATE NUMERIC VALUES BEFORE DB CONNECTION
            # --------------------------------------------

            if "price" in body:

                try:

                    body["price"] = float(
                        body["price"]
                    )

                except (TypeError, ValueError):

                    return response(
                        400,
                        {
                            "message": "price must be numeric"
                        }
                    )


                if body["price"] < 0:

                    return response(
                        400,
                        {
                            "message": "price cannot be negative"
                        }
                    )


            if "stock" in body:

                try:

                    body["stock"] = int(
                        body["stock"]
                    )

                except (TypeError, ValueError):

                    return response(
                        400,
                        {
                            "message": "stock must be numeric"
                        }
                    )


                if body["stock"] < 0:

                    return response(
                        400,
                        {
                            "message": "stock cannot be negative"
                        }
                    )


            if "lowStockThreshold" in body:

                try:

                    body["lowStockThreshold"] = int(
                        body["lowStockThreshold"]
                    )

                except (TypeError, ValueError):

                    return response(
                        400,
                        {
                            "message": (
                                "lowStockThreshold "
                                "must be numeric"
                            )
                        }
                    )


                if body["lowStockThreshold"] < 0:

                    return response(
                        400,
                        {
                            "message": (
                                "lowStockThreshold "
                                "cannot be negative"
                            )
                        }
                    )


            connection = get_database_connection()

            try:

                with connection.cursor() as cursor:

                    # --------------------------------------------
                    # GET CURRENT PRODUCT INFORMATION
                    # --------------------------------------------

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

                    existing_product = cursor.fetchone()


                    if not existing_product:

                        return response(
                            404,
                            {
                                "message": "Product not found"
                            }
                        )


                    old_stock = existing_product["stock"]

                    product_name = existing_product["name"]

                    old_threshold = existing_product[
                        "low_stock_threshold"
                    ]


                    # --------------------------------------------
                    # BUILD UPDATE FIELDS
                    # --------------------------------------------

                    fields = []
                    values = []


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

                        fields.append(
                            "name = %s"
                        )

                        values.append(
                            body["name"]
                        )

                        product_name = body["name"]


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
                            body["lowStockThreshold"]
                        )


                    if not fields:

                        return response(
                            400,
                            {
                                "message": "No fields to update"
                            }
                        )


                    # --------------------------------------------
                    # DETERMINE NEW STOCK AND THRESHOLD
                    # --------------------------------------------

                    new_stock = body.get(
                        "stock",
                        old_stock
                    )

                    new_threshold = body.get(
                        "lowStockThreshold",
                        old_threshold
                    )


                    # --------------------------------------------
                    # UPDATE PRODUCT
                    # --------------------------------------------

                    values.append(product_id)

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


            finally:

                connection.close()


            # ====================================================
            # LOW STOCK EVENT
            # ====================================================

            # Trigger only when stock moves from ABOVE the
            # threshold to AT or BELOW the threshold.

            if (
                "stock" in body
                and old_stock > new_threshold
                and new_stock <= new_threshold
            ):

                try:

                    event_detail = {
                        "productId": product_id,
                        "productName": product_name,
                        "stock": new_stock,
                        "lowStockThreshold": new_threshold
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


                    print(json.dumps({
                        "level": "INFO",
                        "message": (
                            "Low stock event published"
                        ),
                        "product_id": product_id,
                        "stock": new_stock,
                        "threshold": new_threshold,
                        "event_id": (
                            event_response["Entries"][0]
                            .get("EventId")
                        )
                    }))


                except Exception as event_error:

                    print(json.dumps({
                        "level": "ERROR",
                        "message": (
                            "Failed to publish "
                            "low stock event"
                        ),
                        "product_id": product_id,
                        "error": str(event_error)
                    }))


            return response(
                200,
                {
                    "message": "Product updated",
                    "productId": product_id
                }
            )


        # ====================================================
        # DELETE PRODUCT
        # DELETE /products/{id}
        # ====================================================

        if method == "DELETE" and product_id:

            connection = get_database_connection()

            try:

                with connection.cursor() as cursor:

                    cursor.execute(
                        """
                        DELETE FROM products
                        WHERE id = %s
                        """,
                        (product_id,)
                    )


                    if cursor.rowcount == 0:

                        return response(
                            404,
                            {
                                "message": "Product not found"
                            }
                        )


                connection.commit()

            finally:

                connection.close()


            return response(
                200,
                {
                    "message": "Product deleted",
                    "productId": product_id
                }
            )


        # ====================================================
        # UNSUPPORTED REQUEST
        # ====================================================

        return response(
            405,
            {
                "message": "Method not supported"
            }
        )


    except Exception as error:

        print(json.dumps({
            "level": "ERROR",
            "message": "Product Lambda failed",
            "error": str(error),
            "request_id": context.aws_request_id
        }))


        return response(
            500,
            {
                "message": "Internal server error",
                "requestId": context.aws_request_id
            }
        )
