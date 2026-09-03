#!/usr/bin/env bash
# Create GitHub Cloud Build triggers in project beamo-wipe.
# Requires the Cloud Build GitHub App to have BeamoINT/beamo-wipe connected:
#   https://console.cloud.google.com/cloud-build/triggers;add=github?project=beamo-wipe
set -euo pipefail

project="${BEAMO_WIPE_GCP_PROJECT:-beamo-wipe}"
# shellcheck disable=SC2046
unset $(env | awk -F= '/^CLOUDSDK_/ {print $1}') 2>/dev/null || true

create() {
  local name=$1; shift
  if gcloud builds triggers describe "$name" --project="$project" >/dev/null 2>&1; then
    printf 'already exists: %s\n' "$name"
    return 0
  fi
  gcloud builds triggers create github \
    --project="$project" \
    --name="$name" \
    --repo-owner=BeamoINT \
    --repo-name=beamo-wipe \
    --build-config=cloudbuild.yaml \
    --include-logs-with-status \
    "$@"
}

if ! create beamo-wipe-pr-gate \
    --pull-request-pattern='^main$' \
    --description='Beamo Wipe lint/pytest/preview/negative/ISO on PRs to main (QEMU runs on main)' \
    --substitutions=_SKIP_QEMU=true \
    --comment-control=COMMENTS_ENABLED_FOR_EXTERNAL_CONTRIBUTORS_ONLY; then
  printf '\nConnect BeamoINT/beamo-wipe to Cloud Build in project %s, then re-run:\n' "$project" >&2
  printf '  https://console.cloud.google.com/cloud-build/triggers;add=github?project=%s\n' "$project" >&2
  printf '  %s\n' "$0" >&2
  exit 1
fi

create beamo-wipe-main-gate \
  --branch-pattern='^main$' \
  --description='Beamo Wipe full gate (lint/pytest/preview/negative/ISO/QEMU) on pushes to main'

gcloud builds triggers list --project="$project" --format='table(name,filename,github.owner,github.name)'
