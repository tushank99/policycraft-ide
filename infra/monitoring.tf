# ─── P3: Security monitoring ──────────────────────────────────────────────────
# CloudTrail (management events) -> CloudWatch Logs -> metric filters -> alarms -> SNS email.
#
# Free-tier notes:
#   * The FIRST copy of management events per region is free. If the account
#     already has a trail, this one is a second copy (~$2 per 100k events).
#   * CloudWatch: 5 GB log ingest, 10 alarms, 10 custom metrics free.
#   * GuardDuty is intentionally NOT enabled (paid).
# Toggle with -var enable_security_monitoring=true, then set it back to false
# (or `terraform destroy -target=...`) after scripts/trigger_security_alarms.sh.

locals {
  mon       = var.enable_security_monitoring ? 1 : 0
  trail_arn = "arn:${local.partition}:cloudtrail:${var.aws_region}:${local.account_id}:trail/policycraft-security-trail"

  security_alarms = {
    iam_policy_changes = {
      log_group   = "trail"
      description = "IAM policy was created, changed, attached or deleted (CIS 4.4)"
      pattern     = "{($.eventSource=iam.amazonaws.com) && (($.eventName=DeleteGroupPolicy) || ($.eventName=DeleteRolePolicy) || ($.eventName=DeleteUserPolicy) || ($.eventName=PutGroupPolicy) || ($.eventName=PutRolePolicy) || ($.eventName=PutUserPolicy) || ($.eventName=CreatePolicy) || ($.eventName=DeletePolicy) || ($.eventName=CreatePolicyVersion) || ($.eventName=DeletePolicyVersion) || ($.eventName=SetDefaultPolicyVersion) || ($.eventName=AttachRolePolicy) || ($.eventName=DetachRolePolicy) || ($.eventName=AttachUserPolicy) || ($.eventName=DetachUserPolicy) || ($.eventName=AttachGroupPolicy) || ($.eventName=DetachGroupPolicy))}"
    }
    unauthorized_api_calls = {
      log_group   = "trail"
      description = "AWS API call was denied: AccessDenied / UnauthorizedOperation (CIS 4.1)"
      pattern     = "{($.errorCode=\"*UnauthorizedOperation\") || ($.errorCode=\"AccessDenied*\")}"
    }
    failed_api_auth = {
      log_group   = "api"
      description = "PolicyCraft API rejected a request at the JWT authorizer (401/403)"
      pattern     = "{($.status=\"401\") || ($.status=\"403\")}"
    }
  }
}

# ─── SNS topic for alerts ─────────────────────────────────────────────────────
resource "aws_sns_topic" "security_alerts" {
  #checkov:skip=CKV_AWS_26:CloudWatch alarms cannot publish to topics encrypted with the AWS-managed aws/sns key; a CMK costs money.
  count = local.mon
  name  = "policycraft-security-alerts"
}

resource "aws_sns_topic_subscription" "security_email" {
  count     = var.enable_security_monitoring && var.alert_email != "" ? 1 : 0
  topic_arn = aws_sns_topic.security_alerts[0].arn
  protocol  = "email"
  endpoint  = var.alert_email
}

# ─── CloudTrail bucket ───────────────────────────────────────────────────────
resource "aws_s3_bucket" "cloudtrail" {
  #checkov:skip=CKV_AWS_18:Access logging would need another bucket and adds cost.
  #checkov:skip=CKV_AWS_144:Cross-region replication is not free-tier.
  #checkov:skip=CKV2_AWS_62:Event notifications are not required.
  #checkov:skip=CKV_AWS_21:Lifecycle expiry handles retention; versioning only adds storage.
  count         = local.mon
  bucket        = "policycraft-cloudtrail-${local.account_id}"
  force_destroy = true
}

