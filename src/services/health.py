"""Readiness checks for the actual local service HTTP contracts."""

import asyncio
from urllib.parse import urlsplit, urlunsplit

import httpx

from services.local_config import endpoints


async def check_services():
    """Fail before WebRTC starts when ASR, LLM, or Japanese TTS is unavailable."""
    asr, llm, tts = endpoints()
    parts = urlsplit(asr)
    asr_root = urlunsplit(("http", parts.netloc, "", "", ""))
    urls = [
        ("NeMo health", asr_root + "/health"),
        ("NeMo ready", asr_root + "/ready"),
        ("llama.cpp health", llm.removesuffix("/v1") + "/health"),
        ("llama.cpp models", llm + "/models"),
        ("VOICEVOX version", tts + "/version"),
        ("VOICEVOX speakers", tts + "/speakers"),
    ]
    async with httpx.AsyncClient(timeout=10, trust_env=False) as client:
        results = await asyncio.gather(*(client.get(url) for _, url in urls), return_exceptions=True)
    for (label, url), result in zip(urls, results, strict=True):
        if isinstance(result, Exception):
            raise RuntimeError(f"{label} unavailable at {url}: {result}") from result
        if result.status_code != 200:
            raise RuntimeError(f"{label} not ready at {url}: HTTP {result.status_code}")
    ready = results[1].json()
    if ready.get("ready") is not True:
        raise RuntimeError("NeMo /ready did not confirm readiness")
    if not any(item.get("id") == "gpt-oss-20b" for item in results[3].json().get("data", [])):
        raise RuntimeError("llama.cpp must serve the gpt-oss-20b alias")
    if not results[5].json():
        raise RuntimeError("VOICEVOX has no installed Japanese speakers")
    return {label: "ready" for label, _ in urls}


if __name__ == "__main__":
    try:
        print(asyncio.run(check_services()))
    except (RuntimeError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
