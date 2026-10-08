# CloudMart AWS Cloud Project

CloudMart is an AWS-based e-commerce application that demonstrates infrastructure as code, CI/CD, serverless application processing, authentication and authorization, relational database storage, event-driven notifications, monitoring, scheduled reporting, and an administrator dashboard.

The project is deployed in **AWS Region `ap-south-1` (Mumbai)**. Infrastructure is provisioned with **AWS CloudFormation**, and the main deployment pipeline is implemented with **GitHub Actions using AWS OIDC**.

> **Implementation note:** This README describes the current contents and deployment workflow of the final project ZIP. It intentionally follows the actual templates and workflow rather than an older reference architecture.

---

## 1. Project Objectives

CloudMart demonstrates:

- AWS VPC networking and security groups
- Public and private subnet design
- Private Amazon RDS MySQL
- AWS Lambda application services
- API Gateway REST API
- API Gateway REQUEST Lambda Authorizer
- Customer and administrator authorization
- SHA-256 customer authentication token hashes in RDS
- Administrator authentication token configuration through SSM Parameter Store
- Product CRUD operations
- Order creation, retrieval, and cancellation
- Inventory validation and stock updates
- Amazon EventBridge application events
- Amazon SNS email notifications
- CloudWatch custom metrics and alarms
- Daily CSV report generation
- Amazon S3 report storage
- Amazon EC2 Flask administrator dashboard
- AWS Systems Manager Session Manager / Run Command for dashboard configuration
- CloudFormation-based infrastructure provisioning
- GitHub Actions CI/CD with OIDC
- Environment-aware resource naming (`dev` / `prod` templates)

---

# 2. High-Level Architecture

The deployment flow is:

```text
Developer
   |
   v
GitHub Repository
   |
   v
GitHub Actions
   |
   | AWS OIDC
   v
AWS IAM Deployment Role
   |
   v
CloudFormation
   |
   +--------------------+
   |                    |
   v                    v
Network Stack        Data Stack
   |                    |
   |                    +--> RDS MySQL
   |                    |
   |                    +--> Lambda Artifact S3 Bucket
   |
   +--> VPC
   +--> Public Subnet
   +--> Private Subnet A
   +--> Private Subnet B
   +--> Security Groups
   +--> VPC Endpoints
   |
   v
IAM Stack
   |
   v
Lambda Execution Roles
   |
   v
Auth Stack
   |
   v
Lambda Authorizer
   |
   v
API Stack
   |
   +--> API Gateway REST API
   |
   +--> Product Lambda
   |
   +--> Schema Lambda
   |
   +--> Order Processor Lambda
   |
   v
RDS MySQL

API / Product / Order events
   |
   v
EventBridge
   |
   +--> Low-stock SNS
   +--> Order-confirmed SNS
   +--> Order-failed SNS
   +--> Order-cancelled SNS
   |
   v
Email notifications

Monitoring Stack
   |
   +--> CloudWatch metrics
   +--> CloudWatch alarms
   +--> Operations dashboard
   +--> Daily Report Lambda
   +--> Reports S3 bucket
   +--> EC2 Flask Dashboard

Daily schedule
   |
   v
EventBridge
   |
   v
Daily Report Lambda
   |
   +--> RDS MySQL
   |
   +--> CSV
   |
   v
S3 reports bucket
```

---

# 3. Repository Structure

The final project contains the following important structure:

```text
cloudmart-aws/
│
├── .github/
│   └── workflows/
│       └── deploy.yaml
│
├── cloudformation/
│   ├── api/
│   │   └── api-stack.yaml
│   │
│   ├── auth/
│   │   └── auth-stack.yaml
│   │
│   ├── data/
│   │   └── data-stack.yaml
│   │
│   ├── eventbridge/
│   │   └── eventbridge-stack.yaml
│   │
│   ├── iam/
│   │   └── iam-stack.yaml
│   │
│   ├── monitoring/
│   │   └── monitoring-stack.yaml
│   │
│   ├── network/
│   │   └── network-stack.yaml
│   │
│   └── schema/
│       └── schema-stack.yaml
│
├── dashboard/
│   ├── app.py
│   └── templates/
│       ├── index.html
│       └── login.html
│
├── lambda/
│   ├── authorizer/
│   │   ├── lambda_function.py
│   │   └── requirements.txt
│   │
│   ├── daily_report/
│   │   ├── lambda_function.py
│   │   └── requirements.txt
│   │
│   ├── order_processor/
│   │   ├── lambda_function.py
│   │   └── requirements.txt
│   │
│   ├── product/
│   │   ├── lambda_function.py
│   │   └── requirements.txt
│   │
│   └── schema/
│       ├── lambda_function.py
│       └── requirements.txt
│
├── schema/
│   └── schema.sql
│
└── README.md
```

### Important repository detail

The current deployment workflow uses:

- `cloudformation/network/network-stack.yaml`
- `cloudformation/data/data-stack.yaml`
- `cloudformation/iam/iam-stack.yaml`
- `cloudformation/auth/auth-stack.yaml`
- `cloudformation/api/api-stack.yaml`
- `cloudformation/eventbridge/eventbridge-stack.yaml`
- `cloudformation/monitoring/monitoring-stack.yaml`

