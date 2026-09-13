#!/usr/bin/env bash
source "$(dirname "$0")/cpu_docker_common.sh"
CPU_DEPLOY_ENV=${CPU_DEPLOY_ENV:-.env.cpu}
[[ -f $CPU_DEPLOY_ENV ]] || { echo "Copy .env.cpu.example to .env.cpu and configure paths" >&2; exit 1; }
set -a
source "$CPU_DEPLOY_ENV"
set +a
cpu_version "${CPU_IMAGE_VERSION:-local}"
CPU_COMPOSE=(docker compose --env-file "$CPU_DEPLOY_ENV" --profile generic-assistant/cpu)
case ${1:-up} in
  up)
    cpu_docker_host
    for target in app asr llm tts; do
      image="cpu-voice-bot/$target:${CPU_IMAGE_VERSION:-local}-$CPU_ARCH"
      actual=$(docker image inspect --format '{{.Architecture}}' "$image") || { echo "Load missing image: $image" >&2; exit 1; }
      [[ $actual == "$CPU_ARCH" ]] || { echo "Image architecture mismatch: $image" >&2; exit 1; }
    done
    for file in "${CPU_MODELS_DIR:?}/${NEMO_ASR_MODEL_FILE:?}" "${CPU_MODELS_DIR}/${LLM_MODEL_FILE:?}" "${VOICE_AGENT_TLS_CERT:?}" "${VOICE_AGENT_TLS_KEY:?}"; do
      [[ $file == /* && -s $file ]] || { echo "Missing absolute model/TLS path: $file" >&2; exit 1; }
    done
    docker run --rm --network none --entrypoint python3 \
      -e "NEMO_SPEECH_URL=${NEMO_SPEECH_URL:-ws://127.0.0.1:8081/v1/realtime}" \
      -e "LLM_BASE_URL=${LLM_BASE_URL:-http://127.0.0.1:8080/v1}" \
      -e "TTS_BASE_URL=${TTS_BASE_URL:-http://127.0.0.1:50021}" \
      --mount "type=bind,src=$VOICE_AGENT_TLS_CERT,dst=/tls/server.crt,readonly" \
      --mount "type=bind,src=$VOICE_AGENT_TLS_KEY,dst=/tls/server.key,readonly" \
      "cpu-voice-bot/asr:${CPU_IMAGE_VERSION:-local}-$CPU_ARCH" \
      -c 'import ssl; from services.local_config import endpoints; endpoints(); ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER).load_cert_chain("/tls/server.crt", "/tls/server.key")'
    "${CPU_COMPOSE[@]}" up -d --pull never --no-build --wait --wait-timeout 600 cpu-asr cpu-llm cpu-tts cpu-app
    ;;
  stop) "${CPU_COMPOSE[@]}" stop cpu-app cpu-asr cpu-llm cpu-tts ;;
  status) "${CPU_COMPOSE[@]}" ps cpu-app cpu-asr cpu-llm cpu-tts ;;
  logs) "${CPU_COMPOSE[@]}" logs --tail 200 -f cpu-app cpu-asr cpu-llm cpu-tts ;;
  *) echo "Usage: scripts/deploy_cpu.sh [up|stop|status|logs]" >&2; exit 1 ;;
esac
