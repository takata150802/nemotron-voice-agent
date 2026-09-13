"""Validate local inference endpoints before constructing any client."""

import ipaddress
import os
from urllib.parse import urlsplit


def cpu_mode() -> bool:
    """Return whether the explicitly selected CPU profile is active."""
    return os.getenv("PLATFORM", "").lower() == "cpu"


def local_url(value: str, *, schemes: tuple[str, ...] = ("http",)) -> str:
    """Require numeric loopback addresses, preventing DNS and cloud inference."""
    parsed = urlsplit(value)
    try:
        loopback = ipaddress.ip_address(parsed.hostname or "").is_loopback
        port = parsed.port
    except ValueError:
        loopback, port = False, None
    if (
        parsed.scheme not in schemes
        or not loopback
        or not port
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(f"Inference URL must use a numeric loopback address and explicit port: {value!r}")
    return value.rstrip("/")


def endpoints() -> tuple[str, str, str]:
    """Resolve the three local endpoints from the existing environment mechanism."""
    return (
        local_url(os.getenv("NEMO_SPEECH_URL", "ws://127.0.0.1:8081/v1/realtime"), schemes=("ws",)),
        local_url(os.getenv("LLM_BASE_URL", "http://127.0.0.1:8080/v1")),
        local_url(os.getenv("TTS_BASE_URL", "http://127.0.0.1:50021")),
    )


def configure_cpu_catalog(catalog: dict) -> dict:
    """Overlay CPU endpoints in the existing YAML catalog for browser metadata."""
    if not cpu_mode():
        return catalog
    asr, llm, tts = endpoints()
    for category, key, field, value in (
        ("asr", "nemo-speech-cpp", "server", asr),
        ("llm", "gpt-oss-20b", "base_url", llm),
        ("tts", "voicevox", "server", tts),
    ):
        entry = catalog.get(category, {}).get(key)
        if isinstance(entry, dict):
            entry[field] = value
            if category == "tts":
                entry["voice_id"] = os.getenv("TTS_VOICE_ID", "3")
    return catalog
