"""Local Japanese CPU speech synthesis through the official VOICEVOX HTTP API."""

import io
import json
import time
import wave
from collections.abc import AsyncGenerator

import httpx
from loguru import logger
from pipecat.frames.frames import ErrorFrame, Frame, TTSAudioRawFrame, TTSStoppedFrame
from pipecat.services.settings import TTSSettings
from pipecat.services.tts_service import TTSService

from services.local_config import local_url


class VoicevoxTTSService(TTSService):
    """Retain Pipecat sentence aggregation, cancellation, and audio contexts.

    VOICEVOX buffers synthesis per sentence. This adapter streams PCM frames
    after each sentence, without waiting for the entire LLM response.
    """

    Settings = TTSSettings

    def __init__(self, *, base_url: str, voice: str = "3", **kwargs):
        """Select a local style ID and avoid proxy or cloud defaults."""
        super().__init__(
            sample_rate=24000,
            push_start_frame=True,
            settings=TTSSettings(model=None, voice=voice, language="ja"),
            **kwargs,
        )
        self.base_url = local_url(base_url)
        self._http = httpx.AsyncClient(timeout=60, trust_env=False)

    def can_generate_metrics(self) -> bool:
        """Enable inherited TTFB, processing, and text usage metrics."""
        return True

    async def run_tts(self, text: str, context_id: str) -> AsyncGenerator[Frame, None]:
        """Synthesize one sentence and yield ordered mono PCM16 audio frames."""
        started = time.monotonic()
        ttfb_pending = False
        try:
            # Fail closed if the server ever sends unparsed Harmony or thought tags.
            if any(marker in text for marker in ("<|", "<think>", "</think>")):
                raise ValueError("Unparsed model reasoning/control tokens refused by TTS")
            speaker = int(self._settings.voice)
            await self.start_ttfb_metrics()
            ttfb_pending = True
            query = await self._http.post(f"{self.base_url}/audio_query", params={"text": text, "speaker": speaker})
            query.raise_for_status()
            payload = query.json()
            payload["outputSamplingRate"] = self.sample_rate
            payload["outputStereo"] = False
            response = await self._http.post(f"{self.base_url}/synthesis", params={"speaker": speaker}, json=payload)
            response.raise_for_status()
            with wave.open(io.BytesIO(response.content), "rb") as wav:
                if wav.getnchannels() != 1 or wav.getsampwidth() != 2 or wav.getframerate() != self.sample_rate:
                    raise ValueError("VOICEVOX must return mono PCM16 at the requested sample rate")
                audio = wav.readframes(wav.getnframes())
            elapsed = time.monotonic() - started
            duration = len(audio) / (self.sample_rate * 2)
            await self.stop_ttfb_metrics()
            ttfb_pending = False
            await self.start_tts_usage_metrics(text)
            logger.info(
                json.dumps(
                    {
                        "metric": "tts_synthesis",
                        "first_audio_seconds": elapsed,
                        "synthesis_seconds": elapsed,
                        "audio_seconds": duration,
                        "rtf": elapsed / duration if duration else None,
                    }
                )
            )
            for offset in range(0, len(audio), 2400):  # 50 ms PCM packets; transport owns pacing.
                yield TTSAudioRawFrame(audio[offset : offset + 2400], self.sample_rate, 1, context_id=context_id)
        except Exception as exc:
            yield ErrorFrame(f"Local VOICEVOX synthesis failed: {exc}")
        finally:
            if ttfb_pending:
                await self.stop_ttfb_metrics()
        yield TTSStoppedFrame(context_id=context_id)

    async def cleanup(self):
        """Close the local HTTP pool when the pipeline session ends."""
        await self._http.aclose()
        await super().cleanup()