resource "aws_s3_bucket_public_access_block" "cloudtrail" {
  count                   = local.mon
  bucket                  = aws_s3_bucket.cloudtrail[0].id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "cloudtrail" {
  #checkov:skip=CKV_AWS_145:Uses SSE-KMS with the AWS-managed aws/s3 key (free).
  count  = local.mon
  bucket = aws_s3_bucket.cloudtrail[0].id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "aws:kms"
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "cloudtrail" {
  count  = local.mon
  bucket = aws_s3_bucket.cloudtrail[0].id
  rule {
    id     = "expire-trail-logs"
    status = "Enabled"
    filter {}
    expiration {
      days = 30
    }
    abort_incomplete_multipart_upload {
      days_after_initiation = 1
    }
  }
}

resource "aws_s3_bucket_policy" "cloudtrail" {
  count  = local.mon
  bucket = aws_s3_bucket.cloudtrail[0].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "CloudTrailAclCheck"
        Effect    = "Allow"
        Principal = { Service = "cloudtrail.amazonaws.com" }
        Action    = "s3:GetBucketAcl"
        Resource  = aws_s3_bucket.cloudtrail[0].arn
        Condition = { StringEquals = { "aws:SourceArn" = local.trail_arn } }
      },
      {
        Sid       = "CloudTrailWrite"
        Effect    = "Allow"
        Principal = { Service = "cloudtrail.amazonaws.com" }
        Action    = "s3:PutObject"
        Resource  = "${aws_s3_bucket.cloudtrail[0].arn}/AWSLogs/${local.account_id}/*"
        Condition = {
          StringEquals = {
            "s3:x-amz-acl"  = "bucket-owner-full-control"
            "aws:SourceArn" = local.trail_arn
          }
        }
      },
      {
        Sid       = "DenyInsecureTransport"
        Effect    = "Deny"
        Principal = { AWS = "*" }
        Action    = "s3:*"
        Resource  = [aws_s3_bucket.cloudtrail[0].arn, "${aws_s3_bucket.cloudtrail[0].arn}/*"]
        Condition = { Bool = { "aws:SecureTransport" = "false" } }
      }
    ]
  })
  depends_on = [aws_s3_bucket_public_access_block.cloudtrail]
}

# ─── CloudTrail -> CloudWatch Logs ───────────────────────────────────────────
resource "aws_cloudwatch_log_group" "cloudtrail" {
  #checkov:skip=CKV_AWS_158:Log encryption with a CMK costs money; CloudWatch encrypts logs at rest by default.
  #checkov:skip=CKV_AWS_338:1-year retention exceeds the free tier; 14 days is enough here.
  count             = local.mon
  name              = "/aws/cloudtrail/policycraft"
  retention_in_days = 14
}

data "aws_iam_policy_document" "cloudtrail_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["cloudtrail.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceArn"
      values   = [local.trail_arn]
    }
  }
}

resource "aws_iam_role" "cloudtrail_to_cw" {
  count              = local.mon
  name               = "policycraft-cloudtrail-to-cloudwatch"
  assume_role_policy = data.aws_iam_policy_document.cloudtrail_assume.json
}

resource "aws_iam_role_policy" "cloudtrail_to_cw" {
  count = local.mon
  name  = "write-trail-log-group"
  role  = aws_iam_role.cloudtrail_to_cw[0].id
  policy = templatefile("${path.module}/policies/cloudtrail_to_cloudwatch.json.tftpl", {
    log_group_arn = aws_cloudwatch_log_group.cloudtrail[0].arn
  })
}

resource "aws_cloudtrail" "security" {
  #checkov:skip=CKV_AWS_35:SSE-KMS with a CMK costs money; the trail bucket uses SSE-KMS with aws/s3.
  #checkov:skip=CKV_AWS_252:Alerts go through CloudWatch alarms -> SNS instead of per-file SNS notifications.
  count                         = local.mon
  name                          = "policycraft-security-trail"
  s3_bucket_name                = aws_s3_bucket.cloudtrail[0].id
  include_global_service_events = true # IAM events are global
  is_multi_region_trail         = true
  enable_log_file_validation    = true
  cloud_watch_logs_group_arn    = "${aws_cloudwatch_log_group.cloudtrail[0].arn}:*"
  cloud_watch_logs_role_arn     = aws_iam_role.cloudtrail_to_cw[0].arn

  depends_on = [aws_s3_bucket_policy.cloudtrail, aws_iam_role_policy.cloudtrail_to_cw]
}

# ─── Metric filters + alarms ─────────────────────────────────────────────────
resource "aws_cloudwatch_log_metric_filter" "security" {
  for_each       = var.enable_security_monitoring ? local.security_alarms : {}
  name           = "policycraft-${each.key}"
  log_group_name = each.value.log_group == "trail" ? aws_cloudwatch_log_group.cloudtrail[0].name : aws_cloudwatch_log_group.api_access.name
  pattern        = each.value.pattern

  metric_transformation {
    name          = each.key
    namespace     = "PolicyCraft/Security"
    value         = "1"
    default_value = "0"
  }
}

resource "aws_cloudwatch_metric_alarm" "security" {
  for_each            = var.enable_security_monitoring ? local.security_alarms : {}
  alarm_name          = "policycraft-${each.key}"
  alarm_description   = each.value.description
  namespace           = "PolicyCraft/Security"
  metric_name         = each.key
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.security_alerts[0].arn]
  ok_actions          = [aws_sns_topic.security_alerts[0].arn]

  depends_on = [aws_cloudwatch_log_metric_filter.security]
}
