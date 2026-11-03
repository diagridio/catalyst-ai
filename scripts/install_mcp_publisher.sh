#!/usr/bin/env bash
# Install a pinned mcp-publisher, the official MCP Registry CLI, into a directory.
#
# Pinned by version AND by the SHA-256 of the release tarball, so neither a new
# upstream release nor a replaced asset can change what CI runs. The hashes are
# copied from the release's registry_<version>_checksums.txt. To upgrade, change
# the version and both hashes together.
#
# Linux only: both workflows that call this run on ubuntu runners.
#
# Usage: scripts/install_mcp_publisher.sh <install-dir>

set -euo pipefail

readonly MCP_PUBLISHER_VERSION="1.8.1"
readonly SHA256_LINUX_AMD64="a06c9096dcb9727c13555b6be26c7effa707b01f06a4c561ba7a3635443cf2cc"
readonly SHA256_LINUX_ARM64="8dd75a6cf6845688b5d4e46df58d3ca26d5c8d233bb0626606e1db82c5e883e4"
readonly RELEASES="https://github.com/modelcontextprotocol/registry/releases/download"

dest="${1:?usage: $0 <install-dir>}"

if [ "$(uname -s)" != "Linux" ]; then
  echo "install_mcp_publisher.sh supports Linux only, got $(uname -s)" >&2
  exit 1
fi
case "$(uname -m)" in
  x86_64) arch=amd64; want="$SHA256_LINUX_AMD64" ;;
  aarch64 | arm64) arch=arm64; want="$SHA256_LINUX_ARM64" ;;
  *) echo "unsupported architecture $(uname -m)" >&2; exit 1 ;;
esac

asset="mcp-publisher_linux_${arch}.tar.gz"
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

curl -fsSL --retry 3 -o "$work/$asset" "$RELEASES/v$MCP_PUBLISHER_VERSION/$asset"
echo "$want  $work/$asset" | sha256sum --check --strict -

mkdir -p "$dest"
tar -xzf "$work/$asset" -C "$work" mcp-publisher
install -m 0755 "$work/mcp-publisher" "$dest/mcp-publisher"
"$dest/mcp-publisher" --version
