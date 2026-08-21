"""Generation Orchestrator Lambda handler.

Triggered by SQS. Orchestrates the full generation pipeline:
1. Read SQS message (requestId, serviceName, selectedArtifacts)
2. Update status → GENERATING
3. Fetch active policy profile
4. Run deterministic parser → generation spec
5. Build LLM prompt
6. Run Guardrails (Sanitize + Budget Check)
7. Call LLM Router (Groq + Bedrock Failover)
8. Parse LLM output into files
9. Create ZIP + upload to S3
10. Run governance validation
11. Update status + Telemetry → COMPLETED (or FAILED)
"""

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from shared.logger import get_logger
from shared.db import (
    get_policy_profile,
    update_request_status,
    save_validation_results,
    get_request,
)
from shared.s3_helper import upload_zip
from prompt_builder import build_system_prompt, build_user_prompt, build_repair_prompt
from artifact_assembler import parse_llm_output, create_zip, get_file_list

from guardrails import Guardrails, TokenBudgetExceededException
from llm_client import LLMClient
from shared.lineage import calculate_sha256

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'policy_service'))
from parser import parse_policy_to_spec
from defaults import DEFAULT_POLICY_PROFILE

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'validation_service'))
from rules import validate_generated_output

logger = get_logger("generation-orchestrator")
ARTIFACTS_BUCKET = os.environ.get("ARTIFACTS_BUCKET", "idp-artifacts")
llm_client = LLMClient()


def handler(event, context):
    """Lambda entry point — processes SQS messages for code generation."""
    for record in event.get("Records", []):
        try:
            _process_record(record)
        except Exception as e:
            logger.exception(f"Failed to process SQS record: {e}")
            raise


def _process_record(record: dict):
    """Process a single SQS generation request."""
    body = json.loads(record["body"])
    request_id = body["requestId"]
    service_request = body.get("serviceRequest") or body.get("request") or ""
    service_name = body["serviceName"]
    selected_artifacts = body.get("selectedArtifacts", [])

    logger.info(f"Processing generation request: {request_id} for '{service_name}'")
    start_time = time.time()

    # Step 1: Update status to GENERATING
    update_request_status(request_id, "GENERATING", step="Resolving policies")

    # Step 2: Fetch active policy profile
    policy_item = get_policy_profile()
    if policy_item:
        profile = policy_item.get("profile", DEFAULT_POLICY_PROFILE)
    else:
        profile = DEFAULT_POLICY_PROFILE
        logger.info("No saved policy profile — using defaults")

    # Step 3: Parse policy → generation spec (deterministic, no LLM)
    update_request_status(request_id, "GENERATING", step="Building generation spec")
    spec = parse_policy_to_spec(profile)

    
    if selected_artifacts:
        spec["selectedArtifacts"] = [a for a in spec["artifacts"] if a in selected_artifacts]
    else:
        spec["selectedArtifacts"] = spec["artifacts"]
    logger.info(f"Generation spec resolved: stack={spec['stack']}, artifacts={spec['selectedArtifacts']}")

    # Step 4: Apply naming convention
    naming_pattern = spec["requirements"]["namingPattern"]
    clean_name = _extract_service_name(service_request)
    resolved_name = naming_pattern.replace("{name}", clean_name)

    # Step 5: Build prompts
    update_request_status(request_id, "GENERATING", step="Generating code via LLM")
    system_prompt = build_system_prompt(spec)
    raw_user_prompt = build_user_prompt(service_request, resolved_name)

    try:
        Guardrails.check_token_budget(raw_user_prompt)
        safe_user_prompt = Guardrails.sanitize_and_isolate(raw_user_prompt)
    except TokenBudgetExceededException as e:
        logger.error(f"Token budget exceeded: {e}")
        update_request_status(
            request_id,
            "FAILED",
            step="Guardrails failed",
            error=str(e),
        )
        return

    # Step 6: Call LLM Router (Groq primary, Bedrock fallback)
    try:
        generation_result = llm_client.generate_code(system_prompt, safe_user_prompt)
        raw_output = generation_result["content"]
    except RuntimeError as e:
        logger.error(f"LLM API call failed: {e}")
        update_request_status(
            request_id,
            "FAILED",
            step="LLM API call failed",
            error=str(e),
        )
        return

    # Step 7: Parse output into files
    update_request_status(request_id, "GENERATING", step="Assembling artifacts")
    try:
        files = parse_llm_output(raw_output)
    except ValueError as e:
        logger.error(f"Failed to parse LLM output: {e}")
        update_request_status(
            request_id,
            "FAILED",
            step="Failed to parse generated code",
            error=str(e),
        )
        return

    # Step 8: Validate, then repair mandatory failures once before zipping
    update_request_status(request_id, "GENERATING", step="Running governance validation")
    validation_results = validate_generated_output(files, spec)
    files, validation_results = _repair_mandatory_failures(
        files, spec, validation_results, system_prompt, service_request, request_id
    )

    # Step 9: Create ZIP and upload to S3
    zip_bytes = create_zip(files, resolved_name)
    s3_key = f"generated/{request_id}/{resolved_name}.zip"
    upload_zip(s3_key, zip_bytes)
    logger.info(f"ZIP uploaded to s3://{ARTIFACTS_BUCKET}/{s3_key}")
    save_validation_results(request_id, validation_results)

    # Step 10: Calculate Cryptographic Lineage & update status to COMPLETED
    policy_hash = calculate_sha256(spec)
    prompt_hash = calculate_sha256(system_prompt + raw_user_prompt)
    artifact_hash = calculate_sha256(zip_bytes)
    validation_hash = calculate_sha256(validation_results)

    lineage = {
        "policyHash": policy_hash,
        "promptHash": prompt_hash,
        "artifactHash": artifact_hash,
        "validationHash": validation_hash
    }

    elapsed = Decimal(str(round(time.time() - start_time, 2)))
    file_list = get_file_list(files)
    passed = sum(1 for r in validation_results if r["status"] == "PASS")
    total = len(validation_results)

    update_request_status(
        request_id,
        "COMPLETED",
        step="Complete",
        s3Key=s3_key,
        resolvedName=resolved_name,
        generatedFiles=file_list,
        validationSummary={
            "passed": passed,
            "total": total,
            "allPassed": passed == total,
        },
        generationTimeSeconds=elapsed,
        completedAt=datetime.now(timezone.utc).isoformat(),
        llmProviderUsed=generation_result["provider"],
        modelId=generation_result["model_id"],
        tokenUsage=generation_result["usage"],
        estimatedCostUSD=str(generation_result["cost_usd"]),
        generationLatencyMs=str(generation_result["latency_ms"]),
        lineage=lineage # Injected hashes ready for the Audit Stream
    )

    logger.info(
        f"Generation complete for {request_id}: {len(files)} files, "
        f"{passed}/{total} validation checks passed, {elapsed}s elapsed"
    )


