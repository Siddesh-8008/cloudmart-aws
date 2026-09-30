
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
    customer_id=None
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

        response["context"]["customerId"] = (
            customer_id
        )

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
# FIND CUSTOMER BY CUSTOMER ID + TOKEN
# ============================================================

def find_customer_by_credentials(
    customer_id,
    supplied_token
):

    token_hash = hash_token(
        supplied_token
    )

    connection = None

    try:

        connection = get_db_connection()

        with connection.cursor() as cursor:

            cursor.execute(
                """
                SELECT
                    c.customer_id,
                    c.name,
                    c.email,
                    c.status,
                    t.token_hash,
                    t.is_active,
                    t.expires_at
                FROM customer_auth_tokens t
                INNER JOIN customers c
                    ON c.customer_id = t.customer_id
                WHERE t.customer_id = %s
                  AND t.is_active = TRUE
                  AND c.status = 'ACTIVE'
                  AND t.token_hash = %s
                LIMIT 1
                """,
                (
                    customer_id,
                    token_hash,
                )
            )

            customer = cursor.fetchone()

        if not customer:

            return None


        # ====================================================
        # OPTIONAL EXPIRATION CHECK
        # ====================================================

        if customer["expires_at"]:

            from datetime import datetime, timezone

            expires_at = customer[
                "expires_at"
            ]

            now = datetime.now(
                timezone.utc
            ).replace(
                tzinfo=None
            )

            if expires_at <= now:

                return None


        # ====================================================
        # UPDATE LAST USED
        # ====================================================

        with connection.cursor() as cursor:

            cursor.execute(
                """
                UPDATE customer_auth_tokens
                SET last_used_at = CURRENT_TIMESTAMP
                WHERE customer_id = %s
                  AND token_hash = %s
                """,
                (
                    customer_id,
                    token_hash,
                )
            )

        return customer

    finally:

        if connection:

            connection.close()


# ============================================================
# PUBLIC PRODUCTS REQUEST
#
# Public product catalogue supports:
#
# 1. GET /products
# 2. GET /products/{id}
#
# Both can be accessed without a token.
#
# They can ALSO be accessed with:
#
# 3. Customer Bearer token + customerId
# 4. Admin Bearer token
#
# ============================================================

def is_public_products_request(
    event,
    method_arn
):

    # ========================================================
    # REQUEST AUTHORISER EVENT VALUES
    # ========================================================

    http_method = str(
        event.get("httpMethod") or ""
    ).upper()

    resource_path = str(
        event.get("resource") or ""
    )


    # ========================================================
    # FALLBACK TO METHOD ARN
    # ========================================================

    if not http_method or not resource_path:

        parts = method_arn.split("/")

        if len(parts) < 4:

            return False

        http_method = parts[2].upper()

        resource_path = "/" + "/".join(
            parts[3:]
        )


    # ========================================================
    # ONLY GET PRODUCTS IS PUBLIC
    #
    # Allowed:
    #
    # GET /products
    # GET /products/{id}
    #
    # ========================================================

    if http_method != "GET":

        return False


    if resource_path == "/products":

        product_request = True

    elif resource_path == "/products/{id}":

        product_request = True

    else:

        # Some API Gateway authorizer events may provide
        # the actual path instead of the resource template.
        #
        # Example:
        #
        # /products/123
        #
        # Therefore also allow a direct product ID path.

        product_request = (
            resource_path.startswith("/products/")
            and resource_path.count("/") == 2
            and resource_path != "/products/"
        )


    if not product_request:

        return False


    # ========================================================
    # CUSTOMER ID
    #
    # Public access is allowed only when customerId is absent.
    #
    # If customerId is supplied, authentication will continue
    # through the normal customer/admin token validation.
    # ========================================================

    query_parameters = event.get(
        "queryStringParameters"
    ) or {}

    customer_id = query_parameters.get(
        "customerId"
    )

    return not customer_id


# ============================================================
# GET PUBLIC PRODUCT RESOURCES
# ============================================================

