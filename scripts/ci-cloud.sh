#!/usr/bin/env bash
# Submit this checkout to Google Cloud Build (project beamo-wipe).
# Unsets CLOUDSDK_* pins so a leftover support-deployer SA cannot steal the job.
set -euo pipefail

ROOT="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

project="${BEAMO_WIPE_GCP_PROJECT:-beamo-wipe}"

while [ $# -gt 0 ]; do
  case "$1" in
    --skip-iso) export SUBSTITUTIONS="${SUBSTITUTIONS:+$SUBSTITUTIONS,}_SKIP_ISO=true" ;;
    --project) project=${2-}; shift ;;
    -h|--help)
      printf 'usage: %s [--skip-iso] [--project ID]\n' "$0"
      exit 0
      ;;
    *)
      printf 'unknown argument: %s\n' "$1" >&2
      exit 2
      ;;
  esac
  shift
done

# CLOUDSDK_* in the shell profile can pin a different account/project.
# shellcheck disable=SC2046
unset $(env | awk -F= '/^CLOUDSDK_/ {print $1}') 2>/dev/null || true

extra=()
if [ -n "${SUBSTITUTIONS:-}" ]; then
  extra+=(--substitutions="$SUBSTITUTIONS")
fi

exec gcloud builds submit \
  --project="$project" \
  --config="$ROOT/cloudbuild.yaml" \
  "${extra[@]}" \
  "$ROOT"
