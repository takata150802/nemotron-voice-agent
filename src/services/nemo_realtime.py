"""Client for the verified NeMo-Speech.cpp ASR realtime event contract."""

import asyncio
import json

from websockets.asyncio.client import connect
from websockets.protocol import State

from services.local_config import local_url


class _LoopbackConnect(connect):
    def process_redirect(self, exc):
        redirected = super().process_redirect(exc)
        if isinstance(redirected, str):
            local_url(redirected, schemes=("ws",))
        return redirected


class NeMoRealtimeClient:
    """Own one ASR socket; each voice session creates its own client."""

    def __init__(self, url: str, *, sample_rate: int = 16000, language: str = "ja-JP"):
        """Configure PCM16 input without accessing any model download service."""
        self.url = local_url(url, schemes=("ws",))
        self.sample_rate = sample_rate
        self.language = language
        self.socket = None
        self._send_lock = asyncio.Lock()

    @property
    def connected(self) -> bool:
        """Return whether this socket can accept audio."""
        return self.socket is not None and self.socket.state == State.OPEN

    async def open(self):
        """Wait for both official session events before admitting binary audio."""
        if self.connected:
            return
        await self.close()
        self.socket = await _LoopbackConnect(self.url, open_timeout=10, max_size=2**20, max_queue=16, proxy=None)
        try:
            async with asyncio.timeout(10):
                await self.expect("session.created")
                await self.send(
                    {
                        "type": "session.update",
                        "session": {
                            "sample_rate": self.sample_rate,
                            "language": self.language,
                            "automatic_punctuation": True,
                            "word_timestamps": True,
                        },
                    }
                )
                await self.expect("session.updated")
        except BaseException:
            await self.close()
            raise

    async def receive(self) -> dict:
        """Decode a documented server event and surface protocol errors."""
        event = json.loads(await self.socket.recv())
        if event.get("type") == "error":
            raise RuntimeError(f"NeMo ASR: {event.get('error', {}).get('message', 'unknown error')}")
        return event

    async def expect(self, event_type: str):
        """Reject an unexpected handshake rather than guessing a protocol."""
        event = await self.receive()
        if event.get("type") != event_type:
            raise RuntimeError(f"Expected {event_type}, received {event.get('type')}")
        return event

    async def send(self, data: bytes | dict):
        """Serialize binary audio and control events in socket order."""
        async with self._send_lock:
            await self.socket.send(data if isinstance(data, bytes) else json.dumps(data))

    async def commit(self):
        """Finalize the current utterance; the official socket remains reusable."""
        await self.send({"type": "input_audio_buffer.commit"})

    async def close(self):
        """Close the socket on normal termination or cancellation."""
        socket, self.socket = self.socket, None
        if socket is not None:
            await socket.close()