def get_public_products_resources(
    method_arn
):

    api_stage_arn = get_api_stage_arn(
        method_arn
    )

    return [

        # GET /products
        api_stage_arn + "/GET/products",

        # GET /products/{id}
        api_stage_arn + "/GET/products/*"

    ]


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
    #
    # REQUEST AUTHORISER RECEIVES HTTP HEADERS
    # ========================================================

    headers = event.get(
        "headers"
    ) or {}

    authorization_token = None

    for header_name, header_value in headers.items():

        if str(
            header_name
        ).lower() == "authorization":

            authorization_token = (
                header_value
            )

            break


    # ========================================================
    # PUBLIC GET PRODUCTS
    #
    # Supported:
    #
    # GET /products
    # GET /products/{id}
    #
    # No token is required.
    # ========================================================

    if not authorization_token:

        if is_public_products_request(
            event,
            method_arn
        ):

            print(
                json.dumps({

                    "event":
                        "public_products_request",

                    "result":
                        "allowed"

                })
            )

            return generate_policy(

                effect="Allow",

                principal_id=
                    "cloudmart-public-products",

                resources=
                    get_public_products_resources(
                        method_arn
                    ),

                role="public"
            )


        # ====================================================
        # EVERYTHING ELSE REQUIRES AUTHENTICATION
        # ====================================================

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

    supplied_token = (
        token_parts[1].strip()
    )


    # ========================================================
    # EMPTY TOKEN
    # ========================================================

    if not supplied_token:

        raise Exception(
            "Unauthorized"
        )


    # ========================================================
    # CUSTOMER ID FROM QUERY STRING
    # ========================================================

    query_parameters = event.get(
        "queryStringParameters"
    ) or {}

    customer_id = query_parameters.get(
        "customerId"
    )

    if customer_id is not None:

        customer_id = str(
            customer_id
        ).strip()


    # ========================================================
    # ADMIN TOKEN
    # ========================================================

    admin_parameter = os.environ.get(
        "ADMIN_AUTH_TOKEN_PARAMETER"
    )

    if admin_parameter:

        try:

            admin_token = get_parameter(
                admin_parameter
            )

            if hmac.compare_digest(
                supplied_token,
                admin_token
            ):

                print(
                    json.dumps({

                        "event":
                            "token_validation",

                        "result":
                            "success",

                        "role":
                            "admin"

                    })
                )

                return generate_policy(

                    effect="Allow",

                    principal_id=
                        "cloudmart-admin",

                    resources=
                        get_admin_resources(
                            method_arn
                        ),

                    role="admin"
                )

        except Exception as error:

            print(
                json.dumps({

                    "event":
                        "admin_validation_error",

                    "error":
                        str(error)

                })
            )


    # ========================================================
    # CUSTOMER ID IS MANDATORY FOR CUSTOMER AUTHENTICATION
    # ========================================================

    if not customer_id:

        print(
            json.dumps({

                "event":
                    "token_validation",

                "result":
                    "customerId_required"

            })
        )

        raise Exception(
            "customerId is required"
        )


    # ========================================================
    # CUSTOMER TOKEN -> RDS
    # ========================================================

    try:

        customer = find_customer_by_credentials(

            customer_id,

            supplied_token

        )

    except Exception as error:

        print(
            json.dumps({

                "level":
                    "ERROR",

                "event":
                    "customer_token_database_error",

                "error":
                    str(error)

            })
        )

        raise Exception(
            "Unauthorized"
        )


    # ========================================================
    # CUSTOMER NOT FOUND
    # ========================================================

    if not customer:

        print(
            json.dumps({

                "event":
                    "token_validation",

                "result":
                    "invalid_customer_credentials"

            })
        )

        raise Exception(
            "Unauthorized"
        )


    # ========================================================
    # CUSTOMER AUTHORIZED
    # ========================================================

    customer_id = customer[
        "customer_id"
    ]

    print(
        json.dumps({

            "event":
                "token_validation",

            "result":
                "success",

            "role":
                "customer",

            "customerId":
                customer_id

        })
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

