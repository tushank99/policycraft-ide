# ─── Log groups (pre-created so each role can be scoped to its own group) ────
resource "aws_cloudwatch_log_group" "lambda" {
  #checkov:skip=CKV_AWS_158:Log encryption with a CMK costs money; CloudWatch encrypts logs at rest by default.
  #checkov:skip=CKV_AWS_338:1-year retention exceeds the 5 GB free tier; 14 days is enough for this project.
  for_each          = local.lambda_services
  name              = "/aws/lambda/idp-${replace(each.key, "_", "-")}"
  retention_in_days = 14
}

# ─── Common env vars for all Lambdas ─────────────────────────────────────────
locals {
  common_env = {
    TABLE_NAME       = local.table_name
    ARTIFACTS_BUCKET = local.bucket_name
    SQS_QUEUE_URL    = aws_sqs_queue.generation.url
  }
}

# ─── policy_service ───────────────────────────────────────────────────────────
data "archive_file" "policy_service" {
  type        = "zip"
  output_path = "${path.module}/builds/policy_service.zip"

  source {
    content  = file("${path.module}/../backend/policy_service/handler.py")
    filename = "handler.py"
  }
  source {
    content  = file("${path.module}/../backend/shared/auth.py")
    filename = "shared/auth.py"
  }
  source {
    content  = file("${path.module}/../backend/policy_service/defaults.py")
    filename = "defaults.py"
  }
  source {
    content  = file("${path.module}/../backend/policy_service/parser.py")
    filename = "parser.py"
  }
  source {
    content  = file("${path.module}/../backend/shared/__init__.py")
    filename = "shared/__init__.py"
  }
  source {
    content  = file("${path.module}/../backend/shared/db.py")
    filename = "shared/db.py"
  }
  source {
    content  = file("${path.module}/../backend/shared/logger.py")
    filename = "shared/logger.py"
  }
  source {
    content  = file("${path.module}/../backend/shared/response.py")
    filename = "shared/response.py"
  }
  source {
    content  = file("${path.module}/../backend/shared/s3_helper.py")
    filename = "shared/s3_helper.py"
  }
}

resource "aws_lambda_function" "policy_service" {
  #checkov:skip=CKV_AWS_117:No VPC resources to reach; a VPC would require a paid NAT gateway for Groq/GitHub egress.
  #checkov:skip=CKV_AWS_173:Env vars hold only resource names / SSM parameter names, no secrets; CMK costs money.
  #checkov:skip=CKV_AWS_115:New accounts have a 10-concurrency quota; reserving concurrency can fail the deploy.
  #checkov:skip=CKV_AWS_50:X-Ray PutTraceSegments only supports Resource "*", which conflicts with the no-wildcard IAM rule.
  #checkov:skip=CKV_AWS_272:Code signing is out of scope for this project.
  #checkov:skip=CKV_AWS_116:Synchronous/stream invocations; failed SQS messages go to the queue-level DLQ.
  function_name    = "idp-policy-service"
  role             = aws_iam_role.lambda["policy_service"].arn
  filename         = data.archive_file.policy_service.output_path
  source_code_hash = data.archive_file.policy_service.output_base64sha256
  runtime          = "python3.12"
  depends_on       = [aws_iam_role_policy.lambda, aws_cloudwatch_log_group.lambda]
  handler          = "handler.handler"
  timeout          = 30
  memory_size      = 256
  environment {
    variables = merge(local.common_env, { AUTH_ENABLED = tostring(var.enable_api_auth) })
  }
}

# ─── status_service ───────────────────────────────────────────────────────────
data "archive_file" "status_service" {
  type        = "zip"
  output_path = "${path.module}/builds/status_service.zip"

  source {
    content  = file("${path.module}/../backend/status_service/handler.py")
    filename = "handler.py"
  }
  source {
    content  = file("${path.module}/../backend/policy_service/parser.py")
    filename = "parser.py"
  }
  source {
    content  = file("${path.module}/../backend/policy_service/defaults.py")
    filename = "defaults.py"
  }
  source {
    content  = file("${path.module}/../backend/shared/__init__.py")
    filename = "shared/__init__.py"
  }
  source {
    content  = file("${path.module}/../backend/shared/db.py")
    filename = "shared/db.py"
  }
  source {
    content  = file("${path.module}/../backend/shared/logger.py")
    filename = "shared/logger.py"
  }
  source {
    content  = file("${path.module}/../backend/shared/response.py")
    filename = "shared/response.py"
  }
  source {
    content  = file("${path.module}/../backend/shared/s3_helper.py")
    filename = "shared/s3_helper.py"
  }
}

