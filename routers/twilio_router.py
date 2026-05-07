"""
Twilio inbound call handler.

Flow:
  1. POST /incoming-call  — Twilio hits this when a call arrives.
     We respond with TwiML that tells Twilio to open a Media Stream WebSocket
     back to us at /media-stream.

  2. WebSocket /media-stream — bidirectional audio channel.
     Inbound mulaw audio → Deepgram STT → Groq LLM (with tools) → ElevenLabs TTS
     → mulaw audio back to Twilio.
"""
import asyncio
import base64
import json
import logging
import re

import httpx
from deepgram import DeepgramClient, LiveOptions, LiveTranscriptionEvents
from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from agent.session import CallSession
from config import settings
from database.connection import AsyncSessionLocal
from services.llm import get_response
from services.tts import synthesize

logger = logging.getLogger(__name__)

router = APIRouter()

GREETING = (
    "Thank you for calling Sears Home Services. My name is Sarah, and I'm here to help you "
    "get your appliance back up and running. May I start with your name, please?"
)

FAREWELL = "Thank you for calling Sears Home Services. Have a great day. Goodbye."

# Caller phrases that should automatically end the call
GOODBYE_PATTERN = re.compile(
    r"\b("
    r"goodbye|good\s?bye|bye(\s+now)?|"
    r"take\s+care|"
    r"see\s+you(\s+(later|soon))?|"
    r"talk\s+to\s+you\s+later|"
    r"have\s+a\s+(good|great|nice)\s+(day|night|evening|one)|"
    r"that('?s|\s+is)\s+all|"
    r"i'?m\s+(done|good|all\s+set)|"
    r"nothing\s+else|"
    r"hang\s+up|end\s+(the\s+)?call"
    r")\b",
    re.IGNORECASE,
)


def _is_goodbye(text: str) -> bool:
    return bool(GOODBYE_PATTERN.search(text))


