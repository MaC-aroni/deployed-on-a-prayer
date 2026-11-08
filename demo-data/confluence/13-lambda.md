---
id: platform-lambda
title: "Platform: Lambda Service Standard"
parent: handbook
owner: platform-engineering
labels: [platform, lambda, standard]
---
## Runtime

- Runtime `python3.12`, 256 MB memory, a timeout of 15 seconds or less.
- Package the service directory with the `archive_file` data source, and set
  `source_code_hash` so changes redeploy.
- Use only the standard library and the `boto3` that the runtime provides.

## Endpoints

- Expose the service with an `aws_lambda_function_url` whose `authorization_type` is
  **`AWS_IAM`**. Unauthenticated URLs are never allowed.
- Callers sign each request with AWS SigV4 for the `lambda` service.
- Services provide `GET /health`, returning `{"status": "ok"}`.

## Roles

- One role per function, named after the function, trusted by `lambda.amazonaws.com`.
- Attach `AWSLambdaBasicExecutionRole` for logs, and add inline policies for only the actions
  and resources the function needs. For example, a service that reads one table gets
  `dynamodb:GetItem` on that table's ARN and nothing else.
- Roles are created by the owning service's infrastructure component (`terraform/iam`) before
  the functions that use them.

## Configuration

Pass table names and the names of other functions through environment variables, built from
the naming standard. Look up other functions' URLs at runtime with
`lambda:GetFunctionUrlConfig` instead of hard-coding them.
