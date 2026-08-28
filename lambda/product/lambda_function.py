import json
import os

import boto3
import pymysql


# ============================================================
# AWS CLIENTS
# ============================================================

ssm = boto3.client("ssm")


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

    port_parameter = os.environ.get(
        "DB_PORT_PARAMETER",
        "/cloudmart/dev/db/port"
    )

    port = int(
        get_parameter(port_parameter)
    )

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

            if not name or price is None:

                return response(
                    400,
                    {
                        "message": "name and price are required"
                    }
                )

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

            connection = get_database_connection()

            try:

                with connection.cursor() as cursor:

                    fields = []
                    values = []

                    if "name" in body:
                        fields.append("name = %s")
                        values.append(body["name"])

                    if "description" in body:
                        fields.append("description = %s")
                        values.append(body["description"])

                    if "price" in body:
                        fields.append("price = %s")
                        values.append(body["price"])

                    if "stock" in body:
                        fields.append("stock = %s")
                        values.append(body["stock"])

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