async def _hangup_call(call_sid: str) -> None:
    """Terminate the call via Twilio's REST API."""
    if not call_sid:
        return
    url = (
        f"https://api.twilio.com/2010-04-01/Accounts/"
        f"{settings.TWILIO_ACCOUNT_SID}/Calls/{call_sid}.json"
    )
    auth = (settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(url, auth=auth, data={"Status": "completed"})
        logger.info("Call %s terminated via Twilio API", call_sid)
    except Exception:
        logger.exception("Failed to hang up call %s", call_sid)


# ---------------------------------------------------------------------------
# Webhook: incoming call
# ---------------------------------------------------------------------------

@router.post("/incoming-call")
async def incoming_call(request: Request) -> Response:
    """Return TwiML that connects the call audio to our media-stream WebSocket."""
    ws_url = settings.BASE_URL.replace("https://", "wss://").replace("http://", "ws://")
    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Connect>
    <Stream url="{ws_url}/media-stream" />
  </Connect>
</Response>"""
    return Response(content=twiml, media_type="text/xml")


# ---------------------------------------------------------------------------
# WebSocket: media stream
# ---------------------------------------------------------------------------

@router.websocket("/media-stream")
async def media_stream(websocket: WebSocket) -> None:
    await websocket.accept()

    session = CallSession()
    stream_sid: str = ""

    # Queue: full caller utterances → LLM/TTS processor
    transcript_queue: asyncio.Queue[str] = asyncio.Queue()

    # ── Utterance assembly ──────────────────────────────────────────────────
    # We accumulate every `is_final=True` transcript chunk into pending_chunks.
    # We only flush to the LLM when Deepgram fires an UtteranceEnd event,
    # which it emits ONLY after `utterance_end_ms` of true silence (2 s here).
    # This is more reliable than custom debouncing because Deepgram's VAD
    # has full visibility into the audio stream.
    pending_chunks: list[str] = []

    # -----------------------------------------------------------------------
    # Deepgram setup
    # -----------------------------------------------------------------------
    dg_client = DeepgramClient(settings.DEEPGRAM_API_KEY)
    dg_connection = dg_client.listen.asyncwebsocket.v("1")

    async def on_transcript(self_unused, result, **kwargs):  # noqa: ARG001
        """Buffer every finalized phrase; do not flush yet."""
        try:
            if not result.is_final:
                return
            text: str = result.channel.alternatives[0].transcript.strip()
            if text:
                pending_chunks.append(text)
        except Exception:
            logger.exception("Transcript callback error")

    async def on_utterance_end(self_unused, *args, **kwargs):  # noqa: ARG001
        """Fired by Deepgram after `utterance_end_ms` of silence — flush now."""
        try:
            if not pending_chunks:
                return
            full = " ".join(pending_chunks).strip()
            pending_chunks.clear()
            logger.info("[STT] %s", full)
            await transcript_queue.put(full)
        except Exception:
            logger.exception("UtteranceEnd handler error")

    dg_connection.on(LiveTranscriptionEvents.Transcript, on_transcript)
    dg_connection.on(LiveTranscriptionEvents.UtteranceEnd, on_utterance_end)

    dg_options = LiveOptions(
        model="nova-2",
        language="en-US",
        smart_format=True,
        punctuate=True,
        interim_results=True,
        utterance_end_ms="1000",  # caller must be silent for 2 s before utterance closes
        endpointing=300,           # treat <300 ms gaps as part of the same speech
        vad_events=True,
        encoding="mulaw",
        sample_rate=8000,
    )

    dg_connected = await dg_connection.start(dg_options)
    if not dg_connected:
        logger.error("Failed to connect to Deepgram")
        await websocket.close()
        return

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    async def send_audio(mulaw_bytes: bytes) -> None:
        """Send mulaw audio bytes to the caller via Twilio Media Streams."""
        if not stream_sid or not mulaw_bytes:
            return
        session.is_speaking = True
        chunk_size = 8000  # ~1 second of mulaw 8 kHz per chunk
        for i in range(0, len(mulaw_bytes), chunk_size):
            chunk = mulaw_bytes[i : i + chunk_size]
            await websocket.send_text(
                json.dumps({
                    "event": "media",
                    "streamSid": stream_sid,
                    "media": {"payload": base64.b64encode(chunk).decode()},
                })
            )
        session.is_speaking = False

    async def clear_audio() -> None:
        """Tell Twilio to discard buffered audio (barge-in support)."""
        if stream_sid:
            await websocket.send_text(
                json.dumps({"event": "clear", "streamSid": stream_sid})
            )
            session.is_speaking = False

    # -----------------------------------------------------------------------
    # Transcript processor — runs concurrently with the Twilio reader
    # -----------------------------------------------------------------------

    async def process_transcripts() -> None:
        async with AsyncSessionLocal() as db:
            while True:
                try:
                    text = await asyncio.wait_for(transcript_queue.get(), timeout=120.0)
                except asyncio.TimeoutError:
                    logger.info("No speech for 2 minutes — ending processor")
                    break

                # If agent was speaking, interrupt it
                if session.is_speaking:
                    await clear_audio()

                # ── Auto-hangup on caller goodbye ──
                if _is_goodbye(text):
                    logger.info("[BYE] goodbye detected: %s", text)
                    audio = await synthesize(FAREWELL)
                    if audio:
                        await send_audio(audio)
                        # Wait for the farewell audio to finish playing
                        # (mulaw 8 kHz = 8000 bytes per second)
                        await asyncio.sleep(len(audio) / 8000 + 0.5)
                    await _hangup_call(session.call_sid)
                    break

                logger.info("[LLM] processing: %s", text)
                try:
                    reply = await get_response(session, text, db)
                except Exception:
                    logger.exception("LLM error")
                    reply = (
                        "I'm sorry, I'm having a technical difficulty. "
                        "Please hold while I reconnect you with our team."
                    )

                logger.info("[TTS] synthesizing: %.80s", reply)
                audio = await synthesize(reply)
                if audio:
                    await send_audio(audio)

    processor_task = asyncio.create_task(process_transcripts())

    # -----------------------------------------------------------------------
    # Twilio WebSocket reader
    # -----------------------------------------------------------------------

    try:
        async for raw in websocket.iter_text():
            data: dict = json.loads(raw)
            event: str = data.get("event", "")

            if event == "start":
                stream_sid = data["start"]["streamSid"]
                session.stream_sid = stream_sid
                session.call_sid = data["start"]["callSid"]
                logger.info("Stream started: %s", stream_sid)

                # Speak the greeting on the first tick
                greeting_audio = await synthesize(GREETING)
                if greeting_audio:
                    await send_audio(greeting_audio)

            elif event == "media":
                payload = base64.b64decode(data["media"]["payload"])
                await dg_connection.send(payload)

            elif event == "stop":
                logger.info("Stream stopped: %s", stream_sid)
                break

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected")
    except Exception:
        logger.exception("Unexpected error in media stream")
    finally:
        processor_task.cancel()
        try:
            await dg_connection.finish()
        except Exception:
            pass
        logger.info("Call session ended: %s", session.call_sid)
