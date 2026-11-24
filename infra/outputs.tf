output "api_url" {
  description = "Base URL for the API Gateway — set this as VITE_API_URL in the frontend"
  value       = aws_apigatewayv2_stage.default.invoke_url
}

output "s3_bucket" {
  description = "S3 bucket where generated ZIPs are stored"
  value       = aws_s3_bucket.artifacts.bucket
}

output "dynamodb_table" {
  description = "DynamoDB table name"
  value       = aws_dynamodb_table.idp.name
}

output "sqs_queue_url" {
  description = "SQS queue URL for the generation orchestrator"
  value       = aws_sqs_queue.generation.url
}

output "sqs_dlq_url" {
  description = "Dead-letter queue for generation jobs that failed twice"
  value       = aws_sqs_queue.generation_dlq.url
}

output "frontend_bucket" {
  description = "Private S3 bucket — upload the built dist/ folder here"
  value       = aws_s3_bucket.frontend.bucket
}

output "cloudfront_distribution_id" {
  description = "CloudFront distribution id (for cache invalidation after deploys)"
  value       = aws_cloudfront_distribution.frontend.id
}

output "frontend_url" {
  description = "Frontend URL (HTTPS via CloudFront)"
  value       = "https://${aws_cloudfront_distribution.frontend.domain_name}"
}

output "cognito_user_pool_id" {
  value = aws_cognito_user_pool.main.id
}

output "cognito_client_id" {
  description = "VITE_COGNITO_CLIENT_ID"
  value       = aws_cognito_user_pool_client.frontend.id
}

output "cognito_domain" {
  description = "VITE_COGNITO_DOMAIN"
  value       = "https://${aws_cognito_user_pool_domain.main.domain}.auth.${var.aws_region}.amazoncognito.com"
}

output "security_alerts_topic_arn" {
  description = "SNS topic for security alarms (null when monitoring is disabled)"
  value       = var.enable_security_monitoring ? aws_sns_topic.security_alerts[0].arn : null
}
