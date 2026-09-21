import json
import os
import hashlib
import hmac
import boto3
import pymysql


# ============================================================
# AWS CLIENTS
# ============================================================

ssm = boto3.client("ssm")


# ============================================================
# ENVIRONMENT
# ============================================================

ENVIRONMENT = os.environ.get(
    "ENVIRONMENT",
    "dev"
)


# ============================================================
# DATABASE SSM PARAMETERS
# ============================================================

DB_HOST_PARAMETER = os.environ[
    "DB_HOST_PARAMETER"
]

DB_PORT_PARAMETER = os.environ.get(
    "DB_PORT_PARAMETER"
)

DB_NAME_PARAMETER = os.environ[
    "DB_NAME_PARAMETER"
]

DB_USERNAME_PARAMETER = os.environ[
    "DB_USERNAME_PARAMETER"
]

DB_PASSWORD_PARAMETER = os.environ[
    "DB_PASSWORD_PARAMETER"
]


# ============================================================
# SSM PARAMETER
#
# All CloudMart SSM parameters used by this Lambda are
# normal String parameters.
#
# Therefore WithDecryption is NOT required.
# ============================================================

def get_parameter(name):

    return ssm.get_parameter(
        Name=name,
        WithDecryption=False
    )["Parameter"]["Value"]


# ============================================================
# DATABASE CONNECTION
# ============================================================

def get_db_connection():

    host = get_parameter(
        DB_HOST_PARAMETER
    )

    if DB_PORT_PARAMETER:

        port = int(
            get_parameter(
                DB_PORT_PARAMETER
            )
        )

    else:

        port = 3306

    database = get_parameter(
        DB_NAME_PARAMETER
    )

    username = get_parameter(
        DB_USERNAME_PARAMETER
    )

    password = get_parameter(
        DB_PASSWORD_PARAMETER
    )

    return pymysql.connect(
        host=host,
        port=port,
        user=username,
        password=password,
        database=database,
        connect_timeout=5,
        read_timeout=5,
        write_timeout=5,
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True
    )


# ============================================================
# HASH TOKEN
# ============================================================

def hash_token(token):

    return hashlib.sha256(
        token.encode("utf-8")
    ).hexdigest()


# ============================================================
# GET API STAGE ARN
# ============================================================

def get_api_stage_arn(method_arn):

    parts = method_arn.split("/")

    if len(parts) < 2:

        return method_arn

    return parts[0] + "/" + parts[1]


# ============================================================
# GENERATE POLICY
# ============================================================

def generate_policy(
    effect,
    principal_id,
    resources,
    role,
    customer_id=None,
    admin_id=None
):

    response = {

        "principalId": principal_id,

        "policyDocument": {

            "Version": "2012-10-17",

            "Statement": [

                {

                    "Action":
                        "execute-api:Invoke",

                    "Effect":
                        effect,

                    "Resource":
                        resources

                }

            ]

        },

        "context": {

            "role": role

        }

    }

    if customer_id:
        response["context"]["customerId"] = customer_id

    if admin_id:
        response["context"]["adminId"] = admin_id

    return response


# ============================================================
# ADMIN RESOURCES
# ============================================================

def get_admin_resources(method_arn):

    api_stage_arn = get_api_stage_arn(
        method_arn
    )

    return [
        api_stage_arn + "/*/*"
    ]


# ============================================================
# CUSTOMER RESOURCES
# ============================================================

def get_customer_resources(method_arn):

    api_stage_arn = get_api_stage_arn(
        method_arn
    )

    return [

        # ====================================================
        # PRODUCTS - READ ONLY
        # ====================================================

        api_stage_arn + "/GET/products",
        api_stage_arn + "/GET/products/*",

        # ====================================================
        # ORDERS
        # ====================================================

        # Create order
        api_stage_arn + "/POST/orders",

        # Get orders
        api_stage_arn + "/GET/orders",

        # Get specific order
        api_stage_arn + "/GET/orders/*",

        # Cancel order
        api_stage_arn + "/PATCH/orders/*"
    ]


# ============================================================
# FIND AUTHENTICATION RECORD BY ID + TOKEN
#
# The client sends:
#   customerId + Bearer token  -> customer
#   adminId    + Bearer token  -> admin
#
# Only the SHA-256 hash is compared with the RDS value.
# The plaintext token is never stored in RDS.
# ============================================================

def find_auth_record(customer_id=None, admin_id=None, supplied_token=""):

    token_hash = hash_token(supplied_token)

    connection = None

    try:
        connection = get_db_connection()

        with connection.cursor() as cursor:

            if admin_id:
                cursor.execute(
                    """
                    SELECT
                        admin_id,
                        customer_id,
                        role,
                        is_active,
                        expires_at,
                        token_hash
                    FROM customer_auth_tokens
                    WHERE admin_id = %s
                      AND role = 'admin'
                      AND is_active = TRUE
                      AND token_hash = %s
                    LIMIT 1
                    """,
                    (admin_id, token_hash)
                )
            else:
                cursor.execute(
                    """
                    SELECT
                        admin_id,
                        customer_id,
                        role,
                        is_active,
                        expires_at,
                        token_hash
                    FROM customer_auth_tokens
                    WHERE customer_id = %s
                      AND role = 'customer'
                      AND is_active = TRUE
                      AND token_hash = %s
                    LIMIT 1
                    """,
                    (customer_id, token_hash)
                )

            record = cursor.fetchone()

        if not record:
            return None

        if record["expires_at"]:
            from datetime import datetime, timezone

            expires_at = record["expires_at"]
            now = datetime.now(timezone.utc).replace(tzinfo=None)

            if expires_at <= now:
                return None

        with connection.cursor() as cursor:
            if admin_id:
                cursor.execute(
                    """
                    UPDATE customer_auth_tokens
                    SET last_used_at = CURRENT_TIMESTAMP
                    WHERE admin_id = %s
                      AND role = 'admin'
                      AND token_hash = %s
                    """,
                    (admin_id, token_hash)
                )
            else:
                cursor.execute(
                    """
                    UPDATE customer_auth_tokens
                    SET last_used_at = CURRENT_TIMESTAMP
                    WHERE customer_id = %s
                      AND role = 'customer'
                      AND token_hash = %s
                    """,
                    (customer_id, token_hash)
                )

        return record

    finally:
        if connection:
            connection.close()


