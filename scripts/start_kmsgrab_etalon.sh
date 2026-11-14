#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHONPATH="$ROOT/.venv/lib/python3.14/site-packages"
PYTHON="$ROOT/.venv/bin/python"
SCRIPT="$ROOT/scripts/stream_linux.py"

if [ ! -x "$PYTHON" ]; then
  echo "Python venv not found: $PYTHON" >&2
  echo "Run from host with project .venv prepared." >&2
  read -r -p "Press Enter to close..." || true
  exit 1
fi

# Stable PC-route profile (Deck, Goggles Integra, kmsgrab): no oversize observed
exec sudo PYTHONPATH="$PYTHONPATH" "$PYTHON" "$SCRIPT" \
  --source desktop --desktop-capture kmsgrab \
  --encoder libx264 --preset ultrafast \
  --kmsgrab-rotate 270 --gpu-filters off \
  --fps 100 --capture-fps 100 --bitrate-mbps 40 --keyframe-seconds 3 "$@"
