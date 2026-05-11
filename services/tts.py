"""Deepgram Aura TTS → raw mulaw 8 kHz bytes (direct, no conversion needed)."""
import logging

import httpx

from config import settings

logger = logging.getLogger(__name__)

DEEPGRAM_TTS_URL = "https://api.deepgram.com/v1/speak"


async def synthesize(text: str) -> bytes | None:
    """Return mulaw 8 kHz audio bytes for the given text, or None on error."""
    text = text.strip()
    if not text:
        return None
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                DEEPGRAM_TTS_URL,
                params={
                    "model": settings.DEEPGRAM_TTS_MODEL,
                    "encoding": "mulaw",
                    "sample_rate": "8000",
                    "container": "none",
                },
                headers={
                    "Authorization": f"Token {settings.DEEPGRAM_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={"text": text},
            )
            response.raise_for_status()
            return response.content
    except Exception:
        logger.exception("Deepgram TTS failed for text: %.80s", text)
        return None
