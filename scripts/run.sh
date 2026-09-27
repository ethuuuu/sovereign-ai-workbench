#!/usr/bin/env bash
# Start the workbench. Binds to loopback only.
set -euo pipefail
cd "$(dirname "$0")/.."
exec python3 -m uvicorn service.app:app --host 127.0.0.1 --port 8080 --reload
