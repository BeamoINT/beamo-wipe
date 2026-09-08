#!/bin/bash
set -Eeuo pipefail
mkdir -m 700 /lab/native-toolchain
cd /lab/native-toolchain
curl --fail --location --retry 3 https://go.dev/dl/go1.26.5.linux-amd64.tar.gz -o go.tar.gz
printf '%s  %s\n' 5c2c3b16caefa1d968a94c1daca04a7ca301a496d9b086e17ad77bb81393f053 go.tar.gz | sha256sum -c -
tar xzf go.tar.gz
cd /lab/product/desktop
CGO_ENABLED=0 GOOS=windows GOARCH=amd64 GOTOOLCHAIN=local /lab/native-toolchain/go/bin/go test -c -o /lab/setup/desktop-tests.exe .
sha256sum /lab/setup/desktop-tests.exe > /lab/setup/desktop-tests.sha256
