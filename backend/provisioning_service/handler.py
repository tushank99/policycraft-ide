"""Provisioning Service Lambda handler.

Triggered by API Gateway (POST /requests/{id}/provision).
Validates request status, downloads the ZIP artifact from S3, 
extracts it in memory, and triggers the GitOps provisioning workflow.
"""

import json
import os
import sys
import zipfile
import io
from typing import Dict, Any, Optional
import boto3

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from shared.logger import get_logger
from shared.db import get_request

from github_client import provision_to_github

logger = get_logger("provisioning-service")
s3_client: Any = boto3.client("s3")

ARTIFACTS_BUCKET = os.environ.get("ARTIFACTS_BUCKET")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")


def _respond(status_code: int, body: Dict[str, Any]) -> Dict[str, Any]:
    """Standardized API Gateway JSON response builder."""
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type,Authorization",
            "Access-Control-Allow-Methods": "POST,OPTIONS"
        },
        "body": json.dumps(body)
    }


def handler(event, context):
    """API Gateway entry point for GitHub provisioning."""
    try:
        # 1. Parse & Validate Path and Body Parameters
        path_parameters: Dict[str, Any] = event.get("pathParameters") or {}
        raw_request_id: Optional[str] = path_parameters.get("id")
        
        body: Dict[str, Any] = json.loads(event.get("body") or "{}")
        github_org: Optional[str] = body.get("githubOrg")
        repo_name: Optional[str] = body.get("repositoryName")

        # Type guard ensuring request_id, github_org, and repo_name are non-empty strings
        if not raw_request_id or not github_org or not repo_name:
            return _respond(400, {"error": "Missing required fields: id, githubOrg, repositoryName"})

        # Type-narrowed string variable
        request_id: str = raw_request_id

        if not GITHUB_TOKEN:
            return _respond(500, {"error": "GitHub integration is not configured (missing GITHUB_TOKEN)."})

        logger.info(f"Starting provisioning for Request: {request_id} -> {github_org}/{repo_name}")

        # 2. Validate Status in DynamoDB
        request_data = get_request(request_id)
        if not request_data:
            return _respond(404, {"error": "Request not found"})
            
        if request_data.get("status") != "COMPLETED":
            return _respond(400, {"error": f"Cannot provision. Request status is {request_data.get('status')}"})

        s3_key = request_data.get("s3Key")
        if not s3_key:
            return _respond(404, {"error": "ZIP artifact not found for this request."})

        # 3. Download and Extract ZIP in Memory
        logger.info(f"Downloading artifact from s3://{ARTIFACTS_BUCKET}/{s3_key}")
        response = s3_client.get_object(Bucket=ARTIFACTS_BUCKET, Key=s3_key)
        zip_bytes = response["Body"].read()

        extracted_files: Dict[str, bytes] = {}
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            for file_info in zf.infolist():
                if file_info.is_dir():
                    continue
                filename = file_info.filename
                if "/" in filename:
                    clean_path = filename.split("/", 1)[1]
                    if clean_path:
                        extracted_files[clean_path] = zf.read(filename)
                else:
                    extracted_files[filename] = zf.read(filename)

        # 4. Dispatch to GitHub GitOps Client
        logger.info(f"Extracted {len(extracted_files)} files. Dispatching to GitHub Client.")
        
        pr_url = provision_to_github(
            org=github_org, 
            repo_name=repo_name, 
            files=extracted_files, 
            token=GITHUB_TOKEN,
            request_data=request_data
        )

        return _respond(200, {
            "message": "Successfully provisioned to GitHub",
            "pullRequestUrl": pr_url,
            "repository": f"{github_org}/{repo_name}"
        })

    except json.JSONDecodeError:
        return _respond(400, {"error": "Invalid JSON body"})
    except Exception as e:
        logger.exception(f"Provisioning failed: {e}")
        return _respond(500, {"error": str(e)})