The repository also contains `cloudformation/schema/schema-stack.yaml`, but the current `deploy.yaml` does **not** deploy this stack. The schema Lambda is deployed as part of the API stack and is invoked after API deployment.

The `schema/schema.sql` file is a database reference/schema script. The CI/CD workflow does not directly execute this SQL file with a MySQL client.

---

# 4. AWS Region and Environment

Current workflow configuration:

```yaml
AWS_REGION: ap-south-1
ENVIRONMENT: dev
```

The workflow currently uses `dev` stack names such as:

```text
cloudmart-dev-network
cloudmart-dev-data
cloudmart-dev-iam
cloudmart-dev-auth
cloudmart-dev-api
CloudMart-dev-eventbridge
cloudmart-dev-monitoring
```

The CloudFormation templates accept both:

```text
dev
prod
```

However, the current GitHub Actions workflow has `ENVIRONMENT: dev` hard-coded in its global environment section. Therefore, production deployment is not simply a matter of selecting a workflow environment; the workflow configuration must be changed or parameterized before it can deploy a separate production environment.

---

# 5. Network Architecture

The Network CloudFormation stack creates the CloudMart VPC.

## VPC

```text
CIDR: 10.0.0.0/16
```

DNS support and DNS hostnames are enabled.

## Public subnet

```text
CIDR: 10.0.1.0/24
```

The public subnet is used by the EC2 dashboard.

The subnet maps public IP addresses on launch.

## Private subnet A

```text
CIDR: 10.0.2.0/24
```

Used for private application/database connectivity.

## Private subnet B

```text
CIDR: 10.0.3.0/24
```

Used as the second private subnet for Lambda/RDS networking.

The RDS subnet group spans the two private subnets.

## Route tables

The stack creates:

- Public route table
- Public default route to the Internet Gateway
- Private route table
- Associations for both private subnets

There is no NAT Gateway in the current network template.

Instead, the private workloads use VPC endpoints for the AWS services required by the application.

---

# 6. Security Groups

The Network stack creates four main security groups.

## Lambda security group

Purpose:

- Lambda ENIs
- RDS access
- VPC endpoint access

Important outbound rules include:

```text
Lambda -> RDS
TCP 3306
```

and:

```text
Lambda -> VPC endpoints
TCP 443
```

The Lambda security group also has HTTPS egress as defined by the template.

## EC2 security group

Purpose:

- Public Flask dashboard

Inbound:

```text
TCP 80
Source: 0.0.0.0/0
```

The EC2 security group can connect to RDS on:

```text
TCP 3306
```

and to required VPC endpoints over:

```text
TCP 443
```

## RDS security group

Purpose:

- Private MySQL database

Inbound:

```text
TCP 3306 from Lambda security group
TCP 3306 from EC2 security group
```

RDS is not publicly accessible.

## Endpoint security group

Used by interface VPC endpoints.

The template allows HTTPS traffic from:

- Lambda security group
- EC2 security group

---

# 7. VPC Endpoints

The Network stack creates AWS service endpoints so private resources can reach required AWS services without a NAT Gateway.

The current template includes endpoints for services such as:

- S3
- SNS
- CloudWatch Logs
- CloudWatch Monitoring
- Systems Manager
- Systems Manager Messages
- KMS
- EventBridge

The S3 endpoint is a gateway endpoint.

The other endpoint resources are interface endpoints where configured by the template.

---

# 8. RDS MySQL

The Data stack creates Amazon RDS for MySQL.

Current configuration:

```text
Engine: mysql
Instance class: db.t3.micro
Allocated storage: 20 GB
Storage type: gp3
Storage encryption: enabled
Publicly accessible: false
Multi-AZ: false
Backup retention: 0
```

The RDS identifier follows:

```text
CloudMart-{Environment}-mysql
```

The database name is:

```text
cloudmart
```

The default deployment username is:

```text
cloudmartadmin
```

The password is supplied from the GitHub Actions secret:

```text
RDS_MASTER_PASSWORD
```

The Data stack uses the RDS security group exported by the Network stack.

The RDS resource uses:

```text
DeletionPolicy: Snapshot
UpdateReplacePolicy: Snapshot
```

---

# 9. RDS Configuration in Parameter Store

The Data stack creates these SSM parameters:

```text
/cloudmart/{environment}/db/host
/cloudmart/{environment}/db/port
/cloudmart/{environment}/db/name
/cloudmart/{environment}/db/username
/cloudmart/{environment}/db/password
```

In the current template these database parameters are created as:

```text
Type: String
```

The deployment workflow explicitly verifies that the username and password parameters are `String`.

The Lambda functions retrieve database configuration through Parameter Store instead of hardcoding the RDS endpoint or credentials.

---

# 10. Lambda Functions

The project contains five Lambda source components.

## 10.1 Authorizer Lambda

Source:

```text
lambda/authorizer/lambda_function.py
```

Purpose:

- Validate authorization header
- Identify admin requests
- Validate customer ID + token
- Hash customer tokens with SHA-256
- Query customer authentication records in RDS
- Generate an API Gateway authorization policy
- Place customer ID and role in the authorizer context

The authorizer is deployed by:

```text
cloudformation/auth/auth-stack.yaml
```

---

## 10.2 Product Lambda

Source:

```text
lambda/product/lambda_function.py
```

