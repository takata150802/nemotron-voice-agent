#!/usr/bin/env bash
source "$(dirname "$0")/local_common.sh"
NEMO_SOURCE_DIR="${NEMO_SOURCE_DIR:-$CPU_REPO_ROOT/.build/NeMo-Speech.cpp}"
NEMO_REVISION="${NEMO_REVISION:-a5b6953c4a579a2bbd1c0913ad8a85c2a4d99953}"
if [[ ! -d "$NEMO_SOURCE_DIR/.git" ]]; then
  git clone https://github.com/NVIDIA/NeMo-Speech.cpp.git "$NEMO_SOURCE_DIR"
fi
git -C "$NEMO_SOURCE_DIR" checkout "$NEMO_REVISION"
git -C "$NEMO_SOURCE_DIR" submodule update --init ggml third_party/cpp-httplib llama.cpp
# Official ASR has a fixed 4-thread scheduler and no ASR compute-thread CLI.
# This small, checked patch exposes a local CPU control for scheduler/cache paths.
if git -C "$NEMO_SOURCE_DIR" apply --reverse --check "$CPU_REPO_ROOT/patches/nemo-cpu-threads.patch" 2>/dev/null; then
  :
else
  git -C "$NEMO_SOURCE_DIR" apply --check "$CPU_REPO_ROOT/patches/nemo-cpu-threads.patch"
  git -C "$NEMO_SOURCE_DIR" apply "$CPU_REPO_ROOT/patches/nemo-cpu-threads.patch"
fi
cd "$NEMO_SOURCE_DIR"
scripts/configure.sh cpu-server -DGGML_CUDA=OFF -DGGML_VULKAN=OFF -DGGML_METAL=OFF "$@"
cmake --build --preset cpu-server --parallel "${BUILD_JOBS:-4}"
