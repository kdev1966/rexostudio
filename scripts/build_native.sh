#!/bin/bash
# ---------------------------------------------------------------------------
# Compile les outils natifs de Rexo Studio (Swift, frameworks d'Apple) :
#   bin/rexo-segment : detourage des personnes (Apple Vision) et effets photo
#                      (fond transparent, fond noir et blanc, fond flou)
# Necessite les outils en ligne de commande d'Apple (xcode-select --install)
# et macOS 12 ou plus (VNGeneratePersonSegmentationRequest).
# Relancable sans risque : recompile seulement si la source a change.
#
#   ./scripts/build_native.sh
# ---------------------------------------------------------------------------
set -euo pipefail
cd "$(dirname "$0")/.."

SRC="native/segment.swift"
OUT="bin/rexo-segment"

if ! command -v swiftc >/dev/null 2>&1; then
  echo "swiftc introuvable : installez les outils de developpement (xcode-select --install)." >&2
  exit 1
fi
mkdir -p bin
if [ -x "$OUT" ] && [ "$OUT" -nt "$SRC" ]; then
  echo "$OUT est a jour."
  exit 0
fi
swiftc -O "$SRC" -o "$OUT.tmp"
mv "$OUT.tmp" "$OUT"
echo "$OUT compile."
