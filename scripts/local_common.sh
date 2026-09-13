#!/usr/bin/env bash
# Shared environment loading for local CPU launchers.
set -euo pipefail
CPU_REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$CPU_REPO_ROOT"
if [[ -f "${ENV_FILE:-.env}" ]]; then
  set -a
  source "${ENV_FILE:-.env}"
  set +a
fi
export NLTK_DATA="${NLTK_DATA:-$CPU_REPO_ROOT/.models/nltk}"
export CUDA_VISIBLE_DEVICES=-1 HF_HUB_DISABLE_TELEMETRY=1 DO_NOT_TRACK=1
export ENABLE_TRACING=false LANGCHAIN_TRACING_V2=false LANGSMITH_TRACING=false
export PYTHONPATH="$CPU_REPO_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
CPU_PYTHON="${CPU_PYTHON:-$CPU_REPO_ROOT/.venv/bin/python}"
# Numeric loopback URL validation also prevents inherited HTTP proxy use.
local_address() {
  "$CPU_PYTHON" - "$1" "$2" <<'PY'
import sys
from urllib.parse import urlsplit
from services.local_config import local_url
url = local_url(sys.argv[1], schemes=(sys.argv[2],))
p = urlsplit(url)
print(p.hostname)
print(p.port)
PY
}
