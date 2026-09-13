#!/usr/bin/env bash
source "$(dirname "$0")/local_common.sh"
: "${LLM_MODEL_PATH:?Set LLM_MODEL_PATH to an existing gpt-oss-20b Q4_K_M GGUF}"
[[ -f "$LLM_MODEL_PATH" ]] || { echo "LLM GGUF missing: $LLM_MODEL_PATH" >&2; exit 1; }
# Verify GGUF metadata instead of trusting its filename.
"$CPU_PYTHON" scripts/check_gguf.py "$LLM_MODEL_PATH" gpt-oss 15
mapfile -t LLAMA_LISTENER < <(local_address "${LLM_BASE_URL:-http://127.0.0.1:8080/v1}" http)
[[ ${#LLAMA_LISTENER[@]} == 2 ]] || exit 1
export HF_HUB_OFFLINE=1
LLAMA_BIN="${LLAMA_BIN:-.build/llama.cpp/build/bin/llama-server}"
export LD_LIBRARY_PATH="$(dirname "$(realpath "$LLAMA_BIN")")${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
exec "$LLAMA_BIN" \
  --model "$LLM_MODEL_PATH" --alias gpt-oss-20b \
  --host "${LLAMA_LISTENER[0]}" --port "${LLAMA_LISTENER[1]}" \
  --n-gpu-layers 0 --threads "${LLAMA_THREADS:-4}" --threads-batch "${LLAMA_THREADS_BATCH:-4}" \
  --ctx-size "${LLAMA_CTX_SIZE:-4096}" --parallel 1 \
  --offline --jinja --reasoning-format deepseek --metrics --no-webui
