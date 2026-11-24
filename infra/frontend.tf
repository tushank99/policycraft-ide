locals {
  frontend_bucket_name = "policycraft-frontend-${local.account_id}"
}

# ─── Private S3 bucket (was a public static-website bucket) ──────────────────
resource "aws_s3_bucket" "frontend" {
  #checkov:skip=CKV_AWS_18:Access logging would need another bucket and adds cost.
  #checkov:skip=CKV_AWS_144:Cross-region replication is not free-tier.
  #checkov:skip=CKV2_AWS_62:Event notifications are not required for static assets.
  #checkov:skip=CKV2_AWS_61:Static build output is replaced on every deploy; no lifecycle needed.
  #checkov:skip=CKV_AWS_21:Build output is reproducible from git; versioning only adds storage.
  #checkov:skip=CKV_AWS_145:CloudFront OAC cannot read objects encrypted with the AWS-managed aws/s3 key; a CMK costs money. SSE-S3 is used.
  bucket        = local.frontend_bucket_name
  force_destroy = true
}

resource "aws_s3_bucket_public_access_block" "frontend" {
  bucket                  = aws_s3_bucket.frontend.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "frontend" {
  #checkov:skip=CKV_AWS_145:CloudFront OAC cannot read objects encrypted with the AWS-managed aws/s3 key; a CMK costs money. SSE-S3 is used.
  bucket = aws_s3_bucket.frontend.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# ─── CloudFront + Origin Access Control ──────────────────────────────────────
resource "aws_cloudfront_origin_access_control" "frontend" {
  name                              = "policycraft-frontend-oac"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_cloudfront_distribution" "frontend" {
  #checkov:skip=CKV_AWS_68:AWS WAF is not free-tier.
  #checkov:skip=CKV_AWS_86:Access logging needs another bucket; not required here.
  #checkov:skip=CKV_AWS_174:The default *.cloudfront.net certificate can't pin a minimum TLS version; a custom domain is out of scope.
  #checkov:skip=CKV_AWS_310:Origin failover needs a second origin; not needed for a demo.
  #checkov:skip=CKV_AWS_374:Geo restriction is not a requirement.
  #checkov:skip=CKV2_AWS_42:Custom SSL certificate requires a custom domain.
  #checkov:skip=CKV2_AWS_32:Managed SecurityHeadersPolicy is attached by id (67f7725c-...); Checkov only recognises an aws_cloudfront_response_headers_policy resource.
  #checkov:skip=CKV2_AWS_47:Log4j WAF rule requires AWS WAF (not free-tier).
  enabled             = true
  default_root_object = "index.html"
  price_class         = "PriceClass_100"
  comment             = "PolicyCraft frontend"

  origin {
    domain_name              = aws_s3_bucket.frontend.bucket_regional_domain_name
    origin_id                = "frontend-s3"
    origin_access_control_id = aws_cloudfront_origin_access_control.frontend.id
  }

  default_cache_behavior {
    target_origin_id           = "frontend-s3"
    viewer_protocol_policy     = "redirect-to-https"
    allowed_methods            = ["GET", "HEAD", "OPTIONS"]
    cached_methods             = ["GET", "HEAD"]
    compress                   = true
    cache_policy_id            = "658327ea-f89d-4fab-a63d-7e88639e58f6" # Managed-CachingOptimized
    response_headers_policy_id = "67f7725c-6f97-4210-82d7-5512b31e9d03" # Managed-SecurityHeadersPolicy
  }

  # React Router: unknown paths fall back to index.html.
  custom_error_response {
    error_code         = 403
    response_code      = 200
    response_page_path = "/index.html"
  }
  custom_error_response {
    error_code         = 404
    response_code      = 200
    response_page_path = "/index.html"
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }
}

resource "aws_s3_bucket_policy" "frontend" {
  bucket = aws_s3_bucket.frontend.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "AllowCloudFrontOACOnly"
        Effect    = "Allow"
        Principal = { Service = "cloudfront.amazonaws.com" }
        Action    = "s3:GetObject"
        Resource  = "${aws_s3_bucket.frontend.arn}/*"
        Condition = { StringEquals = { "AWS:SourceArn" = aws_cloudfront_distribution.frontend.arn } }
      },
      {
        Sid       = "DenyInsecureTransport"
        Effect    = "Deny"
        Principal = { AWS = "*" }
        Action    = "s3:*"
        Resource  = [aws_s3_bucket.frontend.arn, "${aws_s3_bucket.frontend.arn}/*"]
        Condition = { Bool = { "aws:SecureTransport" = "false" } }
      }
    ]
  })
  depends_on = [aws_s3_bucket_public_access_block.frontend]
}
