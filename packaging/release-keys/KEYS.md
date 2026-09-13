# Beamo Wipe release signing keys

Public-key distribution for publisher-authenticated releases. This directory
carries **public keys only**. Private signing material must never be
committed, printed, pasted into tickets, or attached to pull-request builds.
Production key creation and rotation need separate operator authorization;
nothing here authorizes either.

## Approved first-key setup

On 2026-09-13 UTC, the product owner explicitly authorized automated GCP
signing setup in place of the offline two-operator ceremony for key
`93caaf7ca93eff4d`. Its SHA-256 public fingerprint is
`93caaf7ca93eff4d7fa1c16e360f9d6aa17ced0155a56d4cf89d8f6d429e66f7`.
The fingerprint was also provided directly to the owner in the release task.

For this key, private material was generated in process memory and stored
as one versioned Secret Manager secret. No offline copy was made. Loss of
that secret requires an explicitly authorized replacement key. A dedicated
release publisher identity has secret access; normal PR/main workers do not.
A separate operator-invoked publisher job retrieves artifacts only after a
successful full qualification build and verifies their source, hashes and
execution receipts before signing. The normal `cloudbuild.yaml` remains
secret-free. This approval applies to this first key only; future rotation
still requires separate authorization.

## Registry

`keys.json` (`beamo-wipe-release-keys/1`) maps key id (first 16 hex chars of
the SHA-256 of the 32 raw Ed25519 public bytes) to:

- `fingerprint`: full hex SHA-256 of the public bytes (must match recompute).
- `public_key`: base64 of the 32 raw public bytes.
- `status`: `active`, `retired`, or `revoked`.

An empty registry verifies nothing: every signature check fails closed until
an operator-authorized commit adds a key. Retired and revoked keys stay
listed so old signatures fail with a precise reason.

## Generation ceremony (operator only, offline machine)

1. Two operators present. Machine offline, screen lock on, no clipboard sync.
2. `python3 -m beamo_wipe.release_signing keygen --private-out /secure/rel-2026.priv --public-out /secure/rel-2026.pub`
3. Confirm the private file is mode `0600` and owned by the operator.
4. Record the printed key id and fingerprint in the ceremony log (paper or
   the append-only ops log, never this repo).
5. Store the private file in Secret Manager as one versioned secret readable
   only by the release identity; enable rotation reminders.
6. Commit ONLY the `public_key`, `fingerprint`, and `status: active` entry
   to `keys.json` via reviewed pull request. Announce the fingerprint
   out-of-band (second channel) before first use.

## Custody and least privilege

- The private file exists in exactly two places: the offline ceremony
  record (sealed) and Secret Manager (one secret, release identity only).
- Cloud Build triggers and pull-request builds never receive it:
  `cloudbuild.yaml` is secret-free by policy (pinned by test), and only an
  operator-invoked release submission provides the key file path to the
  publisher. Least privilege means no other identity can read the secret
  and no other step can use it.
- Developers and CI verify with the public registry only.

## Rotation

1. Generate the successor key by the ceremony above.
2. Commit its registry entry as `active` alongside the current key (both
   active during the overlap window, at most one release).
3. Sign the next release with the successor; confirm verification.
4. Commit the predecessor as `retired`. Retired keys verify nothing new but
   keep old signatures diagnosable.

## Revocation

On suspected compromise: commit the key as `revoked` immediately (review
after the fact is acceptable for this one change), then rotate. Revoked
keys fail verification even when the cryptography is valid. Publish a short
incident note naming the key id, the last release it signed, and the
successor. Never delete a revoked entry: deletion would turn precise
rejection into an unknown-key shrug.

## Recovery

- Lost private file, key still active: rotate; the sealed ceremony record
  is the fallback only if the secret itself is intact.
- Lost secret and ceremony record: the key is dead — revoke its entry,
  rotate, and re-sign the current release with the successor.
- Registry file damaged: rebuild entries from the ceremony log and the
  out-of-band announcements; fingerprints must recompute exactly.

## Incident response

1. Freeze publication (`_PUBLISH_RELEASE` stays false; no manual submits).
2. Revoke the affected key id in `keys.json`.
3. Scope: which releases did it sign (manifest `key_id` is recorded).
4. Rotate, re-sign the current release, verify, and only then resume.
5. Write the incident note with dates, key ids, and the exact window.
