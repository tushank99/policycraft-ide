variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "us-east-1"
}

variable "groq_api_key" {
  description = "Groq API key (free at console.groq.com). Stored in SSM Parameter Store, not in Lambda env."
  type        = string
  sensitive   = true
}

variable "github_token" {
  description = "GitHub Personal Access Token for provisioning repositories. Stored in SSM Parameter Store."
  type        = string
  sensitive   = true
  default     = "unset"
}

variable "groq_model" {
  description = "Groq model id. Use a non-reasoning model; reasoning models can exhaust max_tokens inside <think> and produce no files."
  type        = string
  default     = "llama-3.3-70b-versatile"
}

variable "groq_max_tokens" {
  description = "Max output tokens per generation call."
  type        = number
  default     = 8000
}

variable "orchestrator_timeout_seconds" {
  description = "Generation Lambda timeout. Must cover up to 2 LLM calls + 1 repair pass with retries."
  type        = number
  default     = 600
}

variable "enable_bedrock_fallback" {
  description = "Bedrock has NO free tier. Keep false to stay free."
  type        = bool
  default     = false
}

variable "bedrock_fallback_model" {
  description = "Bedrock model used only when enable_bedrock_fallback = true"
  type        = string
  default     = "meta.llama3-70b-instruct-v1:0"
}

variable "enable_api_auth" {
  description = "Require a Cognito JWT on every API route."
  type        = bool
  default     = true
}

variable "audit_retention_days" {
  description = "Object Lock (GOVERNANCE) retention for audit manifests."
  type        = number
  default     = 30
}

# ─── P3: security monitoring (CloudTrail -> CloudWatch -> SNS) ───────────────
variable "enable_security_monitoring" {
  description = "Create CloudTrail + metric filters + alarms. The first management-event trail per account is free."
  type        = bool
  default     = false
}

variable "alert_email" {
  description = "Email address subscribed to the security alarm SNS topic (confirm the subscription email)."
  type        = string
  default     = ""
}
