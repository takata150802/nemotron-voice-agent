#!/usr/bin/env bash
source "$(dirname "$0")/local_common.sh"
exec "$CPU_PYTHON" -m services.health
