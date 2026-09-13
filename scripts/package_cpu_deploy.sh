#!/usr/bin/env bash
source "$(dirname "$0")/cpu_docker_common.sh"
version=${1:-local}
cpu_version "$version"
output="$CPU_DOCKER_ROOT/.build/cpu-deploy-$version.tar.gz"
mkdir -p .build
bundle_settings=$(mktemp -d)
trap 'rm -rf "$bundle_settings"' EXIT
sed "s/^CPU_IMAGE_VERSION=.*/CPU_IMAGE_VERSION=$version/" .env.cpu.example > "$bundle_settings/.env.cpu.example"
# Include every root Compose dependency, even inactive upstream recipes.
tar -czf "$output" docker-compose.yml docker/*.yaml src/examples/frontend_backend_agent/airline/database/docker-compose.yml scripts/cpu_docker_common.sh scripts/deploy_cpu.sh -C "$bundle_settings" .env.cpu.example
printf 'Deploy bundle: %s\n' "$output"