Provides product CRUD operations.

Supported API operations:

```text
GET    /products
GET    /products/{id}
POST   /products
PUT    /products/{id}
DELETE /products/{id}
```

The implementation maintains product inventory and publishes inventory-related events when appropriate.

Deleted products are handled according to the application's active/deleted state rather than simply assuming a physical database deletion.

---

## 10.3 Schema Lambda

Source:

```text
lambda/schema/lambda_function.py
```

Purpose:

- Create required database tables
- Seed products
- Seed customers
- Seed customer authentication token hashes
- Seed order statuses
- Create order tables
- Maintain authentication-table compatibility/migrations
- Optionally create/update an administrator authentication record when `admin_id` and `admin_token` are provided in the invocation event

The CI/CD pipeline invokes:

```text
CloudMart-${ENVIRONMENT}-schema
```

after the API stack is deployed.

The current workflow invokes the function without an event payload. Therefore, the workflow automatically performs the schema initialization, customer seed, customer-token seed, product seed, and order-status setup, but it does **not** currently pass `admin_id` and `admin_token` to the Schema Lambda.

This is important when documenting administrator token storage.

---

## 10.4 Order Processor Lambda

Source:

```text
lambda/order_processor/lambda_function.py
```

Supports:

```text
POST  /orders
GET   /orders
GET   /orders/{id}
PATCH /orders/{id}
```

Responsibilities include:

1. Validate the request.
2. Determine the authenticated customer/admin context.
3. Validate the customer.
4. Validate products and quantities.
5. Check inventory.
6. Calculate order totals.
7. Create order records.
8. Create order-item records.
9. Deduct inventory for successful orders.
10. Restore inventory for cancellation where appropriate.
11. Publish order events.
12. Publish CloudWatch custom metrics.
13. Return the order result.

Order states are:

```text
PENDING
CONFIRMED
FAILED
CANCELLED
```

---

## 10.5 Daily Report Lambda

Source:

```text
lambda/daily_report/lambda_function.py
```

Purpose:

- Read inventory from RDS
- Read today's orders
- Create order summaries
- Create CSV output
- Upload the CSV to S3

The report object key follows:

```text
daily/YYYY-MM-DD/cloudmart-daily-report-YYYYMMDDTHHMMSSZ.csv
```

The report uses server-side AES256 encryption when uploaded to S3.

---

# 11. API Gateway

The API stack creates an API Gateway REST API.

The API stage uses the environment name:

```text
dev
```

Therefore the API URL follows:

```text
https://{api-id}.execute-api.ap-south-1.amazonaws.com/dev
```

CloudFormation outputs provide separate URLs for products and orders.

## Product API

```text
GET    /products
GET    /products/{id}
POST   /products
PUT    /products/{id}
DELETE /products/{id}
```

## Order API

```text
POST  /orders
GET   /orders
GET   /orders/{id}
PATCH /orders/{id}
```

All of these API methods use:

```text
AuthorizationType: CUSTOM
```

and the CloudMart Lambda Authorizer.

---

# 12. Authentication and Authorization

## Authorization header

Requests use:

```text
Authorization: Bearer <token>
```

The authorizer checks the HTTP `Authorization` header.

The format must be:

```text
Bearer <token>
```

If the header is missing or incorrectly formatted, the request is rejected.

---

# 13. Customer Authentication

Customer requests require a customer ID.

The current implementation obtains the customer ID from the query string:

```text
customerId
```

Example:

```text
GET /orders?customerId=CUST001
```

The authorizer then:

1. Reads the supplied token.
2. Computes:

```text
SHA-256(token)
```

3. Queries `customer_auth_tokens`.
4. Joins the authentication record with `customers`.
5. Requires the customer to be active.
6. Requires the token record to be active.
7. Compares the generated SHA-256 hash with `token_hash`.
8. Checks `expires_at` when present.
9. Updates `last_used_at`.
10. Creates an authorization policy.
11. Adds the authenticated customer ID to the authorizer context.

Customer authorization is restricted to customer-level resources.

Customers can:

```text
GET /products
GET /products/{id}

POST /orders
GET /orders?customerId={id}
GET /orders/{id}
PATCH /orders/{id}
```

The Lambda code also verifies order ownership so one customer cannot operate on another customer's orders.

---

# 14. Administrator Authentication

The current implementation has two related administrator-token mechanisms.

## Active API authorization path

The API authorizer currently reads the administrator token from SSM:

```text
/cloudmart/{environment}/auth/admin-token
```

The GitHub Actions deployment creates/updates this value using:

```text
AUTH_TOKEN
```

The authorizer compares the supplied bearer token with the configured SSM value.

Therefore, for the current deployed API implementation, the administrator API token is authenticated against Parameter Store.

## RDS administrator token schema

The database schema also supports an administrator record in:

```text
customer_auth_tokens
```

with:

```text
role = 'admin'
admin_id = <administrator id>
token_hash = SHA-256(admin token)
customer_id = NULL
```

The Schema Lambda contains logic to create/update this record if both `admin_id` and `admin_token` are supplied in its invocation event.

However, the current GitHub Actions workflow invokes the Schema Lambda without those fields. Therefore, do not describe the current deployment as automatically populating the RDS administrator token hash unless that invocation is separately performed.

