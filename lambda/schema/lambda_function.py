import os
import json
import boto3
import pymysql


ssm = boto3.client("ssm")


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

    port = int(
        get_parameter(
            os.environ["DB_PORT_PARAMETER"]
        )
    )

    return pymysql.connect(
        host=host,
        user=username,
        password=password,
        database=database,
        port=port,
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=10
    )


def lambda_handler(event, context):

    print(json.dumps({
        "message": "Schema Lambda invoked",
        "request_id": context.aws_request_id
    }))

    connection = None

    try:

        connection = get_database_connection()

        with connection.cursor() as cursor:

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS products (
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    name VARCHAR(255) NOT NULL,
                    description TEXT,
                    price DECIMAL(10,2) NOT NULL,
                    stock INT NOT NULL DEFAULT 0,
                    low_stock_threshold INT NOT NULL DEFAULT 5,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        ON UPDATE CURRENT_TIMESTAMP
                )
                """
            )

        connection.commit()

        print("Products table created successfully.")

        return {
            "statusCode": 200,
            "body": json.dumps({
                "message": "Products table created successfully"
            })
        }

    except Exception as error:

        print(json.dumps({
            "level": "ERROR",
            "message": "Schema initialization failed",
            "error": str(error),
            "request_id": context.aws_request_id
        }))

        raise

    finally:

        if connection:
            connection.close()