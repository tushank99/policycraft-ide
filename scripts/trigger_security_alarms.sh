#!/usr/bin/env bash
# P3: trigger each security alarm once on purpose, then clean up.
#
# Prereqs: terraform apply -var enable_security_monitoring=true -var alert_email=you@example.com
#          (confirm the SNS subscription email first), AWS CLI logged in as an admin.
#
# Usage:   scripts/trigger_security_alarms.sh            # trigger + wait for ALARM
#          scripts/trigger_security_alarms.sh --no-wait
#
# Everything this script creates is deleted before it exits (trap), even on error.
set -euo pipefail

REGION="${AWS_REGION:-us-east-1}"
SUFFIX="$(date +%s)"
TEST_POLICY="policycraft-alarm-test-${SUFFIX}"
TEST_ROLE="policycraft-alarm-test-noperms-${SUFFIX}"
ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
API_URL="$(cd "$(dirname "$0")/../infra" && terraform output -raw api_url)"
POLICY_ARN=""

cleanup() {
  echo "-- cleanup"
  [ -n "$POLICY_ARN" ] && aws iam delete-policy --policy-arn "$POLICY_ARN" 2>/dev/null && echo "   deleted policy $TEST_POLICY" || true
  aws iam delete-role --role-name "$TEST_ROLE" 2>/dev/null && echo "   deleted role $TEST_ROLE" || true
}
trap cleanup EXIT

echo "== 1/3 IAM policy change: create + delete a managed policy"
POLICY_ARN="$(aws iam create-policy --policy-name "$TEST_POLICY" \
  --policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Deny","Action":"s3:GetObject","Resource":"arn:aws:s3:::policycraft-nonexistent/*"}]}' \
  --query Policy.Arn --output text)"
aws iam delete-policy --policy-arn "$POLICY_ARN" && POLICY_ARN=""
echo "   CreatePolicy + DeletePolicy sent"

echo "== 2/3 Unauthorized API call: assume a no-permission role and call S3"
aws iam create-role --role-name "$TEST_ROLE" --max-session-duration 3600 \
  --assume-role-policy-document "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Principal\":{\"AWS\":\"arn:aws:iam::${ACCOUNT}:root\"},\"Action\":\"sts:AssumeRole\"}]}" >/dev/null
echo "   waiting 15s for IAM propagation"; sleep 15
CREDS="$(aws sts assume-role --role-arn "arn:aws:iam::${ACCOUNT}:role/${TEST_ROLE}" --role-session-name alarmtest \
  --query 'Credentials.[AccessKeyId,SecretAccessKey,SessionToken]' --output text)"
read -r AK SK ST <<<"$CREDS"
for i in 1 2 3; do
  AWS_ACCESS_KEY_ID="$AK" AWS_SECRET_ACCESS_KEY="$SK" AWS_SESSION_TOKEN="$ST" \
    aws s3api list-buckets --region "$REGION" >/dev/null 2>&1 && echo "   unexpected success" || echo "   AccessDenied #$i (expected)"
done

echo "== 3/3 Failed API auth: call the PolicyCraft API without a JWT"
for i in 1 2 3 4 5; do
  code="$(curl -s -o /dev/null -w '%{http_code}' "${API_URL%/}/requests")"
  echo "   GET /requests -> HTTP $code (expected 401)"
done

if [ "${1:-}" = "--no-wait" ]; then exit 0; fi

echo "== Waiting for alarms (CloudTrail -> CloudWatch delivery takes ~5-15 min)"
ALARMS="policycraft-iam_policy_changes policycraft-unauthorized_api_calls policycraft-failed_api_auth"
for _ in $(seq 1 40); do
  states="$(aws cloudwatch describe-alarms --alarm-names $ALARMS --region "$REGION" \
    --query 'MetricAlarms[].[AlarmName,StateValue]' --output text)"
  echo "$states" | sed 's/^/   /'; echo "   --"
  if [ "$(echo "$states" | grep -c ALARM)" -eq 3 ]; then
    echo "All 3 alarms fired. Check your inbox for the SNS emails."
    exit 0
  fi
  sleep 30
done
echo "Timed out waiting; re-run: aws cloudwatch describe-alarms --alarm-names $ALARMS"
exit 1
