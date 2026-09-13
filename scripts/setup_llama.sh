#!/usr/bin/env bash
source "$(dirname "$0")/local_common.sh"
LLAMA_SOURCE_DIR="${LLAMA_SOURCE_DIR:-$CPU_REPO_ROOT/.build/llama.cpp}"
LLAMA_REVISION="${LLAMA_REVISION:-56b9eb280a67796379d8625729fb03d72c70789d}"
if [[ ! -d "$LLAMA_SOURCE_DIR/.git" ]]; then
  git clone https://github.com/ggml-org/llama.cpp.git "$LLAMA_SOURCE_DIR"
fi
git -C "$LLAMA_SOURCE_DIR" checkout "$LLAMA_REVISION"
cmake -S "$LLAMA_SOURCE_DIR" -B "$LLAMA_SOURCE_DIR/build" \
  -DCMAKE_BUILD_TYPE=Release -DGGML_CUDA=OFF -DGGML_VULKAN=OFF -DGGML_METAL=OFF \
  -DLLAMA_BUILD_TESTS=OFF -DLLAMA_BUILD_EXAMPLES=OFF "$@"
cmake --build "$LLAMA_SOURCE_DIR/build" --target llama-server --parallel "${BUILD_JOBS:-4}"
