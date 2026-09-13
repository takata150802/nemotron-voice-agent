#!/usr/bin/env bash
source "$(dirname "$0")/local_common.sh"
export PLATFORM=cpu EXAMPLE_SELECTION=generic-assistant TRANSPORT_SELECTION=webrtc
export PROMPT_SELECTOR=cpu_japanese USE_SILERO_VAD_TURN_DETECTION=true HF_HUB_OFFLINE=1
"$CPU_PYTHON" -m services.health
[[ -d client/dist ]] || { echo 'Browser build missing: run npm --prefix client run build' >&2; exit 1; }
CPU_TLS_ARGS=()
if [[ -n "${VOICE_AGENT_TLS_CERT:-}" || -n "${VOICE_AGENT_TLS_KEY:-}" ]]; then
  : "${VOICE_AGENT_TLS_CERT:?Set both TLS files}" "${VOICE_AGENT_TLS_KEY:?Set both TLS files}"
  CPU_TLS_ARGS=(--tls-cert "$VOICE_AGENT_TLS_CERT" --tls-key "$VOICE_AGENT_TLS_KEY")
fi
exec "$CPU_PYTHON" src/server.py --host "${VOICE_AGENT_HOST:-0.0.0.0}" \
  --port "${VOICE_AGENT_PORT:-7860}" "${CPU_TLS_ARGS[@]}" "$@"
