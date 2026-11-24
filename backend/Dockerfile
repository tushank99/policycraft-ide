# Container image of the generation orchestrator Lambda.
# Used for (a) Trivy image scanning in CI and (b) running the pipeline locally
# with the Lambda Runtime Interface Emulator:
#   docker build -f backend/Dockerfile -t policycraft-orchestrator .
#   docker run -p 9000:8080 -e GROQ_API_KEY=... policycraft-orchestrator
FROM public.ecr.aws/lambda/python:3.15

# Pull the latest Amazon Linux security patches. The base image lags behind
# the AL2023 repos (e.g. rpm/sqlite-libs fixes), which Trivy flags as HIGH.
# AL2023 pins dnf to the image's release version, so a plain upgrade is a
# no-op; --releasever=latest moves to the newest repo where the fixes live.
RUN dnf -y upgrade --refresh --releasever=latest && dnf clean all && rm -rf /var/cache/dnf

COPY backend/generation_orchestrator/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY backend/generation_orchestrator/ ${LAMBDA_TASK_ROOT}/
COPY backend/shared/ ${LAMBDA_TASK_ROOT}/shared/
COPY backend/policy_service/parser.py backend/policy_service/defaults.py ${LAMBDA_TASK_ROOT}/
COPY backend/validation_service/rules.py backend/validation_service/ast_engine.py \
     backend/validation_service/security_scanner.py backend/validation_service/manifest_rules.py \
     ${LAMBDA_TASK_ROOT}/

USER 1000
CMD ["handler.handler"]
