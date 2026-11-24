#!/usr/bin/env python3
"""Validate PolicyCraft IAM policies.

1. Renders every infra/policies/*.json.tftpl with placeholder ARNs.
2. Local gate (no AWS needed): fails if any Allow statement has a wildcard
   action ("*", "s3:*", "dynamodb:Get*") or a wildcard resource ("*",
   "arn:aws:s3:::*", a whole-service ARN). Object/stream suffixes that are
   scoped to one named resource (bucket/generated/*, log-group:...:log-stream:*)
   are reported but allowed, because AWS has no way to name objects that don't
   exist yet.
3. --access-analyzer: also calls IAM Access Analyzer ValidatePolicy (free) and
   fails on ERROR or SECURITY_WARNING findings. Needs AWS credentials.

Exit code 0 = pass, 1 = fail.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from string import Template

ROOT = Path(__file__).resolve().parents[1]
POLICY_DIR = ROOT / "infra" / "policies"

ACCOUNT = "123456789012"
REGION = "us-east-1"
PLACEHOLDERS = {
    "table_arn": f"arn:aws:dynamodb:{REGION}:{ACCOUNT}:table/idp-table",
    "stream_arn": f"arn:aws:dynamodb:{REGION}:{ACCOUNT}:table/idp-table/stream/2026-01-01T00:00:00.000",
    "queue_arn": f"arn:aws:sqs:{REGION}:{ACCOUNT}:idp-generation-queue",
    "artifacts_bucket_arn": f"arn:aws:s3:::idp-artifacts-{ACCOUNT}",
    "vault_bucket_arn": f"arn:aws:s3:::idp-audit-vault-{ACCOUNT}",
    "groq_param_arn": f"arn:aws:ssm:{REGION}:{ACCOUNT}:parameter/policycraft/groq_api_key",
    "github_param_arn": f"arn:aws:ssm:{REGION}:{ACCOUNT}:parameter/policycraft/github_token",
    "bedrock_model_arn": f"arn:aws:bedrock:{REGION}::foundation-model/meta.llama3-70b-instruct-v1:0",
    "log_group_arn": f"arn:aws:logs:{REGION}:{ACCOUNT}:log-group:/aws/lambda/idp-example",
    "audit_function_arn": f"arn:aws:lambda:{REGION}:{ACCOUNT}:function:idp-audit-service",
}

# A "scoped" suffix wildcard: the part before the * names one concrete resource.
_SCOPED_SUFFIX = re.compile(r"^arn:aws:(s3:::[a-z0-9.\-]+/.+|logs:[^:]+:\d+:log-group:[^*]+:log-stream:)\*$")


def render(path: Path) -> dict:
    text = Template(path.read_text(encoding="utf-8")).substitute(PLACEHOLDERS)
    return json.loads(text)


def _as_list(v):
    return v if isinstance(v, list) else [v]


def classify(policy: dict) -> dict:
    """Return wildcard findings for Allow statements."""
    out = {"wildcard_actions": [], "wildcard_resources": [], "scoped_suffixes": []}
    for st in _as_list(policy.get("Statement", [])):
        if st.get("Effect") != "Allow":
            continue
        sid = st.get("Sid", "<no-sid>")
        for action in _as_list(st.get("Action", [])):
            if "*" in action:
                out["wildcard_actions"].append(f"{sid}: {action}")
        if "NotAction" in st or "NotResource" in st:
            out["wildcard_actions"].append(f"{sid}: uses NotAction/NotResource")
        for res in _as_list(st.get("Resource", [])):
            if "*" not in res:
                continue
            if _SCOPED_SUFFIX.match(res):
                out["scoped_suffixes"].append(f"{sid}: {res}")
            else:
                out["wildcard_resources"].append(f"{sid}: {res}")
    return out


def access_analyzer(policy: dict) -> list[dict]:
    import boto3

    client = boto3.client("accessanalyzer", region_name=REGION)
    findings, token = [], None
    while True:
        kwargs = {"policyDocument": json.dumps(policy), "policyType": "IDENTITY_POLICY"}
        if token:
            kwargs["nextToken"] = token
        resp = client.validate_policy(**kwargs)
        findings.extend(resp.get("findings", []))
        token = resp.get("nextToken")
        if not token:
            return findings


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--access-analyzer", action="store_true", help="also call IAM Access Analyzer ValidatePolicy")
    ap.add_argument("--json", type=Path, help="write a JSON report here")
    args = ap.parse_args()

    files = sorted(POLICY_DIR.glob("*.json.tftpl"))
    if not files:
        print(f"No policy templates in {POLICY_DIR}")
        return 1

    failed = False
    report = {"policies": {}, "totals": {"wildcard_actions": 0, "wildcard_resources": 0, "scoped_suffixes": 0}}
    for f in files:
        name = f.name.replace(".json.tftpl", "")
        policy = render(f)
        result = classify(policy)
        for k in report["totals"]:
            report["totals"][k] += len(result[k])
        bad = result["wildcard_actions"] + result["wildcard_resources"]
        status = "FAIL" if bad else "ok"
        print(f"[{status}] {name}")
        for line in bad:
            print(f"    wildcard: {line}")
        for line in result["scoped_suffixes"]:
            print(f"    scoped:   {line}")
        if bad:
            failed = True

        if args.access_analyzer:
            findings = access_analyzer(policy)
            result["access_analyzer"] = [
                {"type": x["findingType"], "issue": x["issueCode"], "detail": x["findingDetails"]} for x in findings
            ]
            for x in findings:
                print(f"    analyzer {x['findingType']}: {x['issueCode']} - {x['findingDetails']}")
                if x["findingType"] in ("ERROR", "SECURITY_WARNING"):
                    failed = True
        report["policies"][name] = result

    t = report["totals"]
    print(
        f"\n{len(files)} policies | wildcard actions: {t['wildcard_actions']} | "
        f"wildcard resources: {t['wildcard_resources']} | scoped object/log suffixes: {t['scoped_suffixes']}"
    )
    if args.json:
        args.json.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("RESULT:", "FAIL" if failed else "PASS")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
