terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.0"
    }
  }
}

provider "aws" {
  region = "us-east-1"
}

# ─── Current account identity ─────────────────────────────────────────────────
data "aws_caller_identity" "current" {}
data "aws_iam_role" "lab_role" {
  name = "LabRole"
}

locals {
  account_id  = data.aws_caller_identity.current.account_id
  bucket_name = "idp-artifacts-${local.account_id}"
  table_name  = "idp-table"
  queue_name  = "idp-generation-queue"
}

# ─── DynamoDB ─────────────────────────────────────────────────────────────────
resource "aws_dynamodb_table" "idp" {
  name           = local.table_name
  billing_mode   = "PAY_PER_REQUEST"
  hash_key       = "PK"
  range_key      = "SK"

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

  # Phase 4 Additions: Enable Streams for EventBridge
  stream_enabled   = true
  stream_view_type = "NEW_AND_OLD_IMAGES"
}

# ─── S3 (Artifacts & Audit Vault) ─────────────────────────────────────────────
resource "aws_s3_bucket" "artifacts" {
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

# Phase 4 Addition: WORM S3 Audit Vault
resource "aws_s3_bucket" "audit_vault" {
  bucket              = "idp-audit-vault-${local.account_id}"
  force_destroy       = true
  object_lock_enabled = true
}

resource "aws_s3_bucket_object_lock_configuration" "audit_vault_lock" {
  bucket = aws_s3_bucket.audit_vault.id
  rule {
    default_retention {
      mode = "GOVERNANCE"
      days = 90
    }
  }
}

# ─── SQS ──────────────────────────────────────────────────────────────────────
resource "aws_sqs_queue" "generation" {
  name                       = local.queue_name
  visibility_timeout_seconds = 360
  message_retention_seconds  = 3600
}

# ─── EventBridge Pipe (Phase 4) ───────────────────────────────────────────────
resource "aws_pipes_pipe" "audit_stream_pipe" {
  name     = "idp-audit-stream-pipe"
  role_arn = data.aws_iam_role.lab_role.arn
  
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