resource "aws_lambda_function" "status_service" {
  #checkov:skip=CKV_AWS_117:No VPC resources to reach; a VPC would require a paid NAT gateway for Groq/GitHub egress.
  #checkov:skip=CKV_AWS_173:Env vars hold only resource names / SSM parameter names, no secrets; CMK costs money.
  #checkov:skip=CKV_AWS_115:New accounts have a 10-concurrency quota; reserving concurrency can fail the deploy.
  #checkov:skip=CKV_AWS_50:X-Ray PutTraceSegments only supports Resource "*", which conflicts with the no-wildcard IAM rule.
  #checkov:skip=CKV_AWS_272:Code signing is out of scope for this project.
  #checkov:skip=CKV_AWS_116:Synchronous/stream invocations; failed SQS messages go to the queue-level DLQ.
  function_name    = "idp-status-service"
  role             = aws_iam_role.lambda["status_service"].arn
  filename         = data.archive_file.status_service.output_path
  source_code_hash = data.archive_file.status_service.output_base64sha256
  runtime          = "python3.12"
  depends_on       = [aws_iam_role_policy.lambda, aws_cloudwatch_log_group.lambda]
  handler          = "handler.handler"
  timeout          = 30
  memory_size      = 256
  environment { variables = local.common_env }
}

# ─── validation_service ───────────────────────────────────────────────────────
data "archive_file" "validation_service" {
  type        = "zip"
  output_path = "${path.module}/builds/validation_service.zip"

  source {
    content  = file("${path.module}/../backend/validation_service/handler.py")
    filename = "handler.py"
  }
  source {
    content  = file("${path.module}/../backend/validation_service/rules.py")
    filename = "rules.py"
  }
  source {
    content  = file("${path.module}/../backend/validation_service/ast_engine.py")
    filename = "ast_engine.py"
  }
  source {
    content  = file("${path.module}/../backend/validation_service/security_scanner.py")
    filename = "security_scanner.py"
  }
  source {
    content  = file("${path.module}/../backend/validation_service/manifest_rules.py")
    filename = "manifest_rules.py"
  }
  source {
    content  = file("${path.module}/../backend/shared/__init__.py")
    filename = "shared/__init__.py"
  }
  source {
    content  = file("${path.module}/../backend/shared/db.py")
    filename = "shared/db.py"
  }
  source {
    content  = file("${path.module}/../backend/shared/logger.py")
    filename = "shared/logger.py"
  }
  source {
    content  = file("${path.module}/../backend/shared/response.py")
    filename = "shared/response.py"
  }
  source {
    content  = file("${path.module}/../backend/shared/s3_helper.py")
    filename = "shared/s3_helper.py"
  }
}

resource "aws_lambda_function" "validation_service" {
  #checkov:skip=CKV_AWS_117:No VPC resources to reach; a VPC would require a paid NAT gateway for Groq/GitHub egress.
  #checkov:skip=CKV_AWS_173:Env vars hold only resource names / SSM parameter names, no secrets; CMK costs money.
  #checkov:skip=CKV_AWS_115:New accounts have a 10-concurrency quota; reserving concurrency can fail the deploy.
  #checkov:skip=CKV_AWS_50:X-Ray PutTraceSegments only supports Resource "*", which conflicts with the no-wildcard IAM rule.
  #checkov:skip=CKV_AWS_272:Code signing is out of scope for this project.
  #checkov:skip=CKV_AWS_116:Synchronous/stream invocations; failed SQS messages go to the queue-level DLQ.
  function_name    = "idp-validation-service"
  role             = aws_iam_role.lambda["validation_service"].arn
  filename         = data.archive_file.validation_service.output_path
  source_code_hash = data.archive_file.validation_service.output_base64sha256
  runtime          = "python3.12"
  depends_on       = [aws_iam_role_policy.lambda, aws_cloudwatch_log_group.lambda]
  handler          = "handler.handler"
  timeout          = 30
  memory_size      = 256
  environment { variables = local.common_env }
}

