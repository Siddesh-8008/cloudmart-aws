import json
import os
import boto3


# ============================================================
# AWS CLIENT
# ============================================================

ssm = boto3.client("ssm")


# ============================================================
# ENVIRONMENT VARIABLES
# ============================================================

ADMIN_PARAMETER_NAME = os.environ[
    "ADMIN_AUTH_TOKEN_PARAMETER"
]

CUSTOMER_PARAMETER_NAME = os.environ[
    "CUSTOMER_AUTH_TOKEN_PARAMETER"
]

CUSTOMER_ID = os.environ[
    "CUSTOMER_ID"
]


# ============================================================
# READ TOKEN FROM SSM
# ============================================================

def get_parameter_value(parameter_name):

    parameter = ssm.get_parameter(
        Name=parameter_name,
        WithDecryption=True
    )

    return parameter["Parameter"]["Value"]


# ============================================================
# GET API GATEWAY STAGE ARN
# ============================================================

def get_api_stage_arn(method_arn):

    """
    Example method ARN:

    arn:aws:execute-api:ap-south-1:123456789012:abc123/dev/GET/products

    Returns:

    arn:aws:execute-api:ap-south-1:123456789012:abc123/dev
    """

    parts = method_arn.split("/")

    if len(parts) < 2:
        return method_arn

    return parts[0] + "/" + parts[1]


# ============================================================
# GENERATE IAM POLICY
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
                    "Action": "execute-api:Invoke",

                    "Effect": effect,

                    "Resource": resources
                }

            ]
        },

        "context": {

            "role": role
        }
    }


    # --------------------------------------------------------
    # ADD CUSTOMER ID ONLY FOR CUSTOMER
    # --------------------------------------------------------

    if customer_id:

        response["context"]["customerId"] = customer_id


    return response


# ============================================================
# ADMIN RESOURCES
# ============================================================

def get_admin_resources(method_arn):

    """
    Admin can access all API Gateway methods.

    Example:

    arn:aws:execute-api:
    ap-south-1:
    ACCOUNT_ID:
    API_ID/dev/*/*
    """

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

    """
    Customer has read-only product access
    and order access.

    Customer is NOT allowed to:

    POST /products
    PUT /products/{id}
    DELETE /products/{id}
    """

    api_stage_arn = get_api_stage_arn(
        method_arn
    )

    return [

        # ----------------------------------------------------
        # PRODUCTS - READ ONLY
        # ----------------------------------------------------

        api_stage_arn + "/GET/products",

        api_stage_arn + "/GET/products/*",


        # ----------------------------------------------------
        # ORDERS
        # ----------------------------------------------------

        api_stage_arn + "/POST/orders",

        api_stage_arn + "/GET/orders",

        api_stage_arn + "/GET/orders/*"
    ]


# ============================================================
# AUTHORIZE
# ============================================================

def handler(event, context):

    print(json.dumps({
        "level": "INFO",
        "event": "authorizer_invoked",
        "request_id": context.aws_request_id
    }))


    # ========================================================
    # METHOD ARN
    # ========================================================

    method_arn = event.get(
        "methodArn",
        "*"
    )


    # ========================================================
    # AUTHORIZATION TOKEN
    # ========================================================

    authorization_token = event.get(
        "authorizationToken"
    )


    # ========================================================
    # MISSING TOKEN
    # ========================================================

    if not authorization_token:

        print(json.dumps({
            "level": "WARN",
            "event": "token_validation",
            "result": "missing"
        }))

        raise Exception("Unauthorized")


    # ========================================================
    # VALIDATE BEARER FORMAT
    # ========================================================

    if not authorization_token.startswith(
        "Bearer "
    ):

        print(json.dumps({
            "level": "WARN",
            "event": "token_validation",
            "result": "invalid_format"
        }))

        raise Exception("Unauthorized")


    supplied_token = authorization_token[
        7:
    ].strip()


    # ========================================================
    # EMPTY TOKEN
    # ========================================================

    if not supplied_token:

        print(json.dumps({
            "level": "WARN",
            "event": "token_validation",
            "result": "empty"
        }))

        raise Exception("Unauthorized")


    # ========================================================
    # READ ADMIN TOKEN
    # ========================================================

    try:

        admin_token = get_parameter_value(
            ADMIN_PARAMETER_NAME
        )

    except Exception as error:

        print(json.dumps({
            "level": "ERROR",
            "event": "admin_token_read",
            "result": "configuration_error",
            "error": str(error)
        }))

        raise Exception("Unauthorized")


    # ========================================================
    # CHECK ADMIN TOKEN
    # ========================================================

    if supplied_token == admin_token:

        print(json.dumps({
            "level": "INFO",
            "event": "token_validation",
            "result": "success",
            "role": "admin"
        }))


        admin_resources = get_admin_resources(
            method_arn
        )


        print(json.dumps({
            "level": "INFO",
            "event": "authorization",
            "result": "allowed",
            "role": "admin",
            "resources": admin_resources
        }))


        return generate_policy(

            effect="Allow",

            principal_id="cloudmart-admin",

            resources=admin_resources,

            role="admin"
        )


    # ========================================================
    # READ CUSTOMER TOKEN
    # ========================================================

    try:

        customer_token = get_parameter_value(
            CUSTOMER_PARAMETER_NAME
        )

    except Exception as error:

        print(json.dumps({
            "level": "ERROR",
            "event": "customer_token_read",
            "result": "configuration_error",
            "error": str(error)
        }))

        raise Exception("Unauthorized")


    # ========================================================
    # CHECK CUSTOMER TOKEN
    # ========================================================

    if supplied_token == customer_token:

        print(json.dumps({
            "level": "INFO",
            "event": "token_validation",
            "result": "success",
            "role": "customer",
            "customerId": CUSTOMER_ID
        }))


        customer_resources = get_customer_resources(
            method_arn
        )


        print(json.dumps({
            "level": "INFO",
            "event": "authorization",
            "result": "allowed",
            "role": "customer",
            "customerId": CUSTOMER_ID,
            "resources": customer_resources
        }))


        return generate_policy(

            effect="Allow",

            principal_id="cloudmart-customer",

            resources=customer_resources,

            role="customer",

            customer_id=CUSTOMER_ID
        )


    # ========================================================
    # INVALID TOKEN
    # ========================================================

    print(json.dumps({
        "level": "WARN",
        "event": "token_validation",
        "result": "failure"
    }))


    raise Exception("Unauthorized")