---

# 15. Authentication Database Design

The main authentication tables are:

## customers

Fields include:

```text
customer_id
name
email
status
created_at
updated_at
```

`customer_id` is the primary key.

Email is unique.

## customer_auth_tokens

Fields include:

```text
token_id
customer_id
admin_id
token_hash
role
is_active
created_at
expires_at
last_used_at
```

The role is:

```text
customer
admin
```

The database check constraint enforces:

### Customer record

```text
role = customer
customer_id is not NULL
admin_id is NULL
```

### Admin record

```text
role = admin
admin_id is not NULL
customer_id is NULL
```

Only the SHA-256 token hash is intended to be stored in this table.

---

# 16. Test Customer Data

The Schema Lambda seeds these customer records:

```text
CUST001
CUST002
CUST003
```

The source also seeds customer authentication records using SHA-256 hashes.

The plaintext customer tokens are part of the current source seed implementation. For a production system, replace test credentials with securely generated credentials and do not keep usable test secrets in source control.

---

# 17. Database Tables

The deployed schema includes:

```text
products
customers
customer_auth_tokens
order_status
orders
order_items
```

## products

Stores:

```text
id
name
description
price
stock
low_stock_threshold
is_active
created_at
updated_at
```

## customers

Stores customer identity and status.

## customer_auth_tokens

Stores authentication metadata and token hashes.

## order_status

Stores:

```text
PENDING
CONFIRMED
FAILED
CANCELLED
```

## orders

Stores:

```text
order_id
customer_id
total_amount
status_id
failure_reason
created_at
updated_at
```

## order_items

Stores:

```text
order_item_id
order_id
product_id
quantity
unit_price
line_total
```

---

# 18. Seed Products

The Schema Lambda initializes ten products.

Examples include:

```text
1. Apple iPhone 15
2. Samsung Galaxy S24
3. OnePlus 12
4. Apple MacBook Air M2
5. Dell Inspiron 15
6. Samsung Galaxy Tab S9 FE
7. Sony WH-1000XM5
8. JBL Flip 6
9. Logitech MX Master 3S
10. Apple AirPods Pro 2
```

Each product has a configured stock value and low-stock threshold.

The Schema Lambda uses `INSERT IGNORE`, so existing product rows are not overwritten during normal schema initialization.

---

# 19. Order Processing

A customer creates an order using a request body containing product IDs and quantities.

Example:

```json
{
  "items": [
    {
      "product_id": 1,
      "quantity": 2
    },
    {
      "product_id": 2,
      "quantity": 1
    }
  ]
}
```

The authenticated customer ID is taken from the authorizer context.

The order processor validates:

- Customer
- Product existence
- Product active status
- Quantity
- Available inventory
- Order totals

A successful order:

```text
Creates order
     |
Creates order items
     |
Deducts stock
     |
Sets order status
     |
Publishes OrderConfirmed
     |
Publishes metrics
```

A failed order records the failure reason and can publish an `OrderFailed` event.

---

# 20. Order Cancellation

Cancellation uses:

```text
PATCH /orders/{id}
```

Example:

```json
{
  "status": "cancelled"
}
```

The order processor verifies authorization/ownership and restores product inventory when cancellation rules require it.

A cancellation publishes an order-cancelled event.

---

# 21. EventBridge

The EventBridge stack creates a custom event bus:

```text
cloudmart-{environment}-event-bus
```

The application uses events such as:

```text
Low Stock Alert
OrderConfirmed
OrderFailed
OrderCancelled
```

---

# 22. Low-Stock Flow

The low-stock flow is:

```text
Product Lambda
      |
      v
EventBridge
      |
      v
Low-stock EventBridge Rule
      |
      v
SNS
      |
      v
Email
```

The rule name follows:

```text
cloudmart-{environment}-low-stock-rule
```

The event uses:

```text
source: cloudmart.product
detail-type: Low Stock Alert
```

The notification includes information such as:

```text
Product ID
Product Name
Current Stock
Low Stock Threshold
```

---

# 23. Order Notification Flow

## Confirmed order

```text
Order Processor
      |
      v
EventBridge
      |
      v
OrderConfirmed rule
      |
      v
SNS
      |
      v
Email
```

## Failed order

```text
Order Processor
      |
      v
EventBridge
      |
      v
OrderFailed rule
      |
      v
SNS
      |
      v
Email
```

## Cancelled order

```text
Order Processor
      |
      v
EventBridge
      |
      v
OrderCancelled rule
      |
      v
SNS
      |
      v
Email
```

The eventbridge stack accepts:

```text
LOW_STOCK_EMAIL
ORDER_NOTIFICATION_EMAIL
```

from GitHub Actions.

---

# 24. Monitoring

The monitoring stack contains:

- CloudWatch operations dashboard
- CloudWatch alarms
- SNS alarm topic
- Daily Report Lambda
- Daily report EventBridge schedule
- Reports S3 bucket
- EC2 dashboard
- EC2 IAM role
- EC2 instance profile

The CloudWatch dashboard name follows:

```text
cloudmart-operations-{environment}
```

---

# 25. Custom CloudWatch Metrics

The application publishes CloudMart metrics for operational monitoring.

The main metrics include:

```text
OrdersPlaced
OrdersFailed
OrdersCancelled
LowStockEvents
```

