#!/usr/bin/env bash
# Submit this checkout to Google Cloud Build (project beamo-wipe).
# Unsets CLOUDSDK_* pins so a leftover support-deployer SA cannot steal the job.
set -euo pipefail

ROOT="$(CDPATH='' cd -- "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

project="${BEAMO_WIPE_GCP_PROJECT:-beamo-wipe}"
publish_release=false

while [ $# -gt 0 ]; do
  case "$1" in
    --skip-iso) export SUBSTITUTIONS="${SUBSTITUTIONS:+$SUBSTITUTIONS,}_SKIP_ISO=true" ;;
    --publish-release)
      publish_release=true
      export SUBSTITUTIONS="${SUBSTITUTIONS:+$SUBSTITUTIONS,}_PUBLISH_RELEASE=true"
      ;;
    --project)
      if [ $# -lt 2 ] || [ -z "${2-}" ]; then
        printf '%s requires a project ID\n' "$1" >&2
        exit 2
      fi
      project=$2
      shift
      ;;
    -h|--help)
      printf 'usage: %s [--skip-iso] [--publish-release] [--project ID]\n' "$0"
      exit 0
      ;;
    *)
      printf 'unknown argument: %s\n' "$1" >&2
      exit 2
      ;;
  esac
  shift
done

if [ "$publish_release" = true ] && {
  [ "${SUBSTITUTIONS#*_SKIP_ISO=true}" != "$SUBSTITUTIONS" ] ||
  [ "${SUBSTITUTIONS#*_SKIP_QEMU=true}" != "$SUBSTITUTIONS" ];
}; then
  printf 'release publication requires both ISO and QEMU gates\n' >&2
  exit 2
fi
if [ "$publish_release" = true ] && [ "$project" != "beamo-wipe" ]; then
  printf 'release publication is restricted to GCP project beamo-wipe\n' >&2
  exit 2
fi
if [ "$publish_release" = false ]; then
  case ",${SUBSTITUTIONS:-}," in
    *,_PUBLISH_RELEASE=true,*)
      printf 'use --publish-release instead of an environment-only publication substitution\n' >&2
      exit 2
      ;;
  esac
fi

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