# ─── download_service ─────────────────────────────────────────────────────────
data "archive_file" "download_service" {
  type        = "zip"
  output_path = "${path.module}/builds/download_service.zip"

  source {
    content  = file("${path.module}/../backend/download_service/handler.py")
    filename = "handler.py"
  }
  source {
    content  = file("${path.module}/../backend/shared/__init__.py")
    filename = "shared/__init__.py"
  }
  source {
    content  = file("${path.module}/../backend/shared/db.py")
    filename = "shared/db.py"
  }
  source {
    content  = file("${path.module}/../backend/shared/logger.py")
    filename = "shared/logger.py"
  }
  source {
    content  = file("${path.module}/../backend/shared/response.py")
    filename = "shared/response.py"
  }
  source {
    content  = file("${path.module}/../backend/shared/s3_helper.py")
    filename = "shared/s3_helper.py"
  }
}

resource "aws_lambda_function" "download_service" {
  #checkov:skip=CKV_AWS_117:No VPC resources to reach; a VPC would require a paid NAT gateway for Groq/GitHub egress.
  #checkov:skip=CKV_AWS_173:Env vars hold only resource names / SSM parameter names, no secrets; CMK costs money.
  #checkov:skip=CKV_AWS_115:New accounts have a 10-concurrency quota; reserving concurrency can fail the deploy.
  #checkov:skip=CKV_AWS_50:X-Ray PutTraceSegments only supports Resource "*", which conflicts with the no-wildcard IAM rule.
  #checkov:skip=CKV_AWS_272:Code signing is out of scope for this project.
  #checkov:skip=CKV_AWS_116:Synchronous/stream invocations; failed SQS messages go to the queue-level DLQ.
  function_name    = "idp-download-service"
  role             = aws_iam_role.lambda["download_service"].arn
  filename         = data.archive_file.download_service.output_path
  source_code_hash = data.archive_file.download_service.output_base64sha256
  runtime          = "python3.12"
  depends_on       = [aws_iam_role_policy.lambda, aws_cloudwatch_log_group.lambda]
  handler          = "handler.handler"
  timeout          = 30
  memory_size      = 256
  environment { variables = local.common_env }
}

# ─── generation_orchestrator (SQS-triggered) ──────────────────────────────────
data "archive_file" "generation_orchestrator" {
  type        = "zip"
  output_path = "${path.module}/builds/generation_orchestrator.zip"

  source {
    content  = file("${path.module}/../backend/generation_orchestrator/handler.py")
    filename = "handler.py"
  }
  source {
    content  = file("${path.module}/../backend/generation_orchestrator/artifact_assembler.py")
    filename = "artifact_assembler.py"
  }
  source {
    content  = file("${path.module}/../backend/generation_orchestrator/prompt_builder.py")
    filename = "prompt_builder.py"
  }
  source {
    content  = file("${path.module}/../backend/generation_orchestrator/llm_client.py")
    filename = "llm_client.py"
  }
  source {
    content  = file("${path.module}/../backend/generation_orchestrator/guardrails.py")
    filename = "guardrails.py"
  }
  source {
    content  = file("${path.module}/../backend/generation_orchestrator/finops.py")
    filename = "finops.py"
  }

  source {
    content  = file("${path.module}/../backend/generation_orchestrator/golden_paths/__init__.py")
    filename = "golden_paths/__init__.py"
  }
  source {
    content  = file("${path.module}/../backend/generation_orchestrator/golden_paths/python_fastapi.py")
    filename = "golden_paths/python_fastapi.py"
  }
  source {
    content  = file("${path.module}/../backend/generation_orchestrator/golden_paths/typescript_express.py")
    filename = "golden_paths/typescript_express.py"
  }
  source {
    content  = file("${path.module}/../backend/generation_orchestrator/golden_paths/go_gin.py")
    filename = "golden_paths/go_gin.py"
  }

  source {
    content  = file("${path.module}/../backend/validation_service/rules.py")
    filename = "rules.py"
  }
  source {
    content  = file("${path.module}/../backend/validation_service/ast_engine.py")
    filename = "validation_service/ast_engine.py"
  }
  source {
    content  = file("${path.module}/../backend/validation_service/security_scanner.py")
    filename = "validation_service/security_scanner.py"
  }
  source {
    content  = file("${path.module}/../backend/validation_service/manifest_rules.py")
    filename = "validation_service/manifest_rules.py"
  }

  source {
    content  = file("${path.module}/../backend/shared/lineage.py")
    filename = "shared/lineage.py"
  }
  source {
    content  = file("${path.module}/../backend/policy_service/parser.py")
    filename = "parser.py"
  }
  source {
    content  = file("${path.module}/../backend/policy_service/defaults.py")
    filename = "defaults.py"
  }
  source {
    content  = file("${path.module}/../backend/shared/__init__.py")
    filename = "shared/__init__.py"
  }
  source {
    content  = file("${path.module}/../backend/shared/db.py")
    filename = "shared/db.py"
  }
  source {
    content  = file("${path.module}/../backend/shared/logger.py")
    filename = "shared/logger.py"
  }
  source {
    content  = file("${path.module}/../backend/shared/response.py")
    filename = "shared/response.py"
  }
  source {
    content  = file("${path.module}/../backend/shared/s3_helper.py")
    filename = "shared/s3_helper.py"
  }
  source {
    content  = file("${path.module}/../backend/shared/secrets.py")
    filename = "shared/secrets.py"
  }
}

