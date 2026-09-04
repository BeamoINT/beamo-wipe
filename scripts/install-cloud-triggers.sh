#!/usr/bin/env bash
# Create GitHub Cloud Build triggers in project beamo-wipe.
# Requires the Cloud Build GitHub App to have BeamoINT/beamo-wipe connected:
#   https://console.cloud.google.com/cloud-build/triggers;add=github?project=beamo-wipe
set -euo pipefail

project="${BEAMO_WIPE_GCP_PROJECT:-beamo-wipe}"
default_service_account="projects/beamo-wipe/serviceAccounts/368895881889-compute@developer.gserviceaccount.com"
if [[ -n "${BEAMO_WIPE_CLOUD_BUILD_SERVICE_ACCOUNT:-}" ]]; then
  service_account="$BEAMO_WIPE_CLOUD_BUILD_SERVICE_ACCOUNT"
elif [[ "$project" == "beamo-wipe" ]]; then
  service_account="$default_service_account"
else
  printf 'BEAMO_WIPE_CLOUD_BUILD_SERVICE_ACCOUNT is required outside project beamo-wipe\n' >&2
  exit 2
fi
case "$service_account" in
  "projects/$project/serviceAccounts/"*) ;;
  *)
    printf 'Cloud Build service account must belong to project %s: %s\n' \
      "$project" "$service_account" >&2
    exit 2
    ;;
esac
# shellcheck disable=SC2046
unset $(env | awk -F= '/^CLOUDSDK_/ {print $1}') 2>/dev/null || true

reconcile() {
  local name=$1; shift
  local -a update_args=("$@")
  local i
  for ((i = 0; i < ${#update_args[@]}; i++)); do
    if [[ "${update_args[i]}" == --substitutions=* ]]; then
      update_args[i]="--update-substitutions=${update_args[i]#--substitutions=}"
    fi
  done

  if gcloud builds triggers describe "$name" --project="$project" >/dev/null 2>&1; then
    printf 'reconciling: %s (service account: %s)\n' "$name" "$service_account"
    gcloud builds triggers update github "$name" \
      --project="$project" \
      --repo-owner=BeamoINT \
      --repo-name=beamo-wipe \
      --build-config=cloudbuild.yaml \
      --include-logs-with-status \
      --service-account="$service_account" \
      "${update_args[@]}"
    return
  fi

  printf 'creating: %s (service account: %s)\n' "$name" "$service_account"
  gcloud builds triggers create github \
    --project="$project" \
    --name="$name" \
    --repo-owner=BeamoINT \
    --repo-name=beamo-wipe \
    --build-config=cloudbuild.yaml \
    --include-logs-with-status \
    --service-account="$service_account" \
    "$@"
}

if ! reconcile beamo-wipe-pr-gate \
    --pull-request-pattern='^main$' \
    --description='Beamo Wipe lint/pytest/preview/negative/ISO on PRs to main (QEMU runs on main)' \
    --substitutions=_SKIP_QEMU=true \
    --comment-control=COMMENTS_ENABLED_FOR_EXTERNAL_CONTRIBUTORS_ONLY; then
  printf '\nConnect BeamoINT/beamo-wipe to Cloud Build in project %s, then re-run:\n' "$project" >&2
  printf '  https://console.cloud.google.com/cloud-build/triggers;add=github?project=%s\n' "$project" >&2
  printf '  %s\n' "$0" >&2
  exit 1
fi

reconcile beamo-wipe-main-gate \
  --branch-pattern='^main$' \
  --description='Beamo Wipe full gate (lint/pytest/preview/negative/ISO/QEMU) on pushes to main'

gcloud builds triggers list --project="$project" --format='table(name,filename,github.owner,github.name)'
