"""ElevenLabs text-to-speech → raw mulaw 8 kHz bytes for Twilio Media Streams."""
import audioop
import logging

from elevenlabs.client import ElevenLabs

from config import settings

logger = logging.getLogger(__name__)

_client: ElevenLabs | None = None


def _get_client() -> ElevenLabs:
    global _client
    if _client is None:
        _client = ElevenLabs(api_key=settings.ELEVENLABS_API_KEY)
    return _client


def _pcm16k_to_mulaw8k(pcm_data: bytes) -> bytes:
    """Downsample PCM 16 kHz 16-bit mono → mulaw 8 kHz (Twilio format)."""
    resampled, _ = audioop.ratecv(pcm_data, 2, 1, 16000, 8000, None)
    return audioop.lin2ulaw(resampled, 2)


async def synthesize(text: str) -> bytes | None:
    """Return mulaw 8 kHz audio bytes for the given text, or None on error."""
    if not text.strip():
        return None
    try:
        client = _get_client()
        # pcm_16000 = raw signed 16-bit PCM at 16 kHz (no container overhead)
        chunks = client.text_to_speech.convert(
            text=text,
            voice_id=settings.ELEVENLABS_VOICE_ID,
            model_id="eleven_turbo_v2",
            output_format="pcm_16000",
        )
        pcm = b"".join(chunks)
        return _pcm16k_to_mulaw8k(pcm)
    except Exception:
        logger.exception("ElevenLabs TTS failed for text: %.80s", text)
        return None
