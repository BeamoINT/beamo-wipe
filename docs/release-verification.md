# Release verification

Each release publishes a machine-readable manifest that links the ISO to its source, inputs, and evidence.

## Artifacts (per release)

| File | Purpose | Retention | Location |
| --- | --- | --- | --- |
| `beamo-wipe-0.2.7-amd64.iso` | Bootable live image (hybrid BIOS+UEFI) | Operator-defined after authorization | local `dist/` until separately published |
| `beamo-wipe-0.2.7-amd64.iso.sha256` | SHA256 sidecar (`<sha>  <name>`) | same | `dist/` alongside ISO |
| `beamo-wipe-0.2.7-amd64.manifest.json` | Release provenance (this doc) | same | `dist/` |
| `beamo-wipe-0.2.7-amd64.manifest.json.sha256` | Manifest checksum | same | `dist/` |
| `SHA256SUMS` | `sha256sum` of ISO + manifest | same | `dist/` |
| `beamo-wipe-0.2.7-amd64.img` | Desktop-readable FAT32 USB image with BIOS/UEFI boot | same | `dist/` after the USB-image builder |
| `beamo-wipe-0.2.7-amd64.img.sha256` | USB image checksum | same | alongside image |
| `beamo-wipe-0.2.7-amd64.img.json` | USB image size, layout, checksum, and source ISO checksum | same | alongside image |

The ISO artifacts are under `dist/` after `./scripts/build-iso.sh`. The hosted
QEMU phase also runs `./scripts/build-usb-image.sh` on its isolated amd64 Linux
worker. It boots the resulting `.img` through BIOS, UEFI, and enrolled Secure
Boot firmware. The publisher requires these USB boot logs and verifies the
image metadata against the actual image and source ISO before any upload.
These new image artifacts are development additions; they do not retroactively
change the previously published v0.2.5 release.

Cloud Build discards artifacts by default. An explicitly authorized
`./scripts/ci-cloud.sh --publish-release` uploads only after the full QEMU gate
and writes `RELEASE_COMPLETE.txt` last under a unique build-ID path.

## What the manifest contains

`dist/beamo-wipe-*.manifest.json` (`schema_version: 2`):

- `source`: `commit` (40-hex), `tag`, `dirty`/redacted `dirty_count`, `branch`, canonical `remote_url`
- `build`: content-addressed `debian:bookworm@sha256:…`, runner, `build_commands`, `built_at` UTC, `release_build_id` (Cloud Build UUID or explicit `local` for development)
- Live image identity is the same payload written once to `/usr/share/beamo-wipe/build-identity.json` (`source_commit`, `source_sha256`, `build_id`, `source_dirty`). Runtime never infers commit from git. Missing or invalid identity is `unavailable`; dirty trees are `dirty`; `local` is `development`; a matching UUID is `production`. ISO format never implies a trusted wall clock.
- `dependencies`: `pyproject.toml`/`THIRD_PARTY.md`/`NOTICE` hashes, `live_build_inputs` (bootstrap/binary/package-lists/hooks/src hashes), `nwipe` (`version` `0.42`, `commit` `6082bde…`, `pinned_path`)
- `artifact`: `iso_name`, `iso_size_bytes`, `iso_sha256`, `iso_sha256_sidecar`
- `test_evidence`: measured gate results (see below), never script paths
- `installed_packages`: deterministic inventory of the image (see below)
- `hardware_limits`: supported/unsupported/degraded (from `docs/compatibility-matrix.md`), `known_issues`, `license` (wrapper GPL-3.0+, nwipe GPL-2.0), `prior_stable` (`0.2.0` `62437e…` `5b3b7af…`), `rollback`, `verification`

## Measured release evidence

`src/beamo_wipe/verification_evidence.py` is the schema owner. Every release
manifest records what was *executed*:

- **Gate receipts** (`beamo-wipe-gate-receipt/1`), one per gate: the executed
  command, status (`pass`/`fail`/`skip`), measured counts
  (`passed`/`failed`/`errors`/`skipped`/`xfailed`/`deselected`/`total`, with
  `total` equal to the sum of its parts), the sorted skip/xfail list with a
  reason per entry, the environment (stable facts only: platform, arch,
  toolchain versions, runner — never hostnames, users, paths, or secrets),
  second-precision UTC timestamps, the source commit and build identity, the
  SHA-256 of the immutable execution log, and a receipt digest over the
  canonical JSON. Receipts whose counts, digests, timestamps, or secrets
  checks fail are rejected as tampered.
