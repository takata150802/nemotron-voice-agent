"""Streaming NeMo-Speech.cpp adapter using Pipecat's STTService lifecycle."""

import asyncio
import json
import time
from collections import deque
from collections.abc import AsyncGenerator

from loguru import logger
from pipecat.frames.frames import (
    CancelFrame,
    EndFrame,
    ErrorFrame,
    Frame,
    InterimTranscriptionFrame,
    TranscriptionFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection
from pipecat.services.settings import STTSettings
from pipecat.services.stt_service import STTService
from pipecat.utils.time import time_now_iso8601

from services.nemo_realtime import NeMoRealtimeClient
from utils import parse_env_int


class NeMoSpeechCppSTTService(STTService):
    """Translate verified binary PCM16 and ASR events to Pipecat frames.

    Pipecat owns VAD and interruption. NeMo endpointing must be disabled.
    A bounded preroll preserves speech preceding the VAD start notification.
    Network loss discards the affected utterance and surfaces an error; the
    next utterance reconnects without replaying stale recognition results.
    """

    def __init__(self, *, url: str, language: str = "ja-JP", **kwargs):
        """Create independent session state and a bounded audio preroll."""
        super().__init__(sample_rate=16000, settings=STTSettings(model="nemotron-3.5", language=language), **kwargs)
        self.client = NeMoRealtimeClient(url, sample_rate=16000, language=language)
        self._receiver = None
        self._preroll = bytearray()
        self._preroll_limit = min(parse_env_int("NEMO_ASR_PREROLL_MS", 800, min_value=200), 2000) * 32
        self._active = False
        self._partial = ""
        self._started = None
        self._pending = deque()
        self._speech_start = None
        self._speech_duration = 0.0
        self._bytes = 0
        self._failed = False
        self._connection_lock = asyncio.Lock()

    def can_generate_metrics(self) -> bool:
        """Enable the inherited VAD-to-final transcript latency metric."""
        return True

    async def _connect(self):
        async with self._connection_lock:
            if not self.client.connected:
                if self._receiver:
                    await self.cancel_task(self._receiver)
                    self._receiver = None
                await self.client.open()
                self._receiver = self.create_task(self._receive(), name="nemo-asr-receiver")
                await self._call_event_handler("on_connected")

    async def run_stt(self, audio: bytes) -> AsyncGenerator[Frame | None, None]:
        """Send live speech PCM16; keep idle input bounded and local."""
        if len(audio) % 2:
            yield ErrorFrame("NeMo requires aligned little-endian PCM16")
            return
        if not self._active:
            self._preroll.extend(audio)
            del self._preroll[: -self._preroll_limit]  # Bounded mono PCM16 at 16 kHz.
            yield None
            return
        if self._failed:
            yield None
            return
        try:
            await self._connect()
            if self._preroll:
                audio = bytes(self._preroll) + audio
                self._preroll.clear()
            if self._started is None:
                self._started = time.monotonic()
            self._bytes += len(audio)
            await self.client.send(audio)
            yield None
        except Exception as exc:
            self._failed = True
            await self.client.close()
            yield ErrorFrame(f"NeMo streaming failed; utterance discarded: {exc}")

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        """Reuse base STT VAD accounting and finalize at the single VAD boundary."""
        await super().process_frame(frame, direction)
        if isinstance(frame, VADUserStartedSpeakingFrame):
            self._active = True
            self._failed = False
            self._speech_start = frame.timestamp
        elif isinstance(frame, VADUserStoppedSpeakingFrame):
            self._active = False
            self._speech_duration = max(0, frame.timestamp - frame.stop_secs - (self._speech_start or frame.timestamp))
            if self.client.connected and self._bytes and not self._failed:
                self._pending.append((self._started, time.monotonic(), self._bytes, self._speech_duration))
                self._started = None
                self._bytes = 0
                try:
                    await self.client.commit()
                except Exception as exc:
                    self._failed = True
                    self._partial = ""
                    self._pending.clear()
                    await self.client.close()
                    await self.push_error(error_msg=f"NeMo commit failed; utterance discarded: {exc}")
        elif isinstance(frame, (CancelFrame, EndFrame)):
            await self._disconnect()

    async def _receive(self):
        try:
            while True:
                event = await self.client.receive()
                kind = event.get("type", "")
                now = time.monotonic()
                if kind == "conversation.item.input_audio_transcription.delta":
                    if not self._partial and self._started:
                        logger.info(json.dumps({"metric": "asr_partial_latency", "seconds": now - self._started}))
                    self._partial += event.get("delta", "")
                    await self.push_frame(InterimTranscriptionFrame(self._partial, self._user_id, time_now_iso8601()))
                elif kind == "conversation.item.input_audio_transcription.completed":
                    text = event.get("transcript", "")
                    self._partial = ""
                    if not self._pending:
                        raise RuntimeError("Unexpected ASR final: disable NeMo endpointing")
                    started, endpoint, audio_bytes, speech_duration = self._pending.popleft()
                    await self.push_frame(TranscriptionFrame(text, self._user_id, time_now_iso8601(), finalized=True))
                    duration = audio_bytes / 32000
                    elapsed = now - started if started else 0
                    logger.info(
                        json.dumps(
                            {
                                "metric": "asr_final",
                                "speech_seconds": speech_duration,
                                "audio_seconds": duration,
                                "stream_wall_seconds": elapsed,
                                "stream_wall_rtf": elapsed / duration if duration else None,
                                "endpoint_to_final_seconds": now - endpoint,
                                "audio_processed": event.get("audio_processed"),
                            }
                        )
                    )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._failed = bool(self._active or self._bytes or self._pending)
            self._partial = ""
            self._bytes = 0
            self._started = None
            self._pending.clear()
            await self.client.close()
            await self._call_event_handler("on_disconnected")
            if self._failed:
                await self.push_error(error_msg=f"NeMo connection lost; utterance discarded: {exc}")

    async def _disconnect(self):
        if self._receiver:
            await self.cancel_task(self._receiver)
            self._receiver = None
        await self.client.close()
        self._preroll.clear()
        self._pending.clear()

    async def cleanup(self):
        """Release receiver and socket even when a worker is cancelled."""
        await self._disconnect()
        await super().cleanup()