resource "aws_lambda_function" "generation_orchestrator" {
  #checkov:skip=CKV_AWS_117:No VPC resources to reach; a VPC would require a paid NAT gateway for Groq/GitHub egress.
  #checkov:skip=CKV_AWS_173:Env vars hold only resource names / SSM parameter names, no secrets; CMK costs money.
  #checkov:skip=CKV_AWS_115:New accounts have a 10-concurrency quota; reserving concurrency can fail the deploy.
  #checkov:skip=CKV_AWS_50:X-Ray PutTraceSegments only supports Resource "*", which conflicts with the no-wildcard IAM rule.
  #checkov:skip=CKV_AWS_272:Code signing is out of scope for this project.
  #checkov:skip=CKV_AWS_116:Synchronous/stream invocations; failed SQS messages go to the queue-level DLQ.
  function_name    = "idp-generation-orchestrator"
  role             = aws_iam_role.lambda["generation_orchestrator"].arn
  filename         = data.archive_file.generation_orchestrator.output_path
  source_code_hash = data.archive_file.generation_orchestrator.output_base64sha256
  runtime          = "python3.12"
  depends_on       = [aws_iam_role_policy.lambda, aws_cloudwatch_log_group.lambda]
  handler          = "handler.handler"
  timeout          = var.orchestrator_timeout_seconds
  memory_size      = 512

  environment {
    variables = merge(local.common_env, {
      GROQ_API_KEY_PARAM      = aws_ssm_parameter.groq_api_key.name
      GROQ_MODEL              = var.groq_model
      GROQ_MAX_TOKENS         = tostring(var.groq_max_tokens)
      ENABLE_BEDROCK_FALLBACK = tostring(var.enable_bedrock_fallback)
      BEDROCK_FALLBACK_MODEL  = var.bedrock_fallback_model
    })
  }
}

resource "aws_lambda_event_source_mapping" "sqs_to_orchestrator" {
  event_source_arn = aws_sqs_queue.generation.arn
  function_name    = aws_lambda_function.generation_orchestrator.arn
  batch_size       = 1
  enabled          = true

  # Free-tier Groq allows ~30 req/min; never fan out more than 2 generations.
  scaling_config {
    maximum_concurrency = 2
  }
}

# ─── audit_service (Phase 4) ──────────────────────────────────────────────────
data "archive_file" "audit_service" {
  type        = "zip"
  output_path = "${path.module}/builds/audit_service.zip"

  source {
    content  = file("${path.module}/../backend/audit_service/handler.py")
    filename = "handler.py"
  }
  source {
    content  = file("${path.module}/../backend/shared/__init__.py")
    filename = "shared/__init__.py"
  }
  source {
    content  = file("${path.module}/../backend/shared/logger.py")
    filename = "shared/logger.py"
  }
}