- **Required vs optional gates.** Required: `lint`, `tests`, `preview`,
  `negative`, `iso`, `qemu` — all must be present with status `pass`, or
  verification fails (a skipped or failed required gate fails; a missing one
  fails as partial evidence). Optional: `desktop-launchers` — may pass or
  skip with a reason; a failed optional gate still fails. Unknown gate names
  are rejected so a renamed step cannot silently leave the record.
- **Installed-package inventory** (`beamo-wipe-package-inventory/1`): every
  installed package with name, version, architecture, and source-package
  provenance, sorted by name with a canonical digest, plus the image-level
  apt-source mirrors. dpkg status carries no per-package repository origin,
  so provenance is the source-package name plus the configured sources,
  stated as such. Two images compare by inventory digest first, source
  inputs second.
- **Fail-closed verification.** `verify_manifest` rejects manifests with
  unmeasured evidence, missing/failed/tampered receipts, evidence bound to
  another commit or build identity, or a missing/tampered package inventory.
  Generation in strict mode refuses to run without gate receipts and an
  inventory (`missing release evidence: …`).

The hosted gate automatically records execution through
`beamo_wipe.ci_evidence` into `dist/evidence/`. The test receipt counts actual
pytest JUnit outcomes; other required receipts count one executed phase,
not individual assertions. Every phase receives the same Cloud Build ID.
The collector rejects stale files and binds receipts to retained log bytes.
The QEMU phase reads package provenance directly from the mounted ISO squashfs.

ISO construction first creates preliminary artifact provenance using
`verify_build_manifest`. It validates source identity and actual artifact
bytes but cannot claim future QEMU success. After QEMU passes, the collector
requires all six passing receipts and the package inventory, finalizes the
manifest, and runs the strict `verify_manifest`. Preliminary provenance is
never accepted by that release verifier or by the publisher.

For individual evidence inspection, use the module CLI (run where each gate executes; the
JUnit XML comes from `pytest --junitxml`, whose hostname/timestamps/paths
are stripped by the parser and never enter the receipt):

```sh
python3 -m beamo_wipe.verification_evidence parse-junit \
  --gate tests --status pass --exec-command "python3 -m pytest" \
  --commit "$(git rev-parse HEAD)" --build-id "${BUILD_ID:-local}" \
  --xml tests.xml --log-sha256 "$(sha256sum tests.log | awk '{print $1}')" \
  --env platform=linux --env arch=x86_64 --env runner=cloudbuild \
  --started-at 2026-09-11T00:00:00Z --ended-at 2026-09-11T00:05:00Z \
  --out receipts/tests.receipt.json
python3 -m beamo_wipe.verification_evidence parse-dpkg-status \
  --status-file "$SQUASH/var/lib/dpkg/status" \
  --collected-from "squashfs var/lib/dpkg/status" \
  --apt-source https://deb.debian.org/debian/ \
  --apt-source https://security.debian.org/ \
  --commit "$(git rev-parse HEAD)" --generated-at 2026-09-11T00:00:00Z \
  --out dist/beamo-wipe-0.2.7-amd64.packages.json
python3 -m beamo_wipe.verification_evidence verify-receipts \
  --receipt receipts/lint.receipt.json --receipt receipts/tests.receipt.json
```

Top-level `_manifest_sha256` is the SHA256 of the canonical JSON (sorted keys, no whitespace).

## Consumer verification

