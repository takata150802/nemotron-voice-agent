"""Run real local backend probes and an optional Pipecat audio pipeline smoke test."""

import argparse
import asyncio
import io
import json
import os
import time
import wave
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()
os.environ["PLATFORM"] = "cpu"

from services.offline import prepare_cpu_runtime

prepare_cpu_runtime()

import httpx
from openai import AsyncOpenAI

from services.health import check_services
from services.local_config import endpoints
from services.nemo_realtime import NeMoRealtimeClient


def read_wav(path):
    """Require the same input format as the live STT adapter."""
    with wave.open(str(path), "rb") as wav:
        if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) != (1, 2, 16000):
            raise ValueError("Probe WAV must be mono PCM16 at 16000 Hz")
        return wav.readframes(wav.getnframes())


async def tts_probe(text, output):
    """Synthesize Japanese test input at 16 kHz using official VOICEVOX APIs."""
    _, _, tts = endpoints()
    started = time.monotonic()
    speaker = int(os.getenv("TTS_VOICE_ID", "3"))
    async with httpx.AsyncClient(trust_env=False, timeout=60) as client:
        query = await client.post(tts + "/audio_query", params={"text": text, "speaker": speaker})
        query.raise_for_status()
        payload = query.json()
        payload.update(outputSamplingRate=16000, outputStereo=False)
        response = await client.post(tts + "/synthesis", params={"speaker": speaker}, json=payload)
        response.raise_for_status()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(response.content)
    with wave.open(io.BytesIO(response.content), "rb") as wav:
        duration = wav.getnframes() / wav.getframerate()
    elapsed = time.monotonic() - started
    print(json.dumps({"probe": "tts", "seconds": elapsed, "audio_seconds": duration, "rtf": elapsed / duration}))


async def asr_probe(audio):
    """Measure unpaced streaming processing RTF separately from live wall RTF."""
    asr, _, _ = endpoints()
    client = NeMoRealtimeClient(asr, language=os.getenv("NEMO_ASR_LANGUAGE", "ja-JP"))
    events = []
    started = time.monotonic()
    endpoint = None

    async def receive():
        while True:
            event = await client.receive()
            event["elapsed_seconds"] = time.monotonic() - started
            events.append(event)
            if event["type"] == "input_audio_buffer.committed":
                return

    await client.open()
    reader = asyncio.create_task(receive())
    try:
        async with asyncio.timeout(90):
            for offset in range(0, len(audio), 3200):
                await client.send(audio[offset : offset + 3200])
            endpoint = time.monotonic()
            await client.commit()
            await reader
        finals = [e for e in events if e["type"].endswith(".completed")]
        partials = [e for e in events if e["type"].endswith(".delta")]
        if not finals or not finals[-1].get("transcript"):
            raise RuntimeError("ASR returned no final transcript")
        elapsed = time.monotonic() - started
        print(
            json.dumps(
                {
                    "probe": "asr",
                    "text": finals[-1]["transcript"],
                    "partial_count": len(partials),
                    "first_partial_seconds": partials[0]["elapsed_seconds"] if partials else None,
                    "endpoint_to_final_seconds": started + finals[-1]["elapsed_seconds"] - endpoint,
                    "audio_seconds": len(audio) / 32000,
                    "unpaced_rtf": elapsed / (len(audio) / 32000),
                },
                ensure_ascii=False,
            )
        )
    finally:
        reader.cancel()
        await asyncio.gather(reader, return_exceptions=True)
        await client.close()


