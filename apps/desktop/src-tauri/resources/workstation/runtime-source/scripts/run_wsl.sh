#!/usr/bin/env bash
set -euo pipefail

VENV="${MEETING_DOCUMENTS_WSL_VENV:-/opt/meeting-documents/venv}"
PYTHON="$VENV/bin/python"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

if [[ ! -x "$PYTHON" ]]; then
  echo "Missing environment: $VENV" >&2
  echo "Run the Meeting Documents workstation setup first." >&2
  exit 1
fi

NVIDIA_LIBS="$(
  "$PYTHON" -c '
import os
import nvidia.cublas.lib
import nvidia.cudnn.lib
print(
    next(iter(nvidia.cublas.lib.__path__))
    + ":"
    + next(iter(nvidia.cudnn.lib.__path__))
)
'
)"
export LD_LIBRARY_PATH="$NVIDIA_LIBS:${LD_LIBRARY_PATH:-}"

cd "$PROJECT_DIR"
exec "$PYTHON" -m meeting_transcriber.cli "$@"