```sh
# From the release directory (where ISO and manifest were downloaded):
sha256sum -c beamo-wipe-0.2.7-amd64.iso.sha256
sha256sum -c beamo-wipe-0.2.7-amd64.manifest.json.sha256
# From repo root, change directory because each sidecar intentionally binds a
# bare filename rather than an arbitrary path:
(cd dist && sha256sum -c beamo-wipe-0.2.7-amd64.iso.sha256)
(cd dist && sha256sum -c beamo-wipe-0.2.7-amd64.manifest.json.sha256)
(cd dist && sha256sum -c SHA256SUMS)

# From a checked-out v0.2.7 source tree, place the downloaded release files
# together under dist/, then verify the manifest and sibling ISO (fails closed
# on dirty/placeholder, path escape, size, content, or sidecar mismatch):
python3 - <<'PY'
import pathlib, sys
sys.path.insert(0, "src")
from beamo_wipe.release_manifest import verify_manifest
verify_manifest(pathlib.Path("dist/beamo-wipe-0.2.7-amd64.manifest.json"))
print("manifest OK")
PY

# Inspect provenance without trusting ISO:
python3 -m json.tool dist/beamo-wipe-0.2.7-amd64.manifest.json | head -n 60
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

## Immutability and publisher signatures

- **Immutability:** Verification output is ephemeral by default. Explicit publication uses a unique Cloud Build UUID path, generation-match-zero uploads, remote byte verification, and a completion marker written last. The bucket also provides seven-day soft deletion; release paths are never reused.
- **Signing:** New publication through this publisher requires a detached Ed25519 sidecar
  (`beamo-wipe-<version>-amd64.manifest.json.sig`) over the exact manifest
  bytes, so one signature covers the artifact hashes, build identity,
  evidence/receipt hashes, and version metadata together. The publisher
  signs after manifest verification and verifies the sidecar before upload;
  without signing material, or against a retired/revoked key, publication
  refuses instead of publishing unsigned. SHA256 alone detects corruption
  but does not authenticate the publisher: do not treat an unsigned image
  as tamper-resistant, and public promotion stays blocked without an
  explicit operator decision.

### What release signing is not (Secure Boot distinction)

Release signing is **not Secure Boot**. It proves *who published this file*
(the Beamo release key held by the operator). It does not prove what a
machine may boot, confer firmware trust, bless image contents beyond their
hashes, or say anything about a wiped disk. Our image may be unsigned for
Secure Boot purposes and we ship no circumvention tools
(see `docs/claims.md`). Confusing the two would be a category error: a valid
publisher signature never means "safe to boot without checking firmware",
and a Secure Boot refusal never means "the download was tampered with".

### Threat model and limitations

- **Stops:** silent substitution of ISO/manifest bytes in transit or at
  rest (digest mismatch fails), publication by anyone without the release
  key, replay of an older signed release as current (acceptance floor),
  use of a retired or compromised key after revocation.
- **Does not stop:** compromise of the release key *before* revocation
  (mitigated by custody rules and fast revocation), a malicious publisher
  with legitimate access (mitigated by clean-tree/tag/record review, never
  by cryptography), attacks on the downloader's machine, or weak
  out-of-band fingerprint checks. Signatures authenticate the publisher,
  not the wipe result.

### Key custody, rotation, revocation (summary)

Full ceremony lives in `packaging/release-keys/KEYS.md`. In short: private
material exists only in the operator's offline ceremony record and one
Secret Manager secret readable by the release identity alone; it is never
committed, printed, or attached to pull-request builds, and `cloudbuild.yaml`
stays secret-free by policy (pinned by test) because a pull request can
rewrite that file. Rotation keeps both keys active for at most one release,
then retires the predecessor. Revocation is a committed status change that
fails verification even for cryptographically valid signatures; never
delete a revoked entry. Production key creation and rotation need separate
operator authorization — code and tests only ever use ephemeral keys.

### Verify a release signature (copyable)

From the release directory (manifest, sidecar, and the registry from a
trusted source tree):

```sh
python3 - <<'PY'
import json, pathlib, sys
sys.path.insert(0, "src")
from beamo_wipe.release_signing import load_key_registry, verify_release_acceptance
manifest = pathlib.Path("beamo-wipe-0.2.7-amd64.manifest.json").read_bytes()
sidecar = json.loads(pathlib.Path("beamo-wipe-0.2.7-amd64.manifest.json.sig").read_text())
registry = load_key_registry(json.loads(pathlib.Path("packaging/release-keys/keys.json").read_text()))
result = verify_release_acceptance(manifest, sidecar, registry, min_version="0.2.7")
print("signature ok:", result["key_id"], "version:", result["beamo_wipe_version"])
PY
```

Expected success: `signature ok: <16-hex-key-id> version: 0.2.7`.
Expected failures (each raises `RuntimeError`, never a partial pass):

- altered manifest or sidecar bytes → `digest mismatch` / `different manifest bytes` / `signature is invalid`
- wrong verification key → `not a known publisher key` / `different key`
- missing sidecar or registry entry → `not a known publisher key` / `cannot be read`
- retired key → `is not active (retired)`; compromised key → `is revoked`
- older signed release against the floor → `below the acceptance floor`

Or use the CLI: `python3 -m beamo_wipe.release_signing verify --manifest … --signature … --registry … --min-version 0.2.7`.

## Reproducibility

Live-build is not bit-reproducible due to `apt` timestamps and `squashfs` ordering; the manifest records `live_build_inputs` hashes and `container_image` for traceability, not for `diff` equality. Use `iso_sha256` + `source.commit` as the release identity.

## Prior stable and rollback

Prior stable: `beamo-wipe-0.2.0-amd64.iso` `62437ec152a5b2ffc7c89fc503a7659d561c32699376a8851ab838f665491c74` commit `5b3b7afa6c448ee01269c9497c1c93e8e83733c1` tag `v0.2.0`. Rollback: `git checkout 5b3b7afa6c448ee01269c9497c1c93e8e83733c1` or `git revert <commit>`.

Never publish or promote the ISO without explicit operator authorization after `CI` (`lint`→`test`→`negative-test`→`iso`→`manifest`) and Cloud Build both pass.
