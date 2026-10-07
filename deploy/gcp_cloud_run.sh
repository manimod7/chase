#!/usr/bin/env bash
# Deploy the Chase API and site to Google Cloud Run (free tier friendly).
# Prereqs: gcloud installed and logged in (gcloud auth login), a project with billing enabled
# (Cloud Run's free quota still applies), and the project set: gcloud config set project YOUR_PROJECT_ID
set -euo pipefail
REGION="${REGION:-asia-south1}"
SERVICE="${SERVICE:-chase}"
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com
gcloud run deploy "$SERVICE" \
  --source . \
  --region "$REGION" \
  --allow-unauthenticated \
  --max-instances=1 --min-instances=0 \
  --memory=512Mi --cpu=1 \
  --set-env-vars "CHASE_CORS_ORIGINS=*" \
  --port 8080
gcloud run services describe "$SERVICE" --region "$REGION" --format='value(status.url)'
