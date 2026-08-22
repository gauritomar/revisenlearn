#!/usr/bin/env bash
#
# Generate assets/AppIcon.icns from assets/logo.png using only macOS built-ins
# (spec §14.3). No packaging framework, no dependencies.
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="${1:-$REPO_ROOT/assets/logo.png}"
OUT="$REPO_ROOT/assets/AppIcon.icns"
ICONSET="$(mktemp -d)/AppIcon.iconset"

[ -f "$SRC" ] || { echo "Source image not found: $SRC" >&2; exit 1; }
command -v sips     >/dev/null || { echo "sips not found (macOS only)" >&2; exit 1; }
command -v iconutil >/dev/null || { echo "iconutil not found (macOS only)" >&2; exit 1; }

mkdir -p "$ICONSET"

# macOS wants each size at 1x and 2x.
for size in 16 32 128 256 512; do
  sips -z "$size" "$size" "$SRC" \
       --out "$ICONSET/icon_${size}x${size}.png" >/dev/null
  double=$((size * 2))
  sips -z "$double" "$double" "$SRC" \
       --out "$ICONSET/icon_${size}x${size}@2x.png" >/dev/null
done

iconutil --convert icns "$ICONSET" --output "$OUT"
rm -rf "$(dirname "$ICONSET")"

echo "Wrote $OUT"
