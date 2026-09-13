"""Headless Chromium regression probe; Windows users still use the browser only.

Install Playwright and Chromium in a separate test environment. Run with all
local backends and the voice agent already started. The supplied WAV is used
as a fake microphone; no physical device is accessed.
"""

import argparse
import asyncio
import json
import time
from pathlib import Path
from urllib.parse import urlsplit

from playwright.async_api import async_playwright


async def probe(args):
    """Connect the unmodified browser client and verify bidirectional WebRTC."""
    origin = urlsplit(args.url)
    if origin.hostname not in {"127.0.0.1", "::1"}:
        raise ValueError("This automated probe only connects to a local test server")
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            headless=True,
            args=[
                "--disable-gpu",
                "--disable-background-networking",
                "--disable-component-update",
                "--disable-sync",
                "--use-fake-device-for-media-stream",
                "--use-fake-ui-for-media-stream",
                f"--use-file-for-fake-audio-capture={args.wav.resolve()}",
                "--autoplay-policy=no-user-gesture-required",
            ],
        )
        context = await browser.new_context(ignore_https_errors=True, permissions=["microphone"])
        page = await context.new_page()
        failures = []
        page.on("pageerror", lambda error: failures.append(str(error)))

        async def local_only(route):
            host = urlsplit(route.request.url).hostname
            if host not in {"127.0.0.1", "::1"}:
                failures.append(f"External browser request: {host}")
                await route.abort()
            else:
                await route.continue_()

        await page.route("**/*", local_only)
        await page.add_init_script("""
            window.__cpuPeers = [];
            const Peer = window.RTCPeerConnection;
            window.RTCPeerConnection = class extends Peer {
                constructor(...args) { super(...args); window.__cpuPeers.push(this); }
            };
        """)
        try:
            await page.goto(args.url)
            await page.wait_for_timeout(1500)
            await page.get_by_role("button", name="Connect", exact=True).click(timeout=30000)
            await page.get_by_role("button", name="Disconnect", exact=True).wait_for(timeout=40000)
            deadline = time.monotonic() + 80
            stats = []
            while time.monotonic() < deadline:
                stats = await page.evaluate("""async () => {
                    const result = [];
                    for (const peer of window.__cpuPeers) {
                        const stats = await peer.getStats();
                        stats.forEach(s => {
                            if (s.type === 'inbound-rtp' || s.type === 'outbound-rtp')
                                result.push({type:s.type, kind:s.kind, bytesReceived:s.bytesReceived,
                                             bytesSent:s.bytesSent, packetsReceived:s.packetsReceived});
                        });
                    }
                    return result;
                }""")
                incoming = any(s["type"] == "inbound-rtp" and s.get("bytesReceived", 0) > 1000 for s in stats)
                outgoing = any(s["type"] == "outbound-rtp" and s.get("bytesSent", 0) > 1000 for s in stats)
                messages = await page.locator(".transcript-message").all_text_contents()
                # A greeting alone is insufficient: require a bot reply after user speech.
                user_seen = any("天気" in message and "You:" in message for message in messages)
                reply_seen = bool(messages) and "Bot:" in messages[-1] and user_seen
                if incoming and outgoing and reply_seen:
                    break
                await asyncio.sleep(1)
            else:
                raise RuntimeError(f"WebRTC audio did not flow both ways: {stats}")
            # Let RTVI deliver the final transcript and server latency metrics.
            await asyncio.sleep(2)
            print(
                json.dumps(
                    {
                        "probe": "chromium-webrtc",
                        "stats": stats,
                        "page_errors": failures,
                        "transcripts": await page.locator(".transcript-message").all_text_contents(),
                    },
                    ensure_ascii=False,
                )
            )
            if failures:
                raise RuntimeError(f"Browser errors: {failures}")
            await page.get_by_role("button", name="Disconnect", exact=True).click()
            await page.get_by_role("button", name="Connect", exact=True).wait_for(timeout=10000)
        except Exception:
            print("Browser failure state:", await page.locator("body").inner_text())
            print("Browser page errors:", failures)
            raise
        finally:
            await browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="https://127.0.0.1:7860/")
    parser.add_argument("--wav", type=Path, required=True)
    asyncio.run(probe(parser.parse_args()))
