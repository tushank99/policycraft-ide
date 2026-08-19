"""Audit Processor Lambda.

Triggered by EventBridge Pipes reading from the DynamoDB idp-table stream.
Converts COMPLETED/FAILED generation records into immutable cryptographic 
manifests and stores them in an S3 Object Lock (WORM) vault for compliance 
(SOC 2, ISO 27001).
"""

import json
import os
from datetime import datetime, timezone
import boto3
from boto3.dynamodb.types import TypeDeserializer
from botocore.exceptions import ClientError

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from shared.logger import get_logger

logger = get_logger("audit-service")

s3_client = boto3.client("s3")
AUDIT_VAULT_BUCKET = os.environ.get("AUDIT_VAULT_BUCKET")
deserializer = TypeDeserializer()

def deserialize_dynamo_image(image: dict) -> dict:
    """Converts DynamoDB typed JSON into a standard Python dictionary."""
    return {k: deserializer.deserialize(v) for k, v in image.items()}

def handler(event, context):
    """EventBridge Pipe entry point. Receives an array of DynamoDB Stream records."""
    if not AUDIT_VAULT_BUCKET:
        logger.error("AUDIT_VAULT_BUCKET environment variable is missing!")
        return {"statusCode": 500}

    
    records = event if isinstance(event, list) else event.get("Records", [])
    
    for record in records:
        try:
            _process_audit_record(record)
        except Exception as e:
            logger.exception(f"Failed to process audit record: {e}")
            raise 

    return {"statusCode": 200, "body": f"Processed {len(records)} audit records."}

def _process_audit_record(record: dict):
    """Processes a single DynamoDB stream record and seals the manifest."""
    event_name = record.get("eventName")
    dynamodb_data = record.get("dynamodb", {})
    new_image_raw = dynamodb_data.get("NewImage")

    if not new_image_raw:
        return

    # Deserialize the clunky DynamoDB JSON into a clean dict
    request_data = deserialize_dynamo_image(new_image_raw)
    
    
    pk = request_data.get("PK", "")
    if not pk.startswith("REQUEST#"):
        return
        
    request_id = pk.replace("REQUEST#", "")
    status = request_data.get("status")
    
    logger.info(f"Generating audit manifest for Request: {request_id} (Status: {status})")

    # 1. Construct the Immutable Manifest Schema
    manifest = {
        "auditId": f"AUDIT-{request_id}",
        "requestId": request_id,
        "serviceName": request_data.get("resolvedName", "unknown"),
        "status": status,
        "auditTimestamp": datetime.now(timezone.utc).isoformat(),
        
      
        "telemetry": {
            "generationTimeSeconds": str(request_data.get("generationTimeSeconds", "0")),
            "llmProvider": request_data.get("llmProviderUsed", "unknown"),
            "modelId": request_data.get("modelId", "unknown"),
            "tokenUsage": request_data.get("tokenUsage", {}),
            "estimatedCostUSD": str(request_data.get("estimatedCostUSD", "0.0"))
        },
        
        
        "complianceGate": request_data.get("validationSummary", {}),
        
        
        "cryptographicLineage": request_data.get("lineage", {})
    }

    # 2. Define the S3 Object Key (Organized by Year/Month for easy auditing)
    now = datetime.now(timezone.utc)
    s3_key = f"manifests/{now.year}/{now.month:02d}/{request_id}.json"

    # 3. Seal into S3 Vault
    try:
        # Check if manifest already exists (Idempotency check)
        # Because we use Object Lock, overwriting might fail or create unnecessary versions
        try:
            s3_client.head_object(Bucket=AUDIT_VAULT_BUCKET, Key=s3_key)
            logger.info(f"Manifest for {request_id} already exists. Skipping duplicate stream event.")
            return
        except ClientError as e:
            if e.response['Error']['Code'] != '404':
                raise

        # Write the manifest to the WORM bucket
        s3_client.put_object(
            Bucket=AUDIT_VAULT_BUCKET,
            Key=s3_key,
            Body=json.dumps(manifest, indent=2),
            ContentType="application/json",
            
            ChecksumAlgorithm='SHA256'
        )
        logger.info(f"Successfully sealed audit manifest to s3://{AUDIT_VAULT_BUCKET}/{s3_key}")

    except ClientError as e:
        logger.error(f"S3 Vault Error: {e}")
        raise