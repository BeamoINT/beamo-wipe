#!/usr/bin/env bash
# Build portable launchers; never enumerate devices or request a restart.
set -euo pipefail
ROOT="$(CDPATH='' cd -- "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
GO_BIN="${BEAMO_GO_BIN:-go}"
if [[ "$($GO_BIN version | awk '{print $3}')" != go1.26.5 ]]; then
  echo "Launcher builds require Go 1.26.5 (see scripts/ci-desktop.sh)." >&2
  exit 2
fi
VERSION="$(PYTHONPATH="$ROOT/src" python3 -c 'import beamo_wipe; print(beamo_wipe.__version__)')"
SOURCE="$(git rev-parse HEAD)"
OUT="$ROOT/dist/desktop"
mkdir -p "$OUT"
export CGO_ENABLED=0 GOTOOLCHAIN=local
cd "$ROOT/desktop"
FLAGS="-s -w -X main.version=$VERSION -X main.sourceCommit=$SOURCE"
GOOS=linux GOARCH=amd64 "$GO_BIN" build -trimpath -buildvcs=false -ldflags="$FLAGS" -o "$OUT/Start Beamo Wipe Linux" .
GOOS=windows GOARCH=amd64 "$GO_BIN" build -trimpath -buildvcs=false -ldflags="$FLAGS -H=windowsgui" -o "$OUT/Start Beamo Wipe.exe" .
python3 - "$OUT" "$VERSION" "$SOURCE" <<'PY'
import hashlib,json,pathlib,sys
root=pathlib.Path(sys.argv[1])
files={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.iterdir()) if p.name in {'Start Beamo Wipe Linux','Start Beamo Wipe.exe'}}
if len(files)!=2: raise SystemExit('missing desktop executable')
(root/'desktop-build.json').write_text(json.dumps({'version':sys.argv[2],'source_commit':sys.argv[3],'go':'go1.26.5','files':files},sort_keys=True,indent=2)+'\n')
PY
echo "Built Windows and Linux desktop launchers. Runtime and firmware tests remain separate gates."