async def llm_probe():
    """Use the existing official SDK streaming endpoint and inspect final channels."""
    _, llm, _ = endpoints()
    started = time.monotonic()
    first_token = first_final = None
    text = ""
    reasoning_chunks = 0
    timings = None
    async with AsyncOpenAI(
        api_key="not-needed", base_url=llm, http_client=httpx.AsyncClient(trust_env=False, timeout=120)
    ) as client:
        stream = await client.chat.completions.create(
            model="gpt-oss-20b",
            messages=[{"role": "user", "content": "日本語で短く挨拶してください。"}],
            max_tokens=512,
            stream=True,
            extra_body={"reasoning_effort": "low"},
        )
        async for chunk in stream:
            if chunk.model_extra and chunk.model_extra.get("timings"):
                timings = chunk.model_extra["timings"]
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta.content or (delta.model_extra and delta.model_extra.get("reasoning_content")):
                first_token = first_token or time.monotonic() - started
            if delta.model_extra and delta.model_extra.get("reasoning_content"):
                reasoning_chunks += 1
            if delta.content:
                first_final = first_final or time.monotonic() - started
                text += delta.content
    if not text or "<|" in text or "<think>" in text:
        raise RuntimeError("llama.cpp must return parsed final assistant content")
    print(
        json.dumps(
            {
                "probe": "llm",
                "ttft_seconds": first_token,
                "first_final_seconds": first_final,
                "total_seconds": time.monotonic() - started,
                "reasoning_chunks": reasoning_chunks,
                "text": text,
                "timings": timings,
            },
            ensure_ascii=False,
        )
    )


async def pipeline_probe(audio):
    """Inject recorded PCM into the upstream service/aggregator order for verification."""
    from pipecat.frames.frames import EndFrame, InputAudioRawFrame, TTSAudioRawFrame
    from pipecat.observers.user_bot_latency_observer import UserBotLatencyObserver
    from pipecat.pipeline.pipeline import Pipeline
    from pipecat.pipeline.worker import PipelineParams, PipelineWorker
    from pipecat.processors.aggregators.llm_context import LLMContext
    from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair
    from pipecat.processors.frame_processor import FrameProcessor
    from pipecat.workers.runner import WorkerRunner

    from examples.shared.pipeline_utils import build_user_aggregator_params
    from services.local_backends import create_local_services

    first_audio = asyncio.Event()
    latency = []

    class Capture(FrameProcessor):
        async def process_frame(self, frame, direction):
            await super().process_frame(frame, direction)
            if isinstance(frame, TTSAudioRawFrame):
                first_audio.set()
            await self.push_frame(frame, direction)

    stt, llm, tts = create_local_services()
    user, assistant = LLMContextAggregatorPair(
        LLMContext([{"role": "system", "content": "自然な日本語の1文で回答してください。"}]),
        user_params=build_user_aggregator_params(False),
    )
    observer = UserBotLatencyObserver()

    @observer.event_handler("on_first_bot_speech_latency")
    async def on_latency(observer, value):
        latency.append(value)

    pipeline = Pipeline([stt, user, llm, tts, Capture(), assistant])
    worker = PipelineWorker(
        pipeline,
        params=PipelineParams(enable_metrics=True, enable_usage_metrics=True),
        observers=[observer],
        enable_rtvi=False,
    )
    runner = WorkerRunner(handle_sigint=False)
    await runner.add_workers(worker)
    task = asyncio.create_task(runner.run())
    try:
        async with asyncio.timeout(120):
            await asyncio.sleep(0.1)
            pcm = b"\0\0" * 8000 + audio + b"\0\0" * 16000
            for offset in range(0, len(pcm), 640):
                await worker.queue_frame(InputAudioRawFrame(pcm[offset : offset + 640], 16000, 1))
                await asyncio.sleep(0.02)
            await first_audio.wait()
            print(json.dumps({"probe": "pipeline", "first_audio": True, "observer_latency_seconds": latency}))
            await worker.queue_frame(EndFrame())
            await task
    finally:
        if not task.done():
            await worker.cancel()
            await task


async def main(args):
    """Verify local readiness and run real ASR, LLM, and TTS probes."""
    print(await check_services())
    path = args.asr_wav or args.output_wav
    if args.asr_wav is None:
        await tts_probe(args.text, path)
    audio = read_wav(path)
    await asr_probe(audio)
    await llm_probe()
    if args.pipeline:
        await pipeline_probe(audio)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asr-wav", type=Path, help="Existing mono PCM16 16 kHz Japanese recording")
    parser.add_argument("--output-wav", type=Path, default=Path(".models/probe-input.wav"))
    parser.add_argument("--text", default="こんにちは。今日は良い天気ですね。")
    parser.add_argument("--pipeline", action="store_true", help="Also run the real Pipecat recorded-audio pipeline")
    try:
        asyncio.run(main(parser.parse_args()))
    except (RuntimeError, ValueError, TimeoutError, httpx.HTTPError) as exc:
        raise SystemExit(f"Local probe failed: {exc}") from exc