resource "aws_lambda_function" "audit_service" {
  #checkov:skip=CKV_AWS_117:No VPC resources to reach; a VPC would require a paid NAT gateway for Groq/GitHub egress.
  #checkov:skip=CKV_AWS_173:Env vars hold only resource names / SSM parameter names, no secrets; CMK costs money.
  #checkov:skip=CKV_AWS_115:New accounts have a 10-concurrency quota; reserving concurrency can fail the deploy.
  #checkov:skip=CKV_AWS_50:X-Ray PutTraceSegments only supports Resource "*", which conflicts with the no-wildcard IAM rule.
  #checkov:skip=CKV_AWS_272:Code signing is out of scope for this project.
  #checkov:skip=CKV_AWS_116:Synchronous/stream invocations; failed SQS messages go to the queue-level DLQ.
  function_name    = "idp-audit-service"
  role             = aws_iam_role.lambda["audit_service"].arn
  filename         = data.archive_file.audit_service.output_path
  source_code_hash = data.archive_file.audit_service.output_base64sha256
  runtime          = "python3.12"
  depends_on       = [aws_iam_role_policy.lambda, aws_cloudwatch_log_group.lambda]
  handler          = "handler.handler"
  timeout          = 30
  memory_size      = 256

  environment {
    variables = merge(local.common_env, {
      AUDIT_VAULT_BUCKET = aws_s3_bucket.audit_vault.bucket
    })
  }
}

# ─── provisioning_service (Phase 5) ───────────────────────────────────────────
data "archive_file" "provisioning_service" {
  type        = "zip"
  output_path = "${path.module}/builds/provisioning_service.zip"

  source {
    content  = file("${path.module}/../backend/provisioning_service/handler.py")
    filename = "handler.py"
  }
  source {
    content  = file("${path.module}/../backend/provisioning_service/github_client.py")
    filename = "github_client.py"
  }
  source {
    content  = file("${path.module}/../backend/shared/__init__.py")
    filename = "shared/__init__.py"
  }
  source {
    content  = file("${path.module}/../backend/shared/db.py")
    filename = "shared/db.py"
  }
  source {
    content  = file("${path.module}/../backend/shared/logger.py")
    filename = "shared/logger.py"
  }
  source {
    content  = file("${path.module}/../backend/shared/response.py")
    filename = "shared/response.py"
  }
  source {
    content  = file("${path.module}/../backend/shared/secrets.py")
    filename = "shared/secrets.py"
  }
}

resource "aws_lambda_function" "provisioning_service" {
  #checkov:skip=CKV_AWS_117:No VPC resources to reach; a VPC would require a paid NAT gateway for Groq/GitHub egress.
  #checkov:skip=CKV_AWS_173:Env vars hold only resource names / SSM parameter names, no secrets; CMK costs money.
  #checkov:skip=CKV_AWS_115:New accounts have a 10-concurrency quota; reserving concurrency can fail the deploy.
  #checkov:skip=CKV_AWS_50:X-Ray PutTraceSegments only supports Resource "*", which conflicts with the no-wildcard IAM rule.
  #checkov:skip=CKV_AWS_272:Code signing is out of scope for this project.
  #checkov:skip=CKV_AWS_116:Synchronous/stream invocations; failed SQS messages go to the queue-level DLQ.
  function_name    = "idp-provisioning-service"
  role             = aws_iam_role.lambda["provisioning_service"].arn
  filename         = data.archive_file.provisioning_service.output_path
  source_code_hash = data.archive_file.provisioning_service.output_base64sha256
  runtime          = "python3.12"
  depends_on       = [aws_iam_role_policy.lambda, aws_cloudwatch_log_group.lambda]
  handler          = "handler.handler"
  timeout          = 60 # GitHub API interactions may take a few seconds
  memory_size      = 256

  environment {
    variables = merge(local.common_env, {
      GITHUB_TOKEN_PARAM = aws_ssm_parameter.github_token.name
    })
  }
}

# ─── API Gateway invoke permissions ───────────────────────────────────────────
resource "aws_lambda_permission" "apigw_policy" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.policy_service.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.main.execution_arn}/*"
}

resource "aws_lambda_permission" "apigw_validation" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.validation_service.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.main.execution_arn}/*"
}

resource "aws_lambda_permission" "apigw_provisioning" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.provisioning_service.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.main.execution_arn}/*"
}
resource "aws_lambda_permission" "apigw_status" {
  statement_id  = "AllowAPIGatewayInvokeStatus"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.status_service.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.main.execution_arn}/*"
}

resource "aws_lambda_permission" "apigw_download" {
  statement_id  = "AllowAPIGatewayInvokeDownload"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.download_service.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.main.execution_arn}/*"
}