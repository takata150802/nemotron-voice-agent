#!/usr/bin/env bash
set -euo pipefail
CPU_DOCKER_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$CPU_DOCKER_ROOT"
[[ $(uname -s) == Linux ]] || { echo "Linux is required" >&2; exit 1; }
case $(uname -m) in
  x86_64) CPU_ARCH=amd64 ;;
  aarch64|arm64) CPU_ARCH=arm64 ;;
  *) echo "Unsupported CPU architecture" >&2; exit 1 ;;
esac
readonly CPU_ARCH
export CPU_ARCH
cpu_version() {
  [[ $1 =~ ^[a-zA-Z0-9_][a-zA-Z0-9_.-]*$ ]] || { echo "Invalid image version" >&2; exit 1; }
}

cpu_docker_host() {
  case $(docker info --format '{{.OSType}}/{{.Architecture}}') in
    linux/x86_64|linux/amd64) daemon_arch=amd64 ;;
    linux/aarch64|linux/arm64) daemon_arch=arm64 ;;
    *) echo "Unsupported Docker daemon platform" >&2; exit 1 ;;
  esac
  [[ $daemon_arch == "$CPU_ARCH" ]] || { echo "Docker daemon must match this native Linux host" >&2; exit 1; }
}
