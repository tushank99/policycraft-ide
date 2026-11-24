# ─── Least-privilege IAM: one role per Lambda ────────────────────────────────
# Replaces the single shared role that had AdministratorAccess ("*" on "*").
# Policy documents live in infra/policies/*.json.tftpl so CI can render them
# and run IAM Access Analyzer validate-policy without a Terraform plan
# (see scripts/validate_iam_policies.py).

locals {
  lambda_services = toset([
    "policy_service",
    "status_service",
    "validation_service",
    "download_service",
    "generation_orchestrator",
    "audit_service",
    "provisioning_service",
  ])

  # Every value a policy template may reference. Templates only use the keys they need.
  policy_vars = {
    table_arn            = aws_dynamodb_table.idp.arn
    queue_arn            = aws_sqs_queue.generation.arn
    artifacts_bucket_arn = aws_s3_bucket.artifacts.arn
    vault_bucket_arn     = aws_s3_bucket.audit_vault.arn
    groq_param_arn       = aws_ssm_parameter.groq_api_key.arn
    github_param_arn     = aws_ssm_parameter.github_token.arn
    bedrock_model_arn    = local.bedrock_model_arn
  }
}

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }
  }
}

resource "aws_iam_role" "lambda" {
  for_each           = local.lambda_services
  name               = "idp-${replace(each.key, "_", "-")}-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

resource "aws_iam_role_policy" "lambda" {
  for_each = local.lambda_services
  name     = "least-privilege"
  role     = aws_iam_role.lambda[each.key].id
  policy = templatefile("${path.module}/policies/${each.key}.json.tftpl", merge(local.policy_vars, {
    log_group_arn = aws_cloudwatch_log_group.lambda[each.key].arn
  }))
}

# ─── EventBridge Pipe role (stream -> audit Lambda) ──────────────────────────
data "aws_iam_policy_document" "pipes_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["pipes.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }
  }
}

resource "aws_iam_role" "audit_pipe" {
  name               = "idp-audit-pipe-role"
  assume_role_policy = data.aws_iam_policy_document.pipes_assume.json
}

resource "aws_iam_role_policy" "audit_pipe" {
  name = "least-privilege"
  role = aws_iam_role.audit_pipe.id
  policy = templatefile("${path.module}/policies/audit_pipe.json.tftpl", {
    stream_arn         = aws_dynamodb_table.idp.stream_arn
    audit_function_arn = aws_lambda_function.audit_service.arn
  })
}