The metrics are associated with the CloudMart application/environment.

---

# 26. CloudWatch Alarms

The monitoring stack defines alarms for:

```text
Authorizer Lambda errors
Product Lambda errors
Order Processor Lambda errors
Schema Lambda errors
Daily Report Lambda errors
API Gateway 4XX errors
API Gateway 5XX errors
Failed orders
Low-stock events
Cancelled orders
RDS high CPU
```

Alarm notifications are sent through the operations SNS topic.

---

# 27. Daily Reporting

The daily report schedule is:

```text
cron(0 18 * * ? *)
```

This is an EventBridge cron expression in UTC.

That corresponds to:

```text
18:00 UTC
23:30 IST
```

The flow is:

```text
EventBridge schedule
       |
       v
Daily Report Lambda
       |
       +--> RDS inventory
       |
       +--> RDS today's orders
       |
       +--> Order summary
       |
       v
CSV
       |
       v
S3 Reports Bucket
```

Report keys are:

```text
daily/YYYY-MM-DD/cloudmart-daily-report-YYYYMMDDTHHMMSSZ.csv
```

The dashboard searches the `daily/` prefix and displays the latest available report.

---

# 28. Administrator Dashboard

The dashboard is a Flask application.

Source:

```text
dashboard/app.py
```

Templates:

```text
dashboard/templates/login.html
dashboard/templates/index.html
```

The dashboard is hosted on EC2.

The current EC2 configuration is:

```text
Instance type: t3.micro
AMI: latest Amazon Linux 2023 x86_64 SSM parameter
Root volume: 10 GB gp3
Root volume: encrypted
Subnet: CloudMart public subnet
Security group: CloudMart EC2 security group
IAM instance profile: CloudMart dashboard instance profile
```

The dashboard is accessed through:

```text
http://<EC2 Public DNS>
```

The CloudFormation output is:

```text
DashboardUrl
```

---

# 29. Dashboard Login

The dashboard provides:

```text
/login
```

The administrator enters the admin token.

The application retrieves the configured token from:

```text
/cloudmart/{environment}/auth/admin-token
```

and compares the entered value using constant-time comparison.

A successful login creates a Flask session.

The dashboard also supports:

```text
/logout
```

The application uses:

```text
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = Lax
```

A Flask secret is generated on the EC2 instance and stored at:

```text
/etc/cloudmart-dashboard/flask-secret
```

---

# 30. Dashboard Data

The dashboard displays operational information including:

- Product inventory
- Low-stock products
- Product count
- Today's order count
- Today's failed order count
- Recent orders
- Order status
- Latest daily report

The dashboard reads database configuration from SSM and reports from S3.

---

# 31. EC2 Dashboard Deployment

The monitoring CloudFormation stack creates the EC2 instance.

The GitHub Actions monitoring job then:

1. Packages the dashboard.
2. Uploads the dashboard ZIP to the Lambda artifact S3 bucket.
3. Creates a SHA-based dashboard object key.
4. Creates the daily report Lambda package.
5. Uploads the report Lambda package.
6. Deploys the monitoring CloudFormation stack.
7. Retrieves the EC2 instance ID.
8. Waits for the EC2 instance to become running.
9. Waits for the SSM Agent to become online.
10. Uses SSM Run Command to install dashboard software.
11. Installs Python 3.12, pip, Nginx, unzip, and OpenSSL.
12. Creates a Python virtual environment.
13. Installs Flask, boto3, PyMySQL, and Gunicorn.
14. Creates the Flask secret.
15. Creates the `cloudmart-dashboard` systemd service.
16. Configures Nginx.
17. Starts Gunicorn and Nginx.
18. Verifies both services.
19. Checks the local HTTP endpoint.
20. Checks the public dashboard URL.

---

# 32. EC2 Key Pair Note

The current `monitoring-stack.yaml` does **not** define a `KeyName` property for the EC2 instance.

Therefore, the current CloudFormation deployment does not attach an EC2 SSH key pair to the dashboard instance.

Dashboard administration is instead configured through the SSM Agent and the EC2 IAM instance profile.

If SSH key-pair access is required later, the CloudFormation template and deployment parameters would need to be updated.

---

# 33. IAM

The IAM stack creates roles for:

```text
Authorizer Lambda
Product Lambda
Order Processor Lambda
```

The monitoring stack creates the dashboard EC2 role.

The dashboard role uses:

```text
AmazonSSMManagedInstanceCore
```

and additional permissions for:

- Reading database configuration from SSM
- Reading the admin token parameter
- Reading report objects from S3
- Reading the dashboard artifact from S3

The project uses IAM roles instead of storing AWS access keys inside application code.

---

# 34. GitHub Actions Authentication

The workflow uses GitHub Actions OIDC.

The workflow permissions include:

```yaml
permissions:
  id-token: write
  contents: read
```

The workflow uses:

```text
aws-actions/configure-aws-credentials@v4
```

with:

```text
AWS_ROLE_ARN
```

The deployment does not require long-lived AWS access keys in GitHub Actions.

---

# 35. GitHub Actions Secrets

The current workflow expects these GitHub repository secrets:

```text
AWS_ROLE_ARN
RDS_MASTER_PASSWORD
AUTH_TOKEN
LOW_STOCK_EMAIL
ORDER_NOTIFICATION_EMAIL
OPERATIONS_EMAIL
```

