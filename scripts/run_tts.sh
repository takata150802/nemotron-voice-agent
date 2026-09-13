#!/usr/bin/env bash
source "$(dirname "$0")/local_common.sh"
: "${VOICEVOX_BIN:?Set VOICEVOX_BIN to the official Linux CPU engine executable}"
mapfile -t TTS_LISTENER < <(local_address "${TTS_BASE_URL:-http://127.0.0.1:50021}" http)
[[ ${#TTS_LISTENER[@]} == 2 ]] || exit 1
export XDG_DATA_HOME="${VOICEVOX_DATA_DIR:-$CPU_REPO_ROOT/.models/runtime-data}"
export VV_CPU_NUM_THREADS="${TTS_THREADS:-2}" VV_USE_GPU=0 HF_HUB_OFFLINE=1
TTS_GPU_ARGS=()
TTS_HELP="$("$VOICEVOX_BIN" --help)"
# Current master supports --no-use_gpu; official 0.25.2 CPU release does not.
if [[ "$TTS_HELP" == *--no-use_gpu* ]]; then TTS_GPU_ARGS=(--no-use_gpu); fi
exec "$VOICEVOX_BIN" --host "${TTS_LISTENER[0]}" --port "${TTS_LISTENER[1]}" \
  "${TTS_GPU_ARGS[@]}" --cpu_num_threads "$VV_CPU_NUM_THREADS" --disable_mutable_api
