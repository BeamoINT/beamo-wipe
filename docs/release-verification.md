# Release verification

Each release publishes a machine-readable manifest that links the ISO to its source, inputs, and evidence.

## Artifacts (per release)

| File | Purpose | Retention | Location |
| --- | --- | --- | --- |
| `beamo-wipe-0.2.1-amd64.iso` | Bootable live image (hybrid BIOS+UEFI) | Operator-defined after authorization | local `dist/` until separately published |
| `beamo-wipe-0.2.1-amd64.iso.sha256` | SHA256 sidecar (`<sha>  <name>`) | same | `dist/` alongside ISO |
| `beamo-wipe-0.2.1-amd64.manifest.json` | Release provenance (this doc) | same | `dist/` |
| `beamo-wipe-0.2.1-amd64.manifest.json.sha256` | Manifest checksum | same | `dist/` |
| `SHA256SUMS` | `sha256sum` of ISO + manifest | same | `dist/` |

All are under `dist/` after `./scripts/build-iso.sh`. Cloud Build discards them by default. An explicitly authorized `./scripts/ci-cloud.sh --publish-release` uploads only after the full QEMU gate and writes `RELEASE_COMPLETE.txt` last under a unique build-ID path.

## What the manifest contains

`dist/beamo-wipe-*.manifest.json` (`schema_version: 1`):

- `source`: `commit` (40-hex), `tag`, `dirty`/redacted `dirty_count`, `branch`, canonical `remote_url`
- `build`: content-addressed `debian:bookworm@sha256:…`, runner, `build_commands`, `built_at` UTC
- `dependencies`: `pyproject.toml`/`THIRD_PARTY.md`/`NOTICE` hashes, `live_build_inputs` (bootstrap/binary/package-lists/hooks/src hashes), `nwipe` (`version` `0.42`, `commit` `6082bde…`, `pinned_path`)
- `artifact`: `iso_name`, `iso_size_bytes`, `iso_sha256`, `iso_sha256_sidecar`
- `test_evidence`: pytest (xvfb 72 DPI, `BEAMO_WIPE_DRY_RUN=1`), preview (`--web`/`--console`), QEMU (disposable qcow2 per `docs/qemu-verify.md`)
- `hardware_limits`: supported/unsupported/degraded (from `docs/compatibility-matrix.md`), `known_issues`, `license` (wrapper GPL-3.0+, nwipe GPL-2.0), `prior_stable` (`0.2.0` `62437e…` `5b3b7af…`), `rollback`, `verification`

Top-level `_manifest_sha256` is the SHA256 of the canonical JSON (sorted keys, no whitespace).

## Consumer verification

```sh
# From the release directory (where ISO and manifest were downloaded):
sha256sum -c beamo-wipe-0.2.1-amd64.iso.sha256
sha256sum -c beamo-wipe-0.2.1-amd64.manifest.json.sha256
# From repo root, change directory because each sidecar intentionally binds a
# bare filename rather than an arbitrary path:
(cd dist && sha256sum -c beamo-wipe-0.2.1-amd64.iso.sha256)
(cd dist && sha256sum -c beamo-wipe-0.2.1-amd64.manifest.json.sha256)
(cd dist && sha256sum -c SHA256SUMS)

# From a checked-out v0.2.1 source tree, place the downloaded release files
# together under dist/, then verify the manifest and sibling ISO (fails closed
# on dirty/placeholder, path escape, size, content, or sidecar mismatch):
python3 - <<'PY'
import pathlib, sys
sys.path.insert(0, "src")
from beamo_wipe.release_manifest import verify_manifest
verify_manifest(pathlib.Path("dist/beamo-wipe-0.2.1-amd64.manifest.json"))
print("manifest OK")
PY

# Inspect provenance without trusting ISO:
python3 -m json.tool dist/beamo-wipe-0.2.1-amd64.manifest.json | head -n 60
# Check source commit matches tag:
git rev-parse HEAD  # should equal manifest source.commit
git status --porcelain  # should be clean for a release
```

`verify_manifest` requires the manifest to record only the canonical bare ISO filename, resolves that file beside the manifest, hashes the actual bytes, checks its size, and validates both exact sidecar lines. This makes the release directory relocatable without accepting an embedded absolute path or traversal. If any check fails, do not use the ISO.

## Build failure (fail-closed)

`scripts/generate-release-manifest.sh` and `src/beamo_wipe/release_manifest.py` abort (exit 2) on:

- `git status --porcelain` not empty (unless `ALLOW_DIRTY=1`)
- `git rev-parse HEAD` not 40-hex
- `PLACEHOLDER`/`TODO`/`CHANGEME` in `src/beamo_wipe/__init__.py` or live-build `binary`
- Missing ISO or `sha256_file` empty
- `NWIPE_PINNED_VERSION != "0.42"` or `commit` not 40-hex
- `pyproject.toml` version drift vs `__version__`
- Manifest/ISO sidecar mismatch, ISO path traversal, ISO byte/size mismatch, or unexpected origin URL

## Immutability and signing

- **Immutability:** Verification output is ephemeral by default. Explicit publication uses a unique Cloud Build UUID path, generation-match-zero uploads, remote byte verification, and a completion marker written last. The bucket also provides seven-day soft deletion; release paths are never reused.
- **Signing:** Not configured. SHA256 detects corruption but does not authenticate the publisher. Do not treat an unsigned image as tamper-resistant; public promotion remains blocked without an explicit operator decision.

## Reproducibility

Live-build is not bit-reproducible due to `apt` timestamps and `squashfs` ordering; the manifest records `live_build_inputs` hashes and `container_image` for traceability, not for `diff` equality. Use `iso_sha256` + `source.commit` as the release identity.

## Prior stable and rollback

Prior stable: `beamo-wipe-0.2.0-amd64.iso` `62437ec152a5b2ffc7c89fc503a7659d561c32699376a8851ab838f665491c74` commit `5b3b7afa6c448ee01269c9497c1c93e8e83733c1` tag `v0.2.0`. Rollback: `git checkout 5b3b7afa6c448ee01269c9497c1c93e8e83733c1` or `git revert <commit>`.

Never publish or promote the ISO without explicit operator authorization after `CI` (`lint`→`test`→`negative-test`→`iso`→`manifest`) and Cloud Build both pass.