Do not commit these values to the repository.

### Secret purposes

`AWS_ROLE_ARN`

The ARN of the IAM role assumed through GitHub OIDC.

`RDS_MASTER_PASSWORD`

The RDS master password passed to the Data CloudFormation stack.

`AUTH_TOKEN`

The administrator token stored in the SSM admin-token parameter.

`LOW_STOCK_EMAIL`

Email address for low-stock SNS notifications.

`ORDER_NOTIFICATION_EMAIL`

Email address for order confirmation/failure/cancellation notifications.

`OPERATIONS_EMAIL`

Email address for CloudWatch operations alarm notifications.

---

# 36. CI/CD Pipeline

The workflow file is:

```text
.github/workflows/deploy.yaml
```

It triggers on pushes to:

```text
main
orders
```

and can also be manually started using:

```text
workflow_dispatch
```

The deployment sequence is:

```text
1. Network
2. Data / RDS
3. IAM
4. Authentication
5. API / Lambda
6. EventBridge / SNS
7. Monitoring / Reporting / EC2 Dashboard
```

---

# 37. Deployment Job Dependencies

The actual workflow dependency chain is:

```text
deploy-network
       |
       v
deploy-data
       |
       v
deploy-iam
       |
       +-------------------+
       |                   |
       v                   |
deploy-auth  <-------------+
       |
       v
deploy-api
       |
       v
deploy-eventbridge
       |
       v
deploy-monitoring
```

Authentication waits for:

```text
Network
Data
IAM
```

API waits for:

```text
Network
Data
IAM
Auth
```

EventBridge waits for:

```text
API
```

Monitoring waits for:

```text
EventBridge
```

---

# 38. Lambda Packaging in CI/CD

The workflow packages the application Lambdas during deployment.

Product:

```text
lambda/product/lambda_function.py
lambda/product/requirements.txt
```

Schema:

```text
lambda/schema/lambda_function.py
lambda/schema/requirements.txt
```

Order processor:

```text
lambda/order_processor/lambda_function.py
lambda/order_processor/requirements.txt
```

Authorizer:

```text
lambda/authorizer/lambda_function.py
lambda/authorizer/requirements.txt
```

Daily report:

```text
lambda/daily_report/lambda_function.py
lambda/daily_report/requirements.txt
```

Packages are uploaded to the Lambda artifact S3 bucket created by the Data stack.

---

# 39. Lambda Artifact Layout

The workflow uses keys similar to:

```text
authorizer/authorizer.zip
product/product.zip
schema/schema.zip
order-processor/order-processor.zip
daily-report/daily-report-{GITHUB_SHA}.zip
dashboard/dashboard-{GITHUB_SHA}.zip
```

The SHA-based dashboard/report artifact keys allow a new deployment to use a new S3 object when the source changes.

---

# 40. Database Initialization During Deployment

After the API stack is deployed, GitHub Actions invokes:

```text
CloudMart-${ENVIRONMENT}-schema
```

The workflow checks the Lambda function error result.

If the Schema Lambda reports a function error, the deployment job fails.

The Schema Lambda creates or updates the database objects required by the application.

---

# 41. Deployment Prerequisites

Before running the deployment, ensure:

- AWS account is available.
- AWS region is `ap-south-1`.
- GitHub repository exists.
- GitHub Actions is enabled.
- AWS OIDC provider exists.
- GitHub Actions IAM role exists.
- The role trusts the correct GitHub repository/branches.
- `AWS_ROLE_ARN` is configured.
- `RDS_MASTER_PASSWORD` is configured.
- `AUTH_TOKEN` is configured.
- `LOW_STOCK_EMAIL` is configured.
- `ORDER_NOTIFICATION_EMAIL` is configured.
- `OPERATIONS_EMAIL` is configured.
- The GitHub role can deploy the required CloudFormation resources.
- The GitHub role can package/upload Lambda artifacts to S3.
- The GitHub role can invoke the Schema Lambda.
- The GitHub role can use SSM Run Command for the dashboard.

---

# 42. API Testing

After deployment, retrieve:

```text
ProductApiUrl
OrderApiUrl
```

from the API CloudFormation stack outputs.

## Product list

```text
GET <ProductApiUrl>
```

with:

```text
Authorization: Bearer <customer-token-or-admin-token>
```

## Get product

```text
GET <ProductApiUrl>/{id}
```

## Create product

```text
POST <ProductApiUrl>
```

Admin authorization is required.

Example body:

```json
{
  "name": "Test Product",
  "description": "CloudMart test product",
  "price": 1999.00,
  "stock": 20,
  "low_stock_threshold": 5
}
```

## Update product

```text
PUT <ProductApiUrl>/{id}
```

Admin authorization is required.

## Delete product

```text
DELETE <ProductApiUrl>/{id}
```

Admin authorization is required.

---

# 43. Customer Order Testing

Example:

```text
POST <OrderApiUrl>
```

Headers:

```text
Authorization: Bearer <customer-token>
```

The request must contain the customer identity expected by the authorizer, for example:

```text
customerId=CUST001
```

Example body:

```json
{
  "items": [
    {
      "product_id": 1,
      "quantity": 2
    }
  ]
}
```

