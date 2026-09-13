#!/usr/bin/env bash
source "$(dirname "$0")/local_common.sh"
: "${NEMO_ASR_MODEL:?Set NEMO_ASR_MODEL to an existing Nemotron 3.5 Q8 GGUF}"
[[ -f "$NEMO_ASR_MODEL" ]] || { echo "ASR GGUF missing: $NEMO_ASR_MODEL" >&2; exit 1; }
"$CPU_PYTHON" scripts/check_gguf.py "$NEMO_ASR_MODEL" asr 7
mapfile -t NEMO_LISTENER < <(local_address "${NEMO_SPEECH_URL:-ws://127.0.0.1:8081/v1/realtime}" ws)
[[ ${#NEMO_LISTENER[@]} == 2 ]] || exit 1
export NEMO_ASR_THREADS="${NEMO_ASR_THREADS:-2}"
export HF_HUB_OFFLINE=1
NEMO_SPEECH_BIN="${NEMO_SPEECH_BIN:-.build/NeMo-Speech.cpp/build/cpu-server/bin/nemo-speech}"
export LD_LIBRARY_PATH="$(dirname "$(realpath "$NEMO_SPEECH_BIN")")${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
exec "$NEMO_SPEECH_BIN" serve \
  --host "${NEMO_LISTENER[0]}" --port "${NEMO_LISTENER[1]}" \
  --asr.model.path "$NEMO_ASR_MODEL" --asr.backend.gpu=-1 \
  --asr.endpointing.enable=false --asr.batching.enabled=false \
  --http.threads "${NEMO_HTTP_THREADS:-4}"
