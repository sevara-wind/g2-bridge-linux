#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHONPATH="$ROOT/.venv/lib/python3.14/site-packages${PYTHONPATH:+:$PYTHONPATH}"
PYTHON="$ROOT/.venv/bin/python"
SCRIPT="$ROOT/scripts/stream_linux.py"
exec "$PYTHON" "$SCRIPT" "$@"
