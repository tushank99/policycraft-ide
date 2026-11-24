# PolicyCraft - Enterprise Internal Developer Platform

A comprehensive Internal Developer Platform (IDP) designed to define company-wide engineering standards as Policy-as-Code. It automatically scaffolds standardized, compliance-validated microservices complete with infrastructure, CI/CD, and embedded OpenTelemetry instrumentation via an event-driven architecture.

## What is PolicyCraft?

PolicyCraft bridges the gap between platform engineering teams and product developers. Instead of relying on static wiki pages for engineering standards, platform teams can codify rules as "Policy-as-Code." 

When developers need to create a new microservice, they simply describe their requirements in plain English. The platform uses AI to generate the initial code, but strictly evaluates it against organizational policies before delivery. This guarantees that every new service is compliant, secure, and fully instrumented from day one.

### Core Capabilities
- **Natural Language Scaffolding**: Developers request boilerplate microservices (Python, TypeScript, or Go) using simple prompts.
- **Automated Policy Enforcement**: Code is statically analyzed against company rules (e.g., "all APIs require pagination", "no plain-text secrets allowed") before it is ever built.
- **Zero-Setup Delivery**: Fully configured code is delivered as a downloadable artifact or provisioned directly into a new GitHub repository with CI/CD pre-configured.

## Architecture

The system utilizes an event-driven, cloud-native architecture on AWS:

```text
┌─────────────┐     ┌──────────────┐     ┌─────────────────────────────────┐
│  React SPA  │────▶│ API Gateway  │────▶│    Lambda Functions (Python)    │
│ (CloudFront)│     │  (REST API)  │     │  ┌───────────────────────────┐  │
└─────────────┘     └──────────────┘     │  │  policy-service           │  │
                                         │  │  status-service           │  │
                                         │  │  gen-orchestrator         │◀─SQS
                                         │  │  validation-service       │  │
                                         │  │  download-service         │  │
                                         │  │  provisioning-service     │  │
                                         │  └───────────────────────────┘  │
                                         └───────┬────────┬───────┬────────┘
                                                 │        │       │
                                          DynamoDB       S3    Groq API /
                                     (Streams enabled) (Vault) AWS Bedrock
                                                 │
                                            EventBridge
                                                 │
                                                 ▼
                                         ┌───────────────────────────┐
                                         │       audit-service       │
                                         └───────────────────────────┘
```

## Enterprise Features

The platform implements five core enterprise engineering paradigms:

### 1. LLM Guardrails, Multi-Provider Failover & FinOps Metering
Implements prompt injection defense, secret redaction, and multi-provider failover (Groq to AWS Bedrock circuit breaker). Features per-request token telemetry to enforce FinOps cost attribution and mitigate denial-of-wallet vectors.

### 2. Enterprise Golden Path Engine & Standardized OpenTelemetry
Provides a pluggable Golden Path engine that dynamically injects standardized OpenTelemetry distributed tracing, correlation ID middleware (`X-Correlation-ID`), structured JSON logging, and Kubernetes health probes (`/healthz`, `/readyz`) into scaffolded microservices across Python (FastAPI), TypeScript/Node, and Go.

### 3. Shift-Left Policy-as-Code (PaC) & Deterministic AST Compliance Gate
Architected a deterministic Policy-as-Code validation gate using Abstract Syntax Tree (AST) parsing and static security scanners. It statically intercepts AI-generated microservices to enforce zero-trust compliance, dependency pin verification, and strict secret absence before artifacts are built.

### 4. Compliance Audit Ledger & Cryptographic Lineage Tracking
Utilizes DynamoDB Streams and AWS EventBridge to asynchronously record immutable audit logs with SHA-256 lineage (`SHA256(PolicySpec || Prompt || ArtifactManifest)`). Ensures SOC 2 / ISO 27001 auditability without adding latency to synchronous developer requests.

### 5. Automated GitOps Repository Provisioning (Zero-Download Scaffolding)
Features a standalone provisioning service integrating with the GitHub REST API. Automatically provisions repositories to the organization with branch protection rules, baseline GitHub Actions CI/CD workflows, and initial pull requests, reducing microservice bootstrap time.

### 6. Security & AI-for-Cyber (P1–P5)
Least-privilege IAM per Lambda (no wildcards), Checkov + Access Analyzer in CI, Cognito-protected API, SSE-KMS everywhere, SAST/SCA/secret scanning with SARIF, CloudTrail alarms, a DistilBERT CVE-severity model, and a LangGraph multi-agent triage bot with human approval. Results and runbook: [docs/security/README.md](docs/security/README.md).

## Monorepo Structure

```text
├── frontend/    # React SPA (Vite)
├── backend/     # Python Lambda functions
├── infra/       # Terraform IaC
├── ml/          # CVE severity models (P4)
├── agents/      # LangGraph triage agents (P5)
├── scripts/     # IAM validation, alarm trigger
└── .github/     # CI/CD + security workflows
```

## AWS Services Utilized

| Category | Service | Purpose |
|----------|---------|---------|
| Compute | Lambda | Core microservices (policy, status, generation, validation, download, provisioning, audit) |
| API | API Gateway | REST API entry point |
| Storage | DynamoDB | Policies, request state, and validation history (Streams enabled) |
| Storage | S3 | Frontend hosting, artifact storage, and WORM-compliant audit vault |
| CDN | CloudFront | Frontend distribution |
| Messaging | SQS | Asynchronous generation queue |
| Event Routing | EventBridge | Audit logging pipeline |
| Monitoring | CloudWatch + X-Ray | Centralized logging, metrics, alarms, and tracing |
| AI | Groq / Bedrock | Primary and fallback LLM code generation |

## Prerequisites

- AWS CLI configured with appropriate credentials (compatible with AWS Free Tier)
- Terraform >= 1.5
- Node.js >= 20
- Python >= 3.12
- Groq API key
- GitHub Personal Access Token (for automated provisioning)

## Deployment

The platform is designed to be deployed via CI/CD, but can be bootstrapped manually.

### Infrastructure Configuration
Initialize the environment via Terraform:

```bash
cd infra
terraform init
terraform apply -var="groq_api_key=$GROQ_API_KEY" -var="github_token=$GITHUB_TOKEN"
```

Secrets are stored in SSM Parameter Store (SecureString), not in Lambda environment variables. Create a login user with `aws cognito-idp admin-create-user` (see docs/security/README.md).

### Frontend Deployment
Build and deploy the React application to the provisioned S3 bucket:

```bash
cd frontend
npm ci
export VITE_API_URL=$(cd ../infra && terraform output -raw api_url)
export VITE_COGNITO_DOMAIN=$(cd ../infra && terraform output -raw cognito_domain)
export VITE_COGNITO_CLIENT_ID=$(cd ../infra && terraform output -raw cognito_client_id)
npm run build
aws s3 sync dist/ s3://$(cd ../infra && terraform output -raw frontend_bucket) --delete
aws cloudfront create-invalidation --distribution-id $(cd ../infra && terraform output -raw cloudfront_distribution_id) --paths "/*"
```

Outputs for the CloudFront distribution and API Gateway endpoint are available via Terraform state.

## License

Internal use only.
