#!/usr/bin/env bash
# Deploy the Chase API to AWS Lambda behind a free HTTPS Function URL.
# Needs: AWS CLI v2 signed in (aws configure / aws sso login), python3, zip. Run from the repo root.
set -euo pipefail
REGION="${AWS_REGION:-ap-south-1}"
FN="${FN:-chase-api}"
ROLE="${ROLE:-chase-api-role}"
export AWS_DEFAULT_REGION="$REGION"

echo "Account: $(aws sts get-caller-identity --query Account --output text)  Region: $REGION"

rm -rf build/lambda && mkdir -p build/lambda
python3 -m pip install -q --target build/lambda --platform manylinux2014_aarch64 --implementation cp \
  --python-version 3.12 --only-binary=:all: -r backend/requirements-lambda.txt
mkdir -p build/lambda/backend build/lambda/web
cp -r backend/app build/lambda/backend/app && touch build/lambda/backend/__init__.py
cp -r web/data build/lambda/web/data
find build/lambda -name '__pycache__' -prune -exec rm -rf {} +
(cd build/lambda && zip -qr ../chase-api.zip .)
echo "Package: $(du -h build/chase-api.zip | cut -f1)"

if ! aws iam get-role --role-name "$ROLE" >/dev/null 2>&1; then
  aws iam create-role --role-name "$ROLE" --assume-role-policy-document \
    '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"lambda.amazonaws.com"},"Action":"sts:AssumeRole"}]}' >/dev/null
  aws iam attach-role-policy --role-name "$ROLE" --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
  echo "Created role; waiting for it to propagate..."; sleep 12
fi
ROLE_ARN=$(aws iam get-role --role-name "$ROLE" --query Role.Arn --output text)

if aws lambda get-function --function-name "$FN" >/dev/null 2>&1; then
  aws lambda update-function-code --function-name "$FN" --zip-file fileb://build/chase-api.zip >/dev/null
  aws lambda wait function-updated --function-name "$FN"
else
  aws lambda create-function --function-name "$FN" --runtime python3.12 --architectures arm64 \
    --handler backend.app.lambda_handler.handler --role "$ROLE_ARN" --memory-size 512 --timeout 30 \
    --zip-file fileb://build/chase-api.zip >/dev/null
  aws lambda wait function-active --function-name "$FN"
  aws lambda create-function-url-config --function-name "$FN" --auth-type NONE \
    --cors '{"AllowOrigins":["*"],"AllowMethods":["GET","POST"],"AllowHeaders":["*"]}' >/dev/null
  aws lambda add-permission --function-name "$FN" --statement-id url-public --action lambda:InvokeFunctionUrl \
    --principal '*' --function-url-auth-type NONE >/dev/null
  aws lambda add-permission --function-name "$FN" --statement-id url-public-invoke --action lambda:InvokeFunction \
    --principal '*' >/dev/null 2>&1 || true
fi
URL=$(aws lambda get-function-url-config --function-name "$FN" --query FunctionUrl --output text)
URL="${URL%/}"
echo; echo "API URL: $URL"; sleep 3
curl -s "$URL/health" || true; echo
echo "Next: put this URL in docs/config.js as CHASE_CONFIG.api"
