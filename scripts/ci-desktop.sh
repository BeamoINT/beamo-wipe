#!/usr/bin/env bash
# Native Linux tests plus Windows compilation on the isolated hosted runner.
set -euo pipefail
ROOT="$(CDPATH='' cd -- "$(dirname "$0")/.." && pwd)"
TOOL_ROOT="$(mktemp -d /tmp/beamo-wipe-go.XXXXXX)"
trap 'rm -rf -- "$TOOL_ROOT"' EXIT
apt-get update -qq
apt-get install -y -qq --no-install-recommends ca-certificates python3 git gcc libc6-dev util-linux
python3 - "$TOOL_ROOT" <<'PY'
import hashlib,pathlib,sys,urllib.request
root=pathlib.Path(sys.argv[1]);path=root/'go.tar.gz'
url='https://go.dev/dl/go1.26.8.linux-amd64.tar.gz'
expected='d0f743b33e8d8945e6b1f432edd15785c70507121d6e2a723b21285eddf8b57b'
with urllib.request.urlopen(url,timeout=60) as response,path.open('wb') as output:
    while chunk:=response.read(1024*1024): output.write(chunk)
if hashlib.sha256(path.read_bytes()).hexdigest()!=expected: raise SystemExit('Go toolchain checksum mismatch')
PY
tar -xzf "$TOOL_ROOT/go.tar.gz" -C "$TOOL_ROOT"
export BEAMO_GO_BIN="$TOOL_ROOT/go/bin/go" GOCACHE="$TOOL_ROOT/cache" GOTOOLCHAIN=local
export BEAMO_DESKTOP_NATIVE_INVENTORY_TEST=1
cd "$ROOT/desktop"
"$BEAMO_GO_BIN" test -race ./...
"$BEAMO_GO_BIN" vet ./...
# Cross-compilation checks platform-specific test code without claiming native
# Windows execution. Run this test executable on a separate Windows worker.
GOOS=windows GOARCH=amd64 "$BEAMO_GO_BIN" test -c -o "$TOOL_ROOT/desktop-windows.test.exe"
"$BEAMO_GO_BIN" test -run='^$' -fuzz=FuzzBootOption -fuzztime=15s -parallel=2
"$ROOT/scripts/build-desktop.sh"
