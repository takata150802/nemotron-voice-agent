#!/usr/bin/env bash
source "$(dirname "$0")/cpu_docker_common.sh"
CPU_IMAGE_VERSION=${1:-local}
cpu_version "$CPU_IMAGE_VERSION"
cpu_docker_host
for target in app asr llm tts; do
  docker build --platform "linux/$CPU_ARCH" --file docker/Dockerfile.cpu --target "$target" --build-arg "BUILD_JOBS=${BUILD_JOBS:-4}" --tag "cpu-voice-bot/$target:$CPU_IMAGE_VERSION-$CPU_ARCH" .
done
printf 'docker save -o cpu-voice-bot-%s-%s.tar' "$CPU_IMAGE_VERSION" "$CPU_ARCH"
for target in app asr llm tts; do printf ' cpu-voice-bot/%s:%s-%s' "$target" "$CPU_IMAGE_VERSION" "$CPU_ARCH"; done
printf '\n'
