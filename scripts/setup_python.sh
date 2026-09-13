#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m venv .venv
.venv/bin/pip install uv
.venv/bin/uv sync --dev
.venv/bin/python scripts/setup_tokenizer.py
npm --prefix client ci
npm --prefix client run build