# ============================================================
# AUTHORIZE
# ============================================================

def handler(event, context):

    print(
        json.dumps({

            "level": "INFO",

            "event":
                "authorizer_invoked",

            "request_id":
                context.aws_request_id

        })
    )


    # ========================================================
    # METHOD ARN
    # ========================================================

    method_arn = event.get(
        "methodArn",
        "*"
    )


    # ========================================================
    # AUTHORIZATION HEADER
    # REQUEST AUTHORISER RECEIVES THE HTTP HEADERS
    # ========================================================

    headers = event.get("headers") or {}

    authorization_token = None

    for header_name, header_value in headers.items():

        if str(header_name).lower() == "authorization":

            authorization_token = header_value

            break


    # ========================================================
    # MISSING TOKEN
    # ========================================================

    if not authorization_token:

        print(
            json.dumps({

                "event":
                    "token_validation",

                "result":
                    "missing_authorization_header"

            })
        )

        raise Exception(
            "Unauthorized"
        )


    # ========================================================
    # BEARER FORMAT
    # ========================================================
    #
    # Expected format:
    #
    # Bearer <token>
    #
    # We use split() to separate:
    #
    # [0] = Bearer
    # [1] = actual token
    #
    # Example:
    #
    # "Bearer ABC123"
    #
    # becomes:
    #
    # ["Bearer", "ABC123"]
    #
    # ========================================================

    token_parts = str(
        authorization_token
    ).split()

    if (
        len(token_parts) != 2
        or token_parts[0] != "Bearer"
    ):

        print(
            json.dumps({

                "event":
                    "token_validation",

                "result":
                    "invalid_format"

            })
        )

        raise Exception(
            "Unauthorized"
        )


    # ========================================================
    # EXTRACT ACTUAL TOKEN
    # ========================================================
    #
    # token_parts[0] = "Bearer"
    # token_parts[1] = actual token
    #
    # Example:
    #
    # ["Bearer", "ABC123"]
    #
    # token_parts[1] = "ABC123"
    #
    # ========================================================

    supplied_token = token_parts[1].strip()


    # ========================================================
    # EMPTY TOKEN
    # ========================================================

    if not supplied_token:

        raise Exception(
            "Unauthorized"
        )


    # ========================================================
    # CUSTOMER / ADMIN ID FROM QUERY STRING
    #
    # Both identifiers are mandatory:
    #   customer -> customerId
    #   admin    -> adminId
    #
    # Exactly one must be supplied.
    # ========================================================

    query_parameters = event.get("queryStringParameters") or {}

    customer_id = query_parameters.get("customerId")
    admin_id = query_parameters.get("adminId")

    if customer_id is not None:
        customer_id = str(customer_id).strip()

    if admin_id is not None:
        admin_id = str(admin_id).strip()

    if bool(customer_id) == bool(admin_id):
        print(
            json.dumps({
                "event": "token_validation",
                "result": "exactly_one_identity_required"
            })
        )
        raise Exception("customerId or adminId is required")


    # ========================================================
    # TOKEN -> RDS
    #
    # The supplied token is hashed with SHA-256 and compared
    # with token_hash in customer_auth_tokens.
    # ========================================================

    try:
        auth_record = find_auth_record(
            customer_id=customer_id,
            admin_id=admin_id,
            supplied_token=supplied_token
        )

    except Exception as error:
        print(
            json.dumps({
                "level": "ERROR",
                "event": "token_validation_database_error",
                "error": str(error)
            })
        )
        raise Exception("Unauthorized")


    if not auth_record:
        print(
            json.dumps({
                "event": "token_validation",
                "result": "invalid_credentials"
            })
        )
        raise Exception("Unauthorized")


    # ========================================================
    # ADMIN AUTHORIZATION
    # ========================================================

    if auth_record["role"] == "admin":

        print(
            json.dumps({
                "event": "token_validation",
                "result": "success",
                "role": "admin",
                "adminId": auth_record["admin_id"]
            })
        )

        return generate_policy(
            effect="Allow",
            principal_id=f"admin-{auth_record['admin_id']}",
            resources=get_admin_resources(method_arn),
            role="admin",
            admin_id=auth_record["admin_id"]
        )


    # ========================================================
    # CUSTOMER AUTHORIZATION
    # ========================================================

    print(
        json.dumps({
            "event": "token_validation",
            "result": "success",
            "role": "customer",
            "customerId": auth_record["customer_id"]
        })
    )

    return generate_policy(
        effect="Allow",
        principal_id=f"customer-{auth_record['customer_id']}",
        resources=get_customer_resources(method_arn),
        role="customer",
        customer_id=auth_record["customer_id"]
    )


    # ========================================================
    # CUSTOMER API RESOURCES
    # ========================================================

    customer_resources = (
        get_customer_resources(
            method_arn
        )
    )


    # ========================================================
    # RETURN CUSTOMER POLICY
    # ========================================================

    return generate_policy(

        effect="Allow",

        principal_id=
            f"customer-{customer_id}",

        resources=
            customer_resources,

        role="customer",

        customer_id=
            customer_id

    )
