import json
import os
import boto3


ssm = boto3.client("ssm")


PARAMETER_NAME = os.environ["AUTH_TOKEN_PARAMETER"]


# ============================================================
# GENERATE IAM POLICY
# ============================================================

def generate_policy(effect, principal_id, resource):

    return {
        "principalId": principal_id,

        "policyDocument": {
            "Version": "2012-10-17",

            "Statement": [
                {
                    "Action": "execute-api:Invoke",
                    "Effect": effect,
                    "Resource": resource
                }
            ]
        }
    }


# ============================================================
# CREATE WILDCARD API RESOURCE
# ============================================================

def get_wildcard_resource(method_arn):

    """
    Converts:

    arn:aws:execute-api:ap-south-1:ACCOUNT_ID:API_ID/dev/GET/products

    into:

    arn:aws:execute-api:ap-south-1:ACCOUNT_ID:API_ID/dev/*/*
    """

    parts = method_arn.split("/")

    if len(parts) < 3:
        return method_arn

    wildcard_resource = (
        parts[0]
        + "/"
        + parts[1]
        + "/*/*"
    )

    return wildcard_resource


# ============================================================
# AUTHORIZE
# ============================================================

def handler(event, context):

    print(json.dumps({
        "level": "INFO",
        "event": "authorizer_invoked",
        "request_id": context.aws_request_id
    }))


    # --------------------------------------------------------
    # METHOD ARN
    # --------------------------------------------------------

    method_arn = event.get("methodArn", "*")


    # --------------------------------------------------------
    # GET AUTHORIZATION TOKEN
    # --------------------------------------------------------

    authorization_token = event.get("authorizationToken")


    # --------------------------------------------------------
    # MISSING TOKEN
    # --------------------------------------------------------

    if not authorization_token:

        print(json.dumps({
            "level": "WARN",
            "event": "token_validation",
            "result": "missing"
        }))

        raise Exception("Unauthorized")


    # --------------------------------------------------------
    # VALIDATE BEARER FORMAT
    # --------------------------------------------------------

    if not authorization_token.startswith("Bearer "):

        print(json.dumps({
            "level": "WARN",
            "event": "token_validation",
            "result": "invalid_format"
        }))

        raise Exception("Unauthorized")


    supplied_token = authorization_token[7:].strip()


    # --------------------------------------------------------
    # EMPTY TOKEN
    # --------------------------------------------------------

    if not supplied_token:

        print(json.dumps({
            "level": "WARN",
            "event": "token_validation",
            "result": "empty"
        }))

        raise Exception("Unauthorized")


    # --------------------------------------------------------
    # READ TOKEN FROM SSM
    # --------------------------------------------------------

    try:

        parameter = ssm.get_parameter(
            Name=PARAMETER_NAME,
            WithDecryption=True
        )

        expected_token = parameter["Parameter"]["Value"]


    except Exception as error:

        print(json.dumps({
            "level": "ERROR",
            "event": "token_validation",
            "result": "configuration_error",
            "error": str(error)
        }))

        raise Exception("Unauthorized")


    # --------------------------------------------------------
    # COMPARE TOKEN
    # --------------------------------------------------------

    if supplied_token != expected_token:

        print(json.dumps({
            "level": "WARN",
            "event": "token_validation",
            "result": "failure"
        }))

        raise Exception("Unauthorized")


    # --------------------------------------------------------
    # VALID TOKEN
    # --------------------------------------------------------

    print(json.dumps({
        "level": "INFO",
        "event": "token_validation",
        "result": "success"
    }))


    # --------------------------------------------------------
    # CREATE WILDCARD RESOURCE
    # --------------------------------------------------------

    wildcard_resource = get_wildcard_resource(
        method_arn
    )


    print(json.dumps({
        "level": "INFO",
        "event": "authorization",
        "result": "allowed",
        "resource": wildcard_resource
    }))


    # --------------------------------------------------------
    # RETURN ALLOW POLICY
    # --------------------------------------------------------

    return generate_policy(
        "Allow",
        "cloudmart-authenticated-client",
        wildcard_resource
    )