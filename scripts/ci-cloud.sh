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
    --skip-iso) export SUBSTITUTIONS="${SUBSTITUTIONS:+$SUBSTITUTIONS,}_SKIP_ISO=true,_SKIP_QEMU=true" ;;
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
  SUBSTITUTIONS="${SUBSTITUTIONS:+$SUBSTITUTIONS,}_PUBLISH_RELEASE=false"
fi
case ",${SUBSTITUTIONS:-}," in
  *,_ALLOW_DIRTY=*)
    printf 'dirty-source verification is selected from git status, not SUBSTITUTIONS\n' >&2
    exit 2
    ;;
esac

# CLOUDSDK_* in the shell profile can pin a different account/project.
# shellcheck disable=SC2046
unset $(env | awk -F= '/^CLOUDSDK_/ {print $1}') 2>/dev/null || true

extra=()
if [ -n "${SUBSTITUTIONS:-}" ]; then
  extra+=(--substitutions="$SUBSTITUTIONS")
fi

# gcloud checks symlinks before applying .gcloudignore. An earlier local
# live-build run leaves absolute hook links into Linux's /usr/share/live/build;
# those links are dangling on macOS and crash source packaging. Remove only
# untracked generated links to that exact hook tree. lb config recreates them.
for hook_parent in packaging packaging/live packaging/live/config \
                   packaging/live/config/hooks packaging/live/config/hooks/live \
                   packaging/live/config/hooks/normal; do
  if [ -L "$hook_parent" ]; then
    printf 'hook directory contains a symlink: %s\n' "$hook_parent" >&2
    exit 2
  fi
done
for hook in packaging/live/config/hooks/live/*.hook.chroot \
            packaging/live/config/hooks/normal/*.hook.chroot; do
  [ -L "$hook" ] || continue
  link_target="$(readlink "$hook")"
  case "$link_target" in
    /usr/share/live/build/hooks/*) ;;
    *) continue ;;
  esac
  [ -e "$hook" ] && continue
  if ! tracked_hook="$(git ls-files -- "$hook")"; then
    printf 'cannot check whether generated hook is tracked: %s\n' "$hook" >&2
    exit 2
  fi
  [ -z "$tracked_hook" ] || continue
  # Another local process can replace the link during the Git query. Open
  # every parent without following links and recheck the exact dangling hook
  # before unlinking it; never delete a newly written regular file instead.
  python3 - "$hook" "$link_target" <<'PY'
import os
from pathlib import Path
import stat
import sys

path = Path(sys.argv[1]).absolute()
expected = sys.argv[2]
flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
fd = os.open("/", flags)
try:
    for component in path.parts[1:-1]:
        next_fd = os.open(component, flags, dir_fd=fd)
        os.close(fd)
        fd = next_fd
    name = path.name
    current = os.stat(name, dir_fd=fd, follow_symlinks=False)
    if not stat.S_ISLNK(current.st_mode) or current.st_uid != os.getuid():
        raise SystemExit("generated hook changed during cleanup")
    if os.readlink(name, dir_fd=fd) != expected:
        raise SystemExit("generated hook changed during cleanup")
    try:
        os.stat(name, dir_fd=fd)
    except FileNotFoundError:
        pass
    else:
        raise SystemExit("generated hook is no longer dangling")
    os.unlink(name, dir_fd=fd)
finally:
    os.close(fd)
PY
done

# A checkout gate must run before the audited edits are committed. Mark that
# build as dirty for provenance, while keeping publication commit-only. Cloud
# Build defaults _ALLOW_DIRTY to 0 for clean submissions and GitHub triggers.
if ! source_status="$(git status --porcelain)"; then
  printf 'cannot determine source checkout state\n' >&2
  exit 2
fi
if [ -n "$source_status" ]; then
  if [ "$publish_release" = true ]; then
    printf 'release publication requires committed source; uncommitted source is present\n' >&2
    exit 2
  fi
  SUBSTITUTIONS="${SUBSTITUTIONS:+$SUBSTITUTIONS,}_ALLOW_DIRTY=1"
  extra=(--substitutions="$SUBSTITUTIONS")
fi

exec gcloud builds submit \
  --project="$project" \
  --config="$ROOT/cloudbuild.yaml" \
  "${extra[@]}" \
  "$ROOT"