def _mandatory_failures(results: list[dict]) -> list[dict]:
    return [
        item for item in results
        if item.get("status") == "FAIL" and item.get("severity") == "mandatory"
    ]


def _repair_mandatory_failures(
    files: dict,
    spec: dict,
    validation_results: list,
    system_prompt: str,
    service_request: str,
    request_id: str,
) -> tuple[dict, list]:
    """One LLM rewrite pass when generated files fail mandatory checks."""
    failures = _mandatory_failures(validation_results)
    if not failures:
        return files, validation_results

    logger.info(f"Attempting repair for {len(failures)} mandatory validation failures")
    update_request_status(request_id, "GENERATING", step="Repairing generated code")
    repair_prompt = build_repair_prompt(files, failures, service_request)

    try:
        Guardrails.check_token_budget(repair_prompt)
        safe_repair = Guardrails.sanitize_and_isolate(repair_prompt)
        repair_result = llm_client.generate_code(system_prompt, safe_repair)
        repaired_files = parse_llm_output(repair_result["content"])
        merged = {**files, **repaired_files}
        revalidated = validate_generated_output(merged, spec)
        remaining = _mandatory_failures(revalidated)
        logger.info(
            f"Repair pass complete: {len(failures)} -> {len(remaining)} mandatory failures"
        )
        return merged, revalidated
    except Exception as err:
        logger.warning(f"Repair pass skipped: {err}")
        return files, validation_results


def _extract_service_name(service_request: str) -> str:
    """Extract a clean kebab-case service name from the developer's request.

    Examples:
        'Create Payment Microservice' -> 'payment'
        'Build User Authentication Service' -> 'user-authentication'
        'Payment Processing' -> 'payment-processing'
    """
    # Remove common prefixes
    text = service_request.strip()
    for prefix in ["create ", "build ", "generate ", "make ", "new "]:
        if text.lower().startswith(prefix):
            text = text[len(prefix):].strip()

    # Remove common suffixes
    for suffix in [" microservice", " service", " api", " application", " app", " project"]:
        if text.lower().endswith(suffix):
            text = text[:len(text)-len(suffix)].strip()

    # Convert to kebab-case
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"\s+", "-", text)
    text = re.sub(r"-+", "-", text)
    text = text.strip("-")

    # Prevent MAX_PATH issues in Windows by truncating absurdly long names
    if len(text) > 40:
        text = text[:40].strip("-")

    return text or "service"