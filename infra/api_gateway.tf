# ─── HTTP API ─────────────────────────────────────────────────────────────────

resource "aws_apigatewayv2_api" "main" {
  name          = "idp-api"
  protocol_type = "HTTP"

  # Only the real frontend origins (was "*").
  cors_configuration {
    allow_origins = ["https://${aws_cloudfront_distribution.frontend.domain_name}", "http://localhost:5173"]
    allow_methods = ["GET", "POST", "PUT", "DELETE", "OPTIONS"]
    allow_headers = ["Content-Type", "Authorization"]
    max_age       = 300
  }
}

# Access logs: required for the "failed API auth" alarm in monitoring.tf.
resource "aws_cloudwatch_log_group" "api_access" {
  #checkov:skip=CKV_AWS_158:Log encryption with a CMK costs money; CloudWatch encrypts logs at rest by default.
  #checkov:skip=CKV_AWS_338:1-year retention exceeds the 5 GB free tier; 14 days is enough for this project.
  name              = "/aws/apigateway/idp-api"
  retention_in_days = 14
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.main.id
  name        = "$default"
  auto_deploy = true

  # Throttling caps "denial-of-wallet" against the LLM pipeline.
  default_route_settings {
    throttling_burst_limit = 20
    throttling_rate_limit  = 10
  }

  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.api_access.arn
    format = jsonencode({
      requestId      = "$context.requestId"
      ip             = "$context.identity.sourceIp"
      httpMethod     = "$context.httpMethod"
      routeKey       = "$context.routeKey"
      status         = "$context.status"
      authError      = "$context.authorizer.error"
      responseLength = "$context.responseLength"
      requestTime    = "$context.requestTime"
    })
  }
}

# ─── JWT authorizer (Cognito) ─────────────────────────────────────────────────
resource "aws_apigatewayv2_authorizer" "cognito" {
  api_id           = aws_apigatewayv2_api.main.id
  name             = "cognito-jwt"
  authorizer_type  = "JWT"
  identity_sources = ["$request.header.Authorization"]

  jwt_configuration {
    issuer   = "https://cognito-idp.${var.aws_region}.amazonaws.com/${aws_cognito_user_pool.main.id}"
    audience = [aws_cognito_user_pool_client.frontend.id]
  }
}

# ─── Integrations (one per Lambda) ────────────────────────────────────────────
locals {
  api_integrations = {
    policy       = aws_lambda_function.policy_service.invoke_arn
    status       = aws_lambda_function.status_service.invoke_arn
    validation   = aws_lambda_function.validation_service.invoke_arn
    download     = aws_lambda_function.download_service.invoke_arn
    provisioning = aws_lambda_function.provisioning_service.invoke_arn
  }

  # route key -> integration
  api_routes = {
    "GET /policies"                 = "policy"
    "PUT /policies"                 = "policy"
    "GET /policies/defaults"        = "policy"
    "POST /requests"                = "status"
    "GET /requests"                 = "status"
    "GET /requests/{id}"            = "status"
    "GET /requests/{id}/status"     = "status"
    "GET /requests/{id}/plan"       = "status"
    "POST /requests/{id}/generate"  = "status"
    "GET /requests/{id}/validation" = "validation"
    "GET /requests/{id}/download"   = "download"
    "POST /requests/{id}/provision" = "provisioning"
  }
}

resource "aws_apigatewayv2_integration" "lambda" {
  for_each               = local.api_integrations
  api_id                 = aws_apigatewayv2_api.main.id
  integration_type       = "AWS_PROXY"
  integration_uri        = each.value
  payload_format_version = "1.0"
}

resource "aws_apigatewayv2_route" "routes" {
  for_each  = local.api_routes
  api_id    = aws_apigatewayv2_api.main.id
  route_key = each.key
  target    = "integrations/${aws_apigatewayv2_integration.lambda[each.value].id}"

  authorization_type = var.enable_api_auth ? "JWT" : "NONE"
  authorizer_id      = var.enable_api_auth ? aws_apigatewayv2_authorizer.cognito.id : null
}
