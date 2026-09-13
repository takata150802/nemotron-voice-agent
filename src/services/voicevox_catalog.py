"""Expose installed Japanese VOICEVOX styles to the upstream voice selector."""

import os

import httpx

from services.local_config import endpoints


async def voice_catalog():
    """Return the existing browser's voice/language metadata shape."""
    _, _, tts = endpoints()
    async with httpx.AsyncClient(trust_env=False, timeout=10) as client:
        response = await client.get(tts + "/speakers")
        response.raise_for_status()
    return {
        "languages": ["ja-JP"],
        "voices": [
            {"id": str(style["id"]), "name": f"{speaker['name']} ({style['name']})", "language": "ja-JP"}
            for speaker in response.json()
            for style in speaker["styles"]
            if style.get("type", "talk") == "talk"
        ],
        "defaultVoiceId": os.getenv("TTS_VOICE_ID", "3"),
    }
