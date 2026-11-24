terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.73"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.0"
    }
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project   = "policycraft"
      ManagedBy = "terraform"
    }
  }
}

data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}

locals {
  account_id  = data.aws_caller_identity.current.account_id
  partition   = data.aws_partition.current.partition
  bucket_name = "idp-artifacts-${local.account_id}"
  table_name  = "idp-table"
  queue_name  = "idp-generation-queue"

  # Free-tier note: every "KMS" setting below uses the AWS-managed keys
  # (aws/s3, aws/dynamodb, aws/ssm). They have no monthly fee; a customer
  # managed key would cost ~$1/month each.
  bedrock_model_arn = "arn:${local.partition}:bedrock:${var.aws_region}::foundation-model/${var.bedrock_fallback_model}"
}

# ─── DynamoDB ─────────────────────────────────────────────────────────────────
resource "aws_dynamodb_table" "idp" {
  #checkov:skip=CKV_AWS_119:Customer-managed CMK costs $1/month; SSE uses the free AWS-managed aws/dynamodb KMS key.
  #checkov:skip=CKV_AWS_28:Point-in-time recovery is billed per GB-month; out of scope for free tier.
  name         = local.table_name
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "PK"
  range_key    = "SK"

  attribute {
    name = "PK"
    type = "S"
  }
  attribute {
    name = "SK"
    type = "S"
  }
  attribute {
    name = "GSI1PK"
    type = "S"
  }
  attribute {
    name = "GSI1SK"
    type = "S"
  }

  global_secondary_index {
    name            = "GSI1"
    hash_key        = "GSI1PK"
    range_key       = "GSI1SK"
    projection_type = "ALL"
  }

  # SSE-KMS with the AWS-managed key (no kms_key_arn = aws/dynamodb).
  server_side_encryption {
    enabled = true
  }

  stream_enabled   = true
  stream_view_type = "NEW_AND_OLD_IMAGES"
}

# ─── S3: generated artifacts ──────────────────────────────────────────────────
resource "aws_s3_bucket" "artifacts" {
  #checkov:skip=CKV_AWS_18:Access logging would need another bucket and adds cost; CloudTrail covers API activity.
  #checkov:skip=CKV_AWS_144:Cross-region replication is not free-tier.
  #checkov:skip=CKV2_AWS_62:Event notifications are not required for this bucket.
  bucket        = local.bucket_name
  force_destroy = true
}

resource "aws_s3_bucket_public_access_block" "artifacts" {
  bucket                  = aws_s3_bucket.artifacts.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "artifacts" {
  #checkov:skip=CKV_AWS_145:Uses SSE-KMS with the AWS-managed aws/s3 key (free) instead of a paid CMK.
  bucket = aws_s3_bucket.artifacts.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "aws:kms"
    }
    bucket_key_enabled = true # fewer KMS requests -> stays inside the 20k/month free tier
  }
}

resource "aws_s3_bucket_versioning" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "artifacts" {
  #checkov:skip=CKV_AWS_300:abort_incomplete_multipart_upload is set on the generated/ rule, the only prefix ever written.
  bucket = aws_s3_bucket.artifacts.id
  rule {
    id     = "expire-generated-zips"
    status = "Enabled"
    filter {
      prefix = "generated/"
    }
    expiration {
      days = 7
    }
    noncurrent_version_expiration {
      noncurrent_days = 1
    }
    abort_incomplete_multipart_upload {
      days_after_initiation = 1
    }
  }
}

resource "aws_s3_bucket_policy" "artifacts_tls_only" {
  bucket = aws_s3_bucket.artifacts.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "DenyInsecureTransport"
      Effect    = "Deny"
      Principal = { AWS = "*" }
      Action    = "s3:*"
      Resource  = [aws_s3_bucket.artifacts.arn, "${aws_s3_bucket.artifacts.arn}/*"]
      Condition = { Bool = { "aws:SecureTransport" = "false" } }
    }]
  })
  depends_on = [aws_s3_bucket_public_access_block.artifacts]
}

# ─── S3: WORM audit vault ─────────────────────────────────────────────────────
resource "aws_s3_bucket" "audit_vault" {
  #checkov:skip=CKV_AWS_18:Access logging would need another bucket and adds cost; CloudTrail covers API activity.
  #checkov:skip=CKV_AWS_144:Cross-region replication is not free-tier.
  #checkov:skip=CKV2_AWS_62:Event notifications are not required for this bucket.
  #checkov:skip=CKV2_AWS_61:Lifecycle would conflict with the Object Lock retention for the audit trail.
  bucket              = "idp-audit-vault-${local.account_id}"
  force_destroy       = true
  object_lock_enabled = true
}

resource "aws_s3_bucket_public_access_block" "audit_vault" {
  bucket                  = aws_s3_bucket.audit_vault.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "audit_vault" {
  #checkov:skip=CKV_AWS_145:Uses SSE-KMS with the AWS-managed aws/s3 key (free) instead of a paid CMK.
  bucket = aws_s3_bucket.audit_vault.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "aws:kms"
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_versioning" "audit_vault" {
  bucket = aws_s3_bucket.audit_vault.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_object_lock_configuration" "audit_vault_lock" {
  bucket = aws_s3_bucket.audit_vault.id
  rule {
    default_retention {
      mode = "GOVERNANCE"
      days = var.audit_retention_days
    }
  }
}

# ─── SQS (+ dead-letter queue so a poison message can't loop forever) ─────────
resource "aws_sqs_queue" "generation_dlq" {
  name                      = "${local.queue_name}-dlq"
  message_retention_seconds = 1209600
  sqs_managed_sse_enabled   = true
}

resource "aws_sqs_queue" "generation" {
  name = local.queue_name
  # AWS guidance: visibility timeout >= 6x the consumer Lambda timeout.
  visibility_timeout_seconds = 6 * var.orchestrator_timeout_seconds
  message_retention_seconds  = 86400
  sqs_managed_sse_enabled    = true

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.generation_dlq.arn
    maxReceiveCount     = 2
  })
}

# ─── Secrets in SSM Parameter Store (Standard tier = free) ────────────────────
# Previously the Groq key / GitHub PAT were plain Lambda environment variables.
resource "aws_ssm_parameter" "groq_api_key" {
  #checkov:skip=CKV_AWS_337:SecureString uses the free AWS-managed aws/ssm key instead of a paid CMK.
  name  = "/policycraft/groq_api_key"
  type  = "SecureString"
  value = var.groq_api_key
}

resource "aws_ssm_parameter" "github_token" {
  #checkov:skip=CKV_AWS_337:SecureString uses the free AWS-managed aws/ssm key instead of a paid CMK.
  name  = "/policycraft/github_token"
  type  = "SecureString"
  value = var.github_token
}

# ─── EventBridge Pipe: DynamoDB stream -> audit Lambda ───────────────────────
resource "aws_pipes_pipe" "audit_stream_pipe" {
  name     = "idp-audit-stream-pipe"
  role_arn = aws_iam_role.audit_pipe.arn
  source   = aws_dynamodb_table.idp.stream_arn
  target   = aws_lambda_function.audit_service.arn

  source_parameters {
    dynamodb_stream_parameters {
      starting_position      = "LATEST"
      batch_size             = 10
      maximum_retry_attempts = 3
    }
    filter_criteria {
      filter {
        pattern = jsonencode({
          eventName = ["INSERT", "MODIFY"]
          dynamodb = {
            NewImage = {
              status = {
                S = ["COMPLETED", "FAILED"]
              }
            }
          }
        })
      }
    }
  }
}
