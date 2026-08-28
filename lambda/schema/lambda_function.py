import json
import os
import urllib.request
import urllib.error

import boto3
import pymysql


ssm = boto3.client("ssm")


# ============================================================
# CLOUDFORMATION CUSTOM RESOURCE RESPONSE
# ============================================================

def send_cfn_response(
    event,
    context,
    status,
    data=None,
    physical_resource_id=None,
    reason=None
):

    response_url = event["ResponseURL"]

    response_body = {
        "Status": status,
        "Reason": reason or (
            f"See CloudWatch logs for details: "
            f"{context.log_stream_name}"
        ),
        "PhysicalResourceId": physical_resource_id
        or context.log_stream_name,
        "StackId": event["StackId"],
        "RequestId": event["RequestId"],
        "LogicalResourceId": event["LogicalResourceId"],
        "Data": data or {}
    }

    json_body = json.dumps(response_body).encode("utf-8")

    request = urllib.request.Request(
        response_url,
        data=json_body,
        headers={
            "content-type": "",
            "content-length": str(len(json_body))
        },
        method="PUT"
    )

    try:
        with urllib.request.urlopen(request) as response:
            print(
                "CloudFormation response status:",
                response.status
            )

    except Exception as error:
        print(
            "Failed to send CloudFormation response:",
            str(error)
        )


# ============================================================
# SSM
# ============================================================

def get_parameter(name, secure=False):

    response = ssm.get_parameter(
        Name=name,
        WithDecryption=secure
    )

    return response["Parameter"]["Value"]


# ============================================================
# DATABASE CONNECTION
# ============================================================

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

    print(
        json.dumps({
            "message": "Connecting to database",
            "host": host,
            "database": database,
            "port": port
        })
    )

    return pymysql.connect(
        host=host,
        user=username,
        password=password,
        database=database,
        port=port,
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=10,
        read_timeout=10,
        write_timeout=10,
        autocommit=False
    )


# ============================================================
# LOAD SCHEMA
# ============================================================

def load_schema():

    schema_path = os.path.join(
        os.path.dirname(__file__),
        "schema.sql"
    )

    with open(
        schema_path,
        "r",
        encoding="utf-8"
    ) as schema_file:

        return schema_file.read()


# ============================================================
# EXECUTE SCHEMA
# ============================================================

def execute_schema():

    connection = get_database_connection()

    try:

        schema = load_schema()

        # Remove SQL comments
        lines = []

        for line in schema.splitlines():

            stripped = line.strip()

            if not stripped:
                continue

            if stripped.startswith("--"):
                continue

            lines.append(line)

        cleaned_schema = "\n".join(lines)

        statements = [
            statement.strip()
            for statement in cleaned_schema.split(";")
            if statement.strip()
        ]

        print(
            f"Found {len(statements)} SQL statement(s)"
        )

        with connection.cursor() as cursor:

            for statement in statements:

                print(
                    "Executing SQL:",
                    statement[:200]
                )

                cursor.execute(statement)

        connection.commit()

        print(
            "Database schema executed successfully."
        )

    except Exception:

        connection.rollback()

        raise

    finally:

        connection.close()


# ============================================================
# LAMBDA HANDLER
# ============================================================

def lambda_handler(event, context):

    print(
        json.dumps({
            "message": "Schema Lambda invoked",
            "request_type": event.get("RequestType"),
            "request_id": context.aws_request_id
        })
    )

    request_type = event.get("RequestType")

    physical_id = (
        "cloudmart-schema-initializer"
    )

    try:

        # ----------------------------------------------------
        # CREATE
        # ----------------------------------------------------

        if request_type == "Create":

            execute_schema()

            send_cfn_response(
                event,
                context,
                "SUCCESS",
                {
                    "Message":
                        "CloudMart database schema created"
                },
                physical_id
            )

            return


        # ----------------------------------------------------
        # UPDATE
        # ----------------------------------------------------

        if request_type == "Update":

            execute_schema()

            send_cfn_response(
                event,
                context,
                "SUCCESS",
                {
                    "Message":
                        "CloudMart database schema updated"
                },
                physical_id
            )

            return


        # ----------------------------------------------------
        # DELETE
        # ----------------------------------------------------

        if request_type == "Delete":

            # We intentionally do not DROP tables.
            #
            # Deleting the CloudFormation stack should not
            # destroy application data.

            send_cfn_response(
                event,
                context,
                "SUCCESS",
                {
                    "Message":
                        "Schema stack deleted without "
                        "dropping application tables"
                },
                physical_id
            )

            return


        raise Exception(
            f"Unsupported RequestType: {request_type}"
        )

    except Exception as error:

        print(
            json.dumps({
                "level": "ERROR",
                "message": "Schema initialization failed",
                "error": str(error),
                "request_id": context.aws_request_id
            })
        )

        send_cfn_response(
            event,
            context,
            "FAILED",
            {},
            physical_id,
            str(error)
        )

        raise