"""Model-free contract tests for the CPU adapters and existing Pipecat pipeline."""

import asyncio
import io
import json
import wave
from contextlib import asynccontextmanager

import pytest
from aiohttp import WSMsgType, web
from pipecat.frames.frames import (
    CancelFrame,
    ErrorFrame,
    InputAudioRawFrame,
    InterimTranscriptionFrame,
    InterruptionFrame,
    LLMContextFrame,
    LLMFullResponseEndFrame,
    LLMTextFrame,
    TranscriptionFrame,
    TTSAudioRawFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.tests.utils import SleepFrame, run_test

from services.local_config import local_url
from services.local_openai_llm import LocalOpenAILLMService
from services.nemo_realtime import NeMoRealtimeClient
from services.nemo_speech_cpp_stt import NeMoSpeechCppSTTService
from services.voicevox_tts import VoicevoxTTSService


@asynccontextmanager
async def backends(*, fail_handshake=False, fail_tts=False, drop_once=False, stream_gate=False):
    """Serve independent fixtures matching official ASR, SSE, and VOICEVOX APIs."""
    seen = {"audio": [], "sessions": [], "queries": [], "llm": [], "llm_done": False, "tts_before_llm_done": False}
    first_tts = asyncio.Event()
    app = web.Application()

    async def asr(request):
        socket = web.WebSocketResponse()
        await socket.prepare(request)
        await socket.send_json({"type": "session.created"})
        partial = False
        async for message in socket:
            if message.type == WSMsgType.BINARY:
                seen["audio"].append(message.data)
                if drop_once and len(seen["audio"]) == 1:
                    await socket.close()
                    break
                if not partial:
                    await socket.send_json(
                        {"type": "conversation.item.input_audio_transcription.delta", "delta": "こんにちは"}
                    )
                    partial = True
            elif message.type == WSMsgType.TEXT:
                event = json.loads(message.data)
                if event["type"] == "session.update":
                    seen["sessions"].append(event["session"])
                    if fail_handshake:
                        await socket.send_json({"type": "error", "error": {"message": "unsupported language"}})
                    else:
                        await socket.send_json({"type": "session.updated"})
                elif event["type"] == "input_audio_buffer.commit":
                    await socket.send_json(
                        {"type": "conversation.item.input_audio_transcription.completed", "transcript": "こんにちは。"}
                    )
                    await socket.send_json({"type": "input_audio_buffer.committed"})
                    partial = False
        return socket

    async def llm(request):
        seen["llm"].append(await request.json())
        response = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
        await response.prepare(request)
        for delta in (
            {"reasoning_content": "secret reasoning"},
            {"content": "こんにちは。"},
            {"content": "元気ですか？"},
        ):
            event = {
                "id": "mock",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": "gpt-oss-20b",
                "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
            }
            await response.write(f"data: {json.dumps(event)}\n\n".encode())
        if stream_gate:
            await asyncio.wait_for(first_tts.wait(), timeout=3)
        seen["llm_done"] = True
        await response.write(b"data: [DONE]\n\n")
        await response.write_eof()
        return response

    async def query(request):
        seen["queries"].append(dict(request.query))
        seen["tts_before_llm_done"] |= not seen["llm_done"]
        first_tts.set()
        return web.json_response({"outputSamplingRate": 24000})

    async def synthesize(request):
        if fail_tts:
            return web.Response(status=503)
        payload = await request.json()
        data = io.BytesIO()
        with wave.open(data, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(payload["outputSamplingRate"])
            wav.writeframes(b"\0\0" * 2400)
        return web.Response(body=data.getvalue(), content_type="audio/wav")

    app.router.add_get("/v1/realtime", asr)
    app.router.add_post("/v1/chat/completions", llm)
    app.router.add_post("/audio_query", query)
    app.router.add_post("/synthesis", synthesize)
    app.router.add_get("/health", lambda r: web.json_response({"status": "ok"}))
    app.router.add_get("/ready", lambda r: web.json_response({"ready": True, "device": "CPU"}))
    app.router.add_get("/v1/models", lambda r: web.json_response({"data": [{"id": "gpt-oss-20b"}]}))
    app.router.add_get("/version", lambda r: web.json_response("0.25.2"))
    app.router.add_get(
        "/speakers", lambda r: web.json_response([{"name": "voice", "styles": [{"id": 3, "name": "normal"}]}])
    )
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}", seen
    finally:
        await runner.cleanup()


@pytest.mark.parametrize(
    "url",
    [
        "https://api.openai.com:443/v1",
        "http://localhost:8080",
        "http://10.0.0.1:8080",
        "http://127.0.0.1:80@evil:80",
        "http://127.0.0.1:8080/?redirect=cloud",
    ],
)
def test_remote_urls_refused(url):
    """Reject cloud, DNS, LAN, user-info, and query-based inference addresses."""
    with pytest.raises(ValueError):
        local_url(url)


def test_asr_connection_streaming_and_reconnect():
    """Test handshake, binary audio, final commit, socket reuse, and reconnect."""

    async def scenario():
        async with backends() as (root, seen):
            client = NeMoRealtimeClient(root.replace("http:", "ws:") + "/v1/realtime")
            for _ in range(2):
                await client.open()
                await client.send(b"\0\0" * 1600)
                assert (await client.receive())["delta"] == "こんにちは"
                await client.commit()
                assert (await client.receive())["transcript"] == "こんにちは。"
                await client.expect("input_audio_buffer.committed")
            await client.close()
            await client.open()
            assert len(seen["sessions"]) == 2
            assert seen["sessions"][0]["language"] == "ja-JP"
            await client.close()

    asyncio.run(scenario())


def test_asr_errors_close_socket():
    """Surface official error payloads and close a failed handshake."""

    async def scenario():
        async with backends(fail_handshake=True) as (root, _):
            client = NeMoRealtimeClient(root.replace("http:", "ws:") + "/v1/realtime")
            with pytest.raises(RuntimeError, match="unsupported language"):
                await client.open()
            assert not client.connected

    asyncio.run(scenario())


def test_pipecat_stt_adapter_lifecycle():
    """Run the adapter under the real Pipecat worker and verify finalization."""

    async def scenario():
        async with backends() as (root, seen):
            stt = NeMoSpeechCppSTTService(url=root.replace("http:", "ws:") + "/v1/realtime")
            down, _ = await run_test(
                stt,
                frames_to_send=[
                    VADUserStartedSpeakingFrame(),
                    SleepFrame(0.03),
                    InputAudioRawFrame(b"\0\0" * 1600, 16000, 1),
                    SleepFrame(0.1),
                    VADUserStoppedSpeakingFrame(stop_secs=0.5),
                    SleepFrame(0.1),
                    VADUserStartedSpeakingFrame(),
                    SleepFrame(0.03),
                    InputAudioRawFrame(b"\0\0" * 1600, 16000, 1),
                    SleepFrame(0.1),
                    VADUserStoppedSpeakingFrame(stop_secs=0.5),
                    SleepFrame(0.1),
                ],
            )
            finals = [f for f in down if isinstance(f, TranscriptionFrame)]
            assert len(finals) == 2
            assert all(f.finalized and f.text == "こんにちは。" for f in finals)
            assert any(isinstance(f, InterimTranscriptionFrame) for f in down)
            assert len(seen["sessions"]) == 1
            assert not stt.client.connected
            assert stt._receiver is None

    asyncio.run(scenario())


def test_llm_stream_only_speaks_final_content():
    """Exercise inherited Pipecat SSE parsing and ignore reasoning_content."""

    async def scenario():
        async with backends() as (root, seen):
            llm = LocalOpenAILLMService(
                base_url=root + "/v1", settings=LocalOpenAILLMService.Settings(model="gpt-oss-20b")
            )
            down, _ = await run_test(
                llm,
                frames_to_send=[LLMContextFrame(LLMContext([{"role": "user", "content": "hello"}])), SleepFrame(0.2)],
            )
            assert "".join(f.text for f in down if isinstance(f, LLMTextFrame)) == "こんにちは。元気ですか？"
            assert seen["llm"][0]["stream"] is True
            assert llm._client.is_closed()

    asyncio.run(scenario())


def test_local_tts_audio_and_errors():
    """Check real TTS frames, sample rate, HTTP errors, and reasoning refusal."""

    async def scenario():
        async with backends() as (root, seen):
            tts = VoicevoxTTSService(base_url=root)
            # The normal worker initializes rate and audio contexts.
            down, _ = await run_test(
                tts, frames_to_send=[LLMTextFrame("こんにちは。"), LLMFullResponseEndFrame(), SleepFrame(0.2)]
            )
            audio = [f for f in down if isinstance(f, TTSAudioRawFrame)]
            assert audio and all(f.sample_rate == 24000 and f.num_channels == 1 for f in audio)
            assert seen["queries"][0]["speaker"] == "3"
        async with backends(fail_tts=True) as (root, _):
            tts = VoicevoxTTSService(base_url=root)
            frames = [f async for f in tts.run_tts("こんにちは。", "test")]
            assert any(isinstance(f, ErrorFrame) for f in frames)
            frames = [f async for f in tts.run_tts("<think>secret</think>", "test")]
            assert any(isinstance(f, ErrorFrame) for f in frames)
            await tts._http.aclose()

    asyncio.run(scenario())


def test_complete_pipeline_smoke_and_interruption(monkeypatch):
    """Use the same ASR/context/LLM/TTS ordering and real Pipecat aggregators."""

    async def scenario():
        from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair

        from examples.shared.pipeline_utils import build_user_aggregator_params

        async with backends(stream_gate=True) as (root, seen):
            stt = NeMoSpeechCppSTTService(url=root.replace("http:", "ws:") + "/v1/realtime")
            llm = LocalOpenAILLMService(
                base_url=root + "/v1", settings=LocalOpenAILLMService.Settings(model="gpt-oss-20b")
            )
            tts = VoicevoxTTSService(base_url=root)
            user, assistant = LLMContextAggregatorPair(
                LLMContext([{"role": "system", "content": "日本語で回答"}]),
                user_params=build_user_aggregator_params(False),
            )
            pipeline = Pipeline([stt, user, llm, tts, assistant])
            down, _ = await run_test(
                pipeline,
                frames_to_send=[
                    VADUserStartedSpeakingFrame(),
                    SleepFrame(0.03),
                    InputAudioRawFrame(b"\0\0" * 1600, 16000, 1),
                    SleepFrame(0.1),
                    VADUserStoppedSpeakingFrame(stop_secs=0.5),
                    SleepFrame(0.8),
                    InterruptionFrame(),
                    SleepFrame(0.1),
                ],
            )
            assert seen["llm"]
            assert seen["queries"]
            assert seen["tts_before_llm_done"], "TTS must start before the complete LLM response"
            assert all("secret" not in q["text"] for q in seen["queries"])
            assert any(isinstance(f, TTSAudioRawFrame) for f in down)
            assert any(isinstance(f, InterruptionFrame) for f in down)
            assert not stt.client.connected and tts._http.is_closed

    monkeypatch.setenv("USE_SILERO_VAD_TURN_DETECTION", "true")
    asyncio.run(scenario())


def test_health_contract(monkeypatch):
    """Verify provider readiness contracts and mandatory local model alias."""

    async def scenario():
        from services.health import check_services

        async with backends() as (root, _):
            monkeypatch.setenv("NEMO_SPEECH_URL", root.replace("http:", "ws:") + "/v1/realtime")
            monkeypatch.setenv("LLM_BASE_URL", root + "/v1")
            monkeypatch.setenv("TTS_BASE_URL", root)
            assert len(await check_services()) == 6

    asyncio.run(scenario())


def test_adapter_network_loss_reconnect_and_cancel():
    """Discard a broken utterance, reconnect on the next one, and release tasks."""

    async def scenario():
        async with backends(drop_once=True) as (root, seen):
            stt = NeMoSpeechCppSTTService(url=root.replace("http:", "ws:") + "/v1/realtime")
            down, up = await run_test(
                stt,
                send_end_frame=False,
                frames_to_send=[
                    VADUserStartedSpeakingFrame(),
                    SleepFrame(0.03),
                    InputAudioRawFrame(b"\0\0" * 1600, 16000, 1),
                    SleepFrame(0.1),
                    VADUserStoppedSpeakingFrame(stop_secs=0.5),
                    SleepFrame(0.05),
                    VADUserStartedSpeakingFrame(),
                    SleepFrame(0.03),
                    InputAudioRawFrame(b"\0\0" * 1600, 16000, 1),
                    SleepFrame(0.1),
                    VADUserStoppedSpeakingFrame(stop_secs=0.5),
                    SleepFrame(0.1),
                    CancelFrame(),
                ],
            )
            assert any(isinstance(f, ErrorFrame) for f in up)
            assert len([f for f in down if isinstance(f, TranscriptionFrame)]) == 1
            assert len(seen["sessions"]) == 2
            assert not stt.client.connected and stt._receiver is None

    asyncio.run(scenario())


def test_websocket_redirect_cannot_escape_loopback():
    """Refuse a server redirect before connecting or sending audio externally."""

    async def scenario():
        app = web.Application()

        async def redirect(request):
            raise web.HTTPFound("ws://example.com:8081/v1/realtime")

        app.router.add_get("/v1/realtime", redirect)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        client = NeMoRealtimeClient(f"ws://127.0.0.1:{port}/v1/realtime")
        try:
            with pytest.raises(ValueError, match="loopback"):
                await client.open()
            assert not client.connected
        finally:
            await runner.cleanup()

    asyncio.run(scenario())
