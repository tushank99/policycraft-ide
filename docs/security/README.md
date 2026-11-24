# PolicyCraft security & AI-for-Cyber work (P1–P5)

All of it is designed to stay inside the **AWS / GitHub / Groq free tiers**. The only
paid items are opt-in and off by default (Bedrock, customer-managed KMS keys, GuardDuty).

| # | Area | Where |
|---|---|---|
| P1 | IAM + cloud security | `infra/iam.tf`, `infra/policies/*.json.tftpl`, `infra/cognito.tf`, `.checkov.yaml`, `scripts/validate_iam_policies.py` |
| P2 | AppSec + vuln management | `.github/workflows/security.yml`, `.github/dependabot.yml`, `.semgrep.yml`, `.gitleaks.toml`, `.trivyignore`, `.security/` |
| P3 | Security monitoring | `infra/monitoring.tf`, `scripts/trigger_security_alarms.sh` |
| P4 | Transformer fine-tuning | `ml/` (`fetch_nvd.py`, `baseline.py`, `train_distilbert.py`, `finetune_distilbert_colab.ipynb`, `severity_model.py`, `rank_findings.py`) |
| P5 | Multi-agent triage | `agents/` (LangGraph), `.github/workflows/triage.yml` |

---

## Recorded results

### P1: IAM and cloud security

| Metric | Before | After |
|---|---|---|
| Checkov failed checks (infra/) | **84** | **0** |
| Checkov HIGH (hard-fail list) | **21** | **0** |
| Checkov passed | 61 | 203 |
| Checkov skipped (inline, each with a written reason) | 0 | 93 |
| IAM roles used by Lambdas | 1 shared role | 7 roles + 1 Pipe role |
| Wildcard permissions | `AdministratorAccess`: `Action "*"` on `Resource "*"`, shared by 8 principals | **0** wildcard actions, **0** wildcard resources (9 policies) |

The 21 HIGH failures before were:
- 12 × API routes with no authorization (CKV_AWS_309)
- 7 × public frontend bucket: CKV2_AWS_6 ×2, CKV_AWS_53/54/55/56 and CKV_AWS_70
- 1 × AdministratorAccess (CKV_AWS_274)
- 1 × unencrypted SQS queue (CKV_AWS_27)

Wildcards removed: the one `*:*` grant. Every role now names exact table, queue, bucket-prefix, SSM-parameter, log-group and model ARNs.
The 12 remaining `…/*` suffixes are *scoped* (`bucket/generated/*`, `log-group:<name>:log-stream:*`), because AWS can't name objects that don't exist yet. The validator reports them separately and allows them.

Other P1 changes:
- SSE-KMS on S3 (aws/s3 key + bucket keys) and DynamoDB (aws/dynamodb key). SQS SSE is on.
- All S3 buckets block public access and deny non-TLS requests.
- The frontend moved from a public website bucket to a private bucket behind CloudFront with OAC.
- The Groq key and GitHub PAT moved from Lambda env vars to SSM SecureString parameters.
- A Cognito JWT authorizer protects every route, CORS is limited to the CloudFront and localhost origins, and the API has throttling and access logs.
- `PUT /policies` requires the Cognito `admins` group. Previously it was gated only by a hardcoded `admin123` password in the frontend.

**Free-tier trade-offs (skipped checks):** customer-managed KMS keys ($1/month each), X-Ray (its IAM action only supports `Resource "*"`), WAF, VPC + NAT, PITR, and access-log buckets.

**Still to record:** IAM Access Analyzer `validate-policy` output. It runs in CI once `AWS_SECURITY_ROLE_ARN` is set (see the runbook).

### P2: Application security and vulnerability management (local run, 2026-11-24)

