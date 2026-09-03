# Release verification

Each release publishes a machine-readable manifest that links the ISO to its source, inputs, and evidence.

## Artifacts (per release)

| File | Purpose | Retention | Location |
| --- | --- | --- | --- |
| `beamo-wipe-0.2.0-amd64.iso` | Bootable live image (hybrid BIOS+UEFI) | GCS per `cloudbuild.yaml` | `dist/`, `gs://beamo-wipe_cloudbuild/releases/${BUILD_ID}/` |
| `beamo-wipe-0.2.0-amd64.iso.sha256` | SHA256 sidecar (`<sha>  <name>`) | same | `dist/` alongside ISO |
| `beamo-wipe-0.2.0-amd64.manifest.json` | Release provenance (this doc) | same | `dist/` |
| `beamo-wipe-0.2.0-amd64.manifest.json.sha256` | Manifest checksum | same | `dist/` |
| `SHA256SUMS` | `sha256sum` of ISO + manifest | same | `dist/` |

All are under `dist/` after `./scripts/build-iso.sh`; Cloud Build uploads to `gs://beamo-wipe_cloudbuild/releases/${BUILD_ID}/`.

## What the manifest contains

`dist/beamo-wipe-*.manifest.json` (`schema_version: 1`):

- `source`: `commit` (40-hex), `tag`, `dirty`/`dirty_files`, `branch`, `remote_url`
- `build`: `container_image` (`debian:bookworm`), runner, `build_commands`, `built_at` UTC
- `dependencies`: `pyproject.toml`/`THIRD_PARTY.md`/`NOTICE` hashes, `live_build_inputs` (bootstrap/binary/package-lists/hooks/src hashes), `nwipe` (`version` `0.42`, `commit` `6082bde…`, `pinned_path`)
- `artifact`: `iso_name`, `iso_size_bytes`, `iso_sha256`, `iso_sha256_sidecar`
- `test_evidence`: pytest (xvfb 72 DPI, `BEAMO_WIPE_DRY_RUN=1`), preview (`--web`/`--console`), QEMU (disposable qcow2 per `docs/qemu-verify.md`)
- `hardware_limits`: supported/unsupported/degraded (from `docs/compatibility-matrix.md`), `known_issues`, `license` (wrapper GPL-3.0+, nwipe GPL-2.0), `prior_stable` (`0.1.0` `8a531d…` `3b4c01f`), `rollback`, `verification`

Top-level `_manifest_sha256` is the SHA256 of the canonical JSON (sorted keys, no whitespace).

## Consumer verification

```sh
# From the release directory (where ISO and manifest were downloaded):
sha256sum -c beamo-wipe-0.2.0-amd64.iso.sha256
sha256sum -c beamo-wipe-0.2.0-amd64.manifest.json.sha256
# Or from repo root:
sha256sum -c dist/beamo-wipe-0.2.0-amd64.iso.sha256
sha256sum -c dist/beamo-wipe-0.2.0-amd64.manifest.json.sha256
sha256sum -c dist/SHA256SUMS   # checks both

# Verify manifest itself (fails closed on dirty/placeholder):
python3 - <<'PY'
import pathlib, sys
sys.path.insert(0, "src")
from beamo_wipe.release_manifest import verify_manifest
verify_manifest(pathlib.Path("dist/beamo-wipe-0.2.0-amd64.manifest.json"))
print("manifest OK")
PY

# Inspect provenance without trusting ISO:
python3 -m json.tool dist/beamo-wipe-0.2.0-amd64.manifest.json | head -n 60
# Check source commit matches tag:
git rev-parse HEAD  # should equal manifest source.commit
git status --porcelain  # should be clean for a release
```

If any `sha256sum -c` fails, do not use the ISO. If `verify_manifest` raises `uncommitted source state`, `placeholder provenance`, `missing checksum`, or `unexpected nwipe version`, the build is not a release (generate with `ALLOW_DIRTY=1` only for local dev).

## Build failure (fail-closed)

`scripts/generate-release-manifest.sh` and `src/beamo_wipe/release_manifest.py` abort (exit 2) on:

- `git status --porcelain` not empty (unless `ALLOW_DIRTY=1`)
- `git rev-parse HEAD` not 40-hex
- `PLACEHOLDER`/`TODO`/`CHANGEME` in `src/beamo_wipe/__init__.py` or live-build `binary`
- Missing ISO or `sha256_file` empty
- `NWIPE_PINNED_VERSION != "0.42"` or `commit` not 40-hex
- `pyproject.toml` version drift vs `__version__`

## Immutability and signing

- **Immutability:** `cloudbuild.yaml` `artifacts.objects` to `gs://beamo-wipe_cloudbuild/releases/${BUILD_ID}` (bucket versioning/retention per project).
- **Signing:** Not configured (SHA256 sidecar only). Verify via `SHA256SUMS` and manifest `_manifest_sha256`. If `cosign`/`gpg` is added later, the manifest `verification.signing` field will be updated.

## Reproducibility

Live-build is not bit-reproducible due to `apt` timestamps and `squashfs` ordering; the manifest records `live_build_inputs` hashes and `container_image` for traceability, not for `diff` equality. Use `iso_sha256` + `source.commit` as the release identity.

## Prior stable and rollback

Prior stable: `beamo-wipe-0.1.0-amd64.iso` `8a531d35c437d858512ccbba20913cd7dbd9237cc9a2e2a1b7935ba9d9781c55` commit `3b4c01f` tag `v0.1.0`. Rollback: `git checkout 3b4c01f` or `git revert <commit>`.

Never publish or promote the ISO without explicit operator authorization after `CI` (`lint`→`test`→`negative-test`→`iso`→`manifest`) and Cloud Build both pass.