Then verify:

- Order created
- Inventory reduced
- Order status updated
- EventBridge event generated
- Notification generated where configured
- CloudWatch metrics updated

---

# 44. Order Retrieval

Customer order list:

```text
GET <OrderApiUrl>?customerId=CUST001
```

Individual order:

```text
GET <OrderApiUrl>/{order_id}
```

The application checks that customer-level access does not expose another customer's order.

Administrators can access administrative order operations according to the authorization policy.

---

# 45. Order Cancellation Test

Use:

```text
PATCH <OrderApiUrl>/{order_id}
```

Body:

```json
{
  "status": "cancelled"
}
```

Verify:

```text
Order status = CANCELLED
Inventory restored where applicable
OrderCancelled event generated
SNS notification generated
OrdersCancelled metric updated
```

---

# 46. Low-Stock Test

To test low-stock behavior:

1. Select an active product.
2. Confirm its current stock and threshold.
3. Perform an order that reduces stock to or below the threshold.
4. Confirm the Product/Order logic publishes the low-stock event.
5. Check the EventBridge rule.
6. Check the low-stock SNS topic.
7. Check the configured email.
8. Check the CloudWatch `LowStockEvents` metric.
9. Check the low-stock alarm if its configured threshold is reached.

---

# 47. Dashboard Verification

Get the dashboard URL:

```text
CloudFormation
    ->
cloudmart-dev-monitoring
    ->
Outputs
    ->
DashboardUrl
```

Open the URL.

Expected flow:

```text
DashboardUrl
    |
    v
/login
    |
    v
Enter admin token
    |
    v
Dashboard
```

Verify:

- Login works.
- Product inventory is displayed.
- Low-stock products are visible.
- Recent orders are visible.
- Today's order count is displayed.
- Failed order count is displayed.
- Latest daily report is available when one exists.
- `/health` returns a healthy response.

---

# 48. CloudWatch Verification

Open:

```text
AWS Console
    ->
CloudWatch
    ->
Dashboards
```

Look for:

```text
cloudmart-operations-dev
```

Verify the dashboard contains the expected application metrics and infrastructure health information.

---

# 49. Report Verification

Open:

```text
AWS Console
    ->
S3
    ->
CloudMart reports bucket
```

Expected prefix:

```text
daily/
```

Expected object format:

```text
daily/YYYY-MM-DD/cloudmart-daily-report-YYYYMMDDTHHMMSSZ.csv
```

The report contains:

```text
Report metadata
Order summary
Orders
Inventory
```

---

# 50. Common Deployment Failure Checks

## CloudFormation failure

Check:

```text
AWS Console
    ->
CloudFormation
    ->
Stack
    ->
Events
```

Also check the corresponding GitHub Actions job.

## RDS deployment failure

Check:

- RDS password secret exists.
- Password meets the template constraints.
- RDS security group exists.
- Private subnet outputs exist.
- DB subnet group contains both private subnets.

## Lambda deployment failure

Check:

- Lambda artifact bucket exists.
- ZIP package was uploaded.
- Lambda package contains the expected handler.
- Python dependencies were installed into the ZIP.
- IAM role ARN outputs exist.
- Lambda security group exists.

## Authorizer failure

Check:

```text
/cloudmart/dev/auth/admin-token
```

and database connectivity.

For customer requests check:

```text
Authorization: Bearer <token>
customerId=<customer id>
```

Also verify that the corresponding customer is active and the stored SHA-256 hash matches the supplied token.

## API 401/403

Check:

- Authorization header format.
- Bearer token.
- Customer ID for customer requests.
- Customer active status.
- Token active status.
- Authorizer Lambda CloudWatch logs.
- API Gateway authorizer configuration.

## Dashboard failure

Check:

```text
SSM
CloudWatch Logs
EC2 status
cloudmart-dashboard systemd service
nginx service
```

The deployment writes dashboard installation output to:

```text
/var/log/cloudmart-dashboard-ssm.log
```

The service is:

```text
cloudmart-dashboard
```

---

# 51. Useful AWS Console Locations

Network:

```text
VPC
```

Database:

```text
RDS
```

Parameters:

```text
Systems Manager
    ->
Parameter Store
```

Functions:

```text
Lambda
```

API:

```text
API Gateway
```

Events:

```text
EventBridge
```

Notifications:

```text
SNS
```

Logs:

```text
CloudWatch Logs
```

Metrics and alarms:

```text
CloudWatch
```

Reports:

```text
S3
```

Dashboard:

```text
EC2
```

Instance management:

```text
Systems Manager
    ->
Fleet Manager / Run Command
```

---

# 52. Security Practices

The current project implements:

- Private RDS.
- Security-group-controlled RDS access.
- Lambda-to-RDS security-group rules.
- EC2-to-RDS security-group rules.
- VPC endpoints for private AWS service access.
- IAM execution roles.
- GitHub Actions OIDC.
- No long-lived AWS access keys in the workflow.
- Encrypted RDS storage.
- Encrypted EC2 root volume.
- S3 server-side encryption for generated reports.
- S3 artifact access through IAM.
- HTTP-only Flask session cookies.
- SameSite `Lax` session configuration.
- SHA-256 hashing for customer token records.
- Environment-based parameter paths.
- Public access only to the EC2 dashboard HTTP endpoint and API Gateway endpoint.