| Source | Found | Fixed | Accepted | False positive |
|---|---|---|---|---|
| npm audit (prod deps) | 16 (axios ×12, follow-redirects ×3, react-router ×1) | 16 (`npm audit fix`) | 0 | 0 |
| pip-audit | 9 (pytest, transformers ×6, datasets, fsspec) | 6 (pytest 9.0.3, transformers ≥5.10, datasets ≥5.0.1, fsspec ≥2026.6.0) | 3 (transformers, no upstream fix, training-only deps) | 0 |
| Semgrep | 12 | 2 (GitHub API call with no timeout; SHA-1 → SHA-256) | 9 (7 × X-Ray INFO, CloudFront default-cert TLS, DynamoDB CMK) | 1 (custom rule matched `list.append`; rule fixed) |
| Secrets (git history regex: `gsk_`, `ghp_`, `github_pat_`, `AKIA`) | 0 | – | – | – |
| Manual review | 2 (hardcoded admin password in SPA; plaintext secrets in Lambda env) | 2 | 0 | 0 |
| **Total** | **39** | **26** | **12** | **1** |

Trivy (deps + container image) and gitleaks run in CI on the first push. They weren't run locally.

Gates in CI: Semgrep `ERROR`, Trivy `HIGH/CRITICAL` with a fix available, any pip-audit vuln not in `.security/pip-audit-ignore.txt`, npm `high+`, any gitleaks hit, and the Checkov hard-fail list.

### P3: Security monitoring
Three alarms: IAM policy changes, unauthorized API calls (CloudTrail), and failed API auth (API Gateway 401/403). They publish to an SNS email.
**Not yet triggered.** That needs a live AWS account (runbook step 3).

### P4: CVE severity model (NVD, 6,000 CVEs, 1,500 per class, sampled across eras)

| Model | Macro-F1 (600 held-out CVEs) |
|---|---|
| TF-IDF + logistic regression | **0.7034** |
| DistilBERT fine-tuned | _run `ml/finetune_distilbert_colab.ipynb` on a Colab T4, then `python ml/compare.py`_ |

Full table: `ml/results/RESULTS.md`. Both models use the committed dataset and the same seed-42 split.

### P5: Multi-agent triage (local run on this repo's real scans + 5 test fixtures)
- Findings processed per run: **30**
- Time per report: **6.5 s** (baseline severity model, offline remediation; Groq adds about 2–5 s for one batched call)
- 3 dependency fixes proposed and held for human approval. None were applied automatically.

---

## Runbook (needs your accounts)

### 1. Deploy (free tier)
```bash
cd infra
terraform init
terraform apply -var="groq_api_key=$GROQ_API_KEY"   # github_token optional
```
Create your login. Self sign-up is disabled.
```bash
POOL=$(terraform output -raw cognito_user_pool_id)
aws cognito-idp admin-create-user --user-pool-id $POOL --username you@example.com
aws cognito-idp admin-add-user-to-group --user-pool-id $POOL --username you@example.com --group-name admins
```
Build the frontend with `VITE_API_URL`, `VITE_COGNITO_DOMAIN` and `VITE_COGNITO_CLIENT_ID` from the Terraform outputs.
Sync `dist/` to `frontend_bucket`, then invalidate `cloudfront_distribution_id`.

### 2. Access Analyzer in CI (P1)
Create an IAM role trusted by GitHub OIDC for this repo, allowing only `access-analyzer:ValidatePolicy`.
Set the repo **variable** `AWS_SECURITY_ROLE_ARN`.

### 3. Prove the alarms (P3), then tear down
```bash
terraform apply -var="groq_api_key=$GROQ_API_KEY" -var enable_security_monitoring=true -var alert_email=you@example.com
# click "Confirm subscription" in the email, then:
bash scripts/trigger_security_alarms.sh     # creates + deletes its own test policy/role
terraform apply -var="groq_api_key=$GROQ_API_KEY" -var enable_security_monitoring=false
```
If the account already has a CloudTrail trail, this one is a second copy (about $2 per 100k events). Keep it on only for the test.

### 4. DistilBERT (P4)
Open `ml/finetune_distilbert_colab.ipynb` in Colab, select a T4 GPU, set `REPO`, and run all.
Unzip the downloaded model into `ml/models/` and copy `distilbert.json` to `ml/results/`.

### 5. Agents on PRs (P5)
Works with the default `GITHUB_TOKEN`. Add the repo secret `GROQ_API_KEY` for LLM remediation text; without it the agents use templates.
A maintainer approves fixes by commenting `/approve-fixes <ids>`.
Bedrock is supported (`REMEDIATION_LLM=bedrock`) but is **not free tier**.
