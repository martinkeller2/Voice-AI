import asyncio
from dataclasses import dataclass, field
from typing import Any


@dataclass
class CallSession:
    """Holds all mutable state for a single active call."""

    call_sid: str = ""
    stream_sid: str = ""
    customer_name: str = ""
    zip_code: str = ""
    appliance_type: str = ""
    issue_summary: str = ""

    # Claude conversation history — list of {"role": ..., "content": ...}
    conversation_history: list[dict[str, Any]] = field(default_factory=list)

    # True while we're streaming TTS audio so we can detect barge-in
    is_speaking: bool = False

    # Serialized state for the transcript processor
    transcript_queue: asyncio.Queue = field(default_factory=asyncio.Queue)
