import json
import os
import boto3

ssm = boto3.client("ssm")

PARAMETER_NAME = os.environ["AUTH_TOKEN_PARAMETER"]


def generate_policy(effect, principal_id, method_arn):
    return {
        "principalId": principal_id,
        "policyDocument": {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Action": "execute-api:Invoke",
                    "Effect": effect,
                    "Resource": method_arn
                }
            ]
        }
    }


def handler(event, context):

    method_arn = event.get("methodArn", "*")

    authorization_token = event.get("authorizationToken")

    # ------------------------------------------------
    # Missing token
    # ------------------------------------------------

    if not authorization_token:
        print(json.dumps({
            "level": "WARN",
            "event": "token_validation",
            "result": "missing"
        }))

        raise Exception("Unauthorized")


    # ------------------------------------------------
    # Validate Bearer format
    # ------------------------------------------------

    if not authorization_token.startswith("Bearer "):
        print(json.dumps({
            "level": "WARN",
            "event": "token_validation",
            "result": "invalid_format"
        }))

        raise Exception("Unauthorized")


    supplied_token = authorization_token[7:].strip()


    if not supplied_token:
        print(json.dumps({
            "level": "WARN",
            "event": "token_validation",
            "result": "empty"
        }))

        raise Exception("Unauthorized")


    # ------------------------------------------------
    # Read expected token from SSM
    # ------------------------------------------------

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
            "result": "configuration_error"
        }))

        raise Exception("Unauthorized")


    # ------------------------------------------------
    # Compare token
    # ------------------------------------------------

    if supplied_token != expected_token:

        print(json.dumps({
            "level": "WARN",
            "event": "token_validation",
            "result": "failure"
        }))

        raise Exception("Unauthorized")


    # ------------------------------------------------
    # Valid token
    # ------------------------------------------------

    print(json.dumps({
        "level": "INFO",
        "event": "token_validation",
        "result": "success"
    }))


    return generate_policy(
        "Allow",
        "cloudmart-authenticated-client",
        method_arn
    )
