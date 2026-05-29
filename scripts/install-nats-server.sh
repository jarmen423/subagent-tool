#!/usr/bin/env bash
set -euo pipefail

VERSION="2.10.24"
ROOT="${HOME}/.cursor/subagents/bin"
mkdir -p "$ROOT"

ARCH="$(uname -m)"
OS="$(uname -s | tr '[:upper:]' '[:lower:]')"
case "$ARCH-$OS" in
  x86_64-linux) ASSET="nats-server-v${VERSION}-linux-amd64.tar.gz" ;;
  aarch64-linux) ASSET="nats-server-v${VERSION}-linux-arm64.tar.gz" ;;
  x86_64-darwin) ASSET="nats-server-v${VERSION}-darwin-amd64.tar.gz" ;;
  arm64-darwin) ASSET="nats-server-v${VERSION}-darwin-arm64.tar.gz" ;;
  *) echo "Unsupported platform: $ARCH $OS" >&2; exit 1 ;;
esac

URL="https://github.com/nats-io/nats-server/releases/download/v${VERSION}/${ASSET}"
TMP="$(mktemp -d)"
curl -L "$URL" -o "$TMP/$ASSET"
tar -xzf "$TMP/$ASSET" -C "$TMP"
install -m 755 "$TMP/nats-server-v${VERSION}-$OS-$ARCH/nats-server" "$ROOT/nats-server"
echo "Installed to $ROOT/nats-server"
