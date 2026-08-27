import json
import os


def lambda_handler(event, context):
    print(json.dumps({
        "level": "INFO",
        "message": "Product Lambda invoked",
        "environment": os.environ.get("ENVIRONMENT"),
        "request_id": context.aws_request_id
    }))

    return {
        "statusCode": 200,
        "headers": {
            "Content-Type": "application/json"
        },
        "body": json.dumps({
            "message": "Product API is working",
            "requestId": context.aws_request_id
        })
    }
