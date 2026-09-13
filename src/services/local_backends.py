"""Construct CPU services while retaining the upstream generic pipeline."""

import os

from services.local_config import endpoints
from services.local_openai_llm import LocalOpenAILLMService
from services.nemo_speech_cpp_stt import NeMoSpeechCppSTTService
from services.voicevox_tts import VoicevoxTTSService


def create_local_services(*, voice: str | None = None):
    """Return services, plus metadata expected by the existing pipeline."""
    asr_url, llm_url, tts_url = endpoints()
    if os.getenv("TTS_PROVIDER", "voicevox") != "voicevox":
        raise ValueError("Unsupported local TTS_PROVIDER; configure a CPU Pipecat TTS service explicitly")
    model = os.getenv("LLM_MODEL", "gpt-oss-20b")
    if model != "gpt-oss-20b":
        raise ValueError("The CPU profile requires LLM_MODEL=gpt-oss-20b")
    stt = NeMoSpeechCppSTTService(url=asr_url, language=os.getenv("NEMO_ASR_LANGUAGE", "ja-JP"))
    llm = LocalOpenAILLMService(
        api_key="not-needed",
        base_url=llm_url,
        settings=LocalOpenAILLMService.Settings(model=model, max_tokens=512, extra={"reasoning_effort": "low"}),
    )
    tts = VoicevoxTTSService(base_url=tts_url, voice=voice or os.getenv("TTS_VOICE_ID", "3"))
    return stt, llm, tts