---

# 53. Important Current-Project Security Notes

The following are important when presenting the current implementation.

### Admin API token

The current authorizer compares the admin bearer token with the SSM Parameter Store value.

It does not currently authenticate the admin bearer token by querying the RDS `customer_auth_tokens` admin row.

The database schema supports the hashed admin record, but the deployment workflow does not pass `admin_id` and `admin_token` to the Schema Lambda.

### Customer test tokens

The current Schema Lambda contains test customer token seed values and stores their SHA-256 hashes.

For a production system, replace these test credentials with securely provisioned credentials.

### SSM parameter type

The current deployment intentionally creates database credentials and the admin token as SSM `String` parameters. The Lambda code therefore retrieves them without relying on SecureString decryption semantics in the authorizer.

### Dashboard exposure

The EC2 security group allows HTTP port 80 from `0.0.0.0/0`. The dashboard login provides application-level authentication, but the current deployment does not provide HTTPS/TLS termination.

For production, place the dashboard behind an appropriate HTTPS-capable front end and restrict direct exposure where possible.

---

# 54. CloudFormation Stack Summary

## Network

```text
cloudmart-dev-network
```

Creates:

- VPC
- Subnets
- Internet Gateway
- Route tables
- Security groups
- VPC endpoints

## Data

```text
cloudmart-dev-data
```

Creates:

- RDS MySQL
- Lambda artifact S3 bucket
- Database SSM parameters

## IAM

```text
cloudmart-dev-iam
```

Creates:

- Authorizer Lambda role
- Product Lambda role
- Order Processor Lambda role

## Auth

```text
cloudmart-dev-auth
```

Creates:

- Authorizer Lambda
- API Gateway Lambda permission

## API

```text
cloudmart-dev-api
```

Creates:

- Product Lambda
- Schema Lambda
- Order Processor Lambda
- API Gateway REST API
- API Gateway authorizer
- Product resources/methods
- Order resources/methods
- Low-stock SNS topic/subscription

## EventBridge

```text
CloudMart-dev-eventbridge
```

Creates:

- Event bus
- Low-stock rule
- Order confirmed rule
- Order failed rule
- Order cancelled rule
- SNS topics/subscriptions/policies

## Monitoring

```text
cloudmart-dev-monitoring
```

Creates:

- Reports S3 bucket
- Daily Report Lambda
- Daily report schedule
- EC2 dashboard
- Dashboard IAM role/profile
- CloudWatch operations dashboard
- CloudWatch alarms
- Operations SNS topic

---

# 55. Deployment Order Rationale

The order is important because later stacks consume outputs from earlier stacks.

```text
Network
   |
   +--> subnet IDs
   +--> security group IDs
   |
Data
   |
   +--> RDS parameters
   +--> Lambda artifact bucket
   |
IAM
   |
   +--> Lambda execution role ARNs
   |
Auth
   |
   +--> Authorizer ARN
   |
API
   |
   +--> application API
   +--> application Lambdas
   |
EventBridge
   |
   +--> event bus and notification rules
   |
Monitoring
   |
   +--> reports
   +--> dashboard
   +--> alarms
   +--> EC2
```

This dependency chain prevents later stacks from being deployed before their required resources and outputs exist.

---

# 56. Final Deployment Checklist

Before deployment:

```text
[ ] AWS account available
[ ] Region = ap-south-1
[ ] GitHub repository configured
[ ] OIDC provider configured
[ ] GitHub Actions role configured
[ ] AWS_ROLE_ARN configured
[ ] RDS_MASTER_PASSWORD configured
[ ] AUTH_TOKEN configured
[ ] LOW_STOCK_EMAIL configured
[ ] ORDER_NOTIFICATION_EMAIL configured
[ ] OPERATIONS_EMAIL configured
```

After deployment:

```text
[ ] Network stack successful
[ ] Data stack successful
[ ] IAM stack successful
[ ] Auth stack successful
[ ] API stack successful
[ ] EventBridge stack successful
[ ] Monitoring stack successful
[ ] Schema Lambda successful
[ ] RDS reachable from Lambda
[ ] Product API tested
[ ] Order API tested
[ ] Customer authentication tested
[ ] Admin authentication tested
[ ] Low-stock event tested
[ ] Order notification tested
[ ] CloudWatch dashboard verified
[ ] CloudWatch alarms verified
[ ] Daily report verified
[ ] EC2 dashboard running
[ ] Dashboard login tested
[ ] Dashboard health endpoint tested
```

---

# 57. Project Outcome

CloudMart provides an end-to-end AWS deployment containing:

```text
Networking
    +
Security Groups
    +
VPC Endpoints
    +
RDS MySQL
    +
Lambda
    +
API Gateway
    +
Lambda Authorizer
    +
Authentication
    +
Product CRUD
    +
Order Processing
    +
EventBridge
    +
SNS
    +
CloudWatch
    +
Scheduled Reports
    +
S3
    +
EC2 Flask Dashboard
    +
GitHub Actions OIDC
    +
CloudFormation
```

The project demonstrates how infrastructure and application components can be provisioned and deployed through an environment-aware AWS CloudFormation architecture and a GitHub Actions CI/CD pipeline.
