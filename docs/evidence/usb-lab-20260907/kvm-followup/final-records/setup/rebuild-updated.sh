set -euo pipefail
cd /lab/product-updated
export BEAMO_GO_BIN=/lab/native-toolchain/go/bin/go GOCACHE=/lab/native-toolchain/cache GOPATH=/lab/native-toolchain/gopath GOTOOLCHAIN=local
(cd desktop; "$BEAMO_GO_BIN" test -race ./...; "$BEAMO_GO_BIN" vet ./...; CGO_ENABLED=0 GOOS=windows GOARCH=amd64 "$BEAMO_GO_BIN" test -c -o /lab/setup/desktop-tests-updated.exe .)
bash scripts/build-desktop.sh
bash scripts/build-iso.sh
bash scripts/build-usb-image.sh
sha256sum dist/*.iso dist/*.img /lab/setup/desktop-tests-updated.exe
