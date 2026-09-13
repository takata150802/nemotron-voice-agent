"""Fail before Pipecat import if its sentence tokenizer is not preinstalled."""

import os
from pathlib import Path


def prepare_cpu_runtime():
    """Enforce CPU selection and disable runtime download/telemetry defaults."""
    if os.getenv("PLATFORM", "").lower() != "cpu":
        return
    root = Path(__file__).resolve().parents[2]
    data = Path(os.getenv("NLTK_DATA", str(root / ".models/nltk")))
    if not (data / "tokenizers/punkt_tab/english/collocations.tab").is_file():
        raise RuntimeError("Offline tokenizer missing: run scripts/setup_python.sh before CPU startup")
    os.environ["NLTK_DATA"] = str(data)
    os.environ.update(
        CUDA_VISIBLE_DEVICES="-1",
        HF_HUB_OFFLINE="1",
        HF_HUB_DISABLE_TELEMETRY="1",
        DO_NOT_TRACK="1",
        ENABLE_TRACING="false",
        LANGCHAIN_TRACING_V2="false",
        LANGSMITH_TRACING="false",
        USE_SILERO_VAD_TURN_DETECTION="true",
        EXAMPLE_SELECTION="generic-assistant",
        TRANSPORT_SELECTION="webrtc",
    )
