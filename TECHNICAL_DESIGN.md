# Technical Design Document
## Sears Home Services — Inbound Voice AI Agent

---

### 1. Overview

This system accepts inbound phone calls, guides callers through appliance diagnostics via natural voice conversation, and books technician visits when basic troubleshooting does not resolve the issue. The design prioritizes low end-to-end latency, correctness of tool-assisted scheduling, and operational simplicity.

---

### 2. Architecture

```
Caller → Twilio (PSTN) → FastAPI WebSocket (/media-stream)
                              ↓               ↑
                       Deepgram STT     Deepgram TTS
                       (nova-2)         (aura-asteria-en)
                              ↓               ↑
                         Groq llama-3.3-70b (tool use)
                              ↓
                         PostgreSQL (scheduling)
```

**Request lifecycle for a single turn:**

1. Twilio streams mulaw 8 kHz audio to `/media-stream` (WebSocket).
2. Chunks are forwarded in real time to Deepgram's streaming WebSocket.
3. Deepgram emits `is_final=True` Transcript events for each stable phrase; we buffer them in `pending_chunks`.
4. After `utterance_end_ms=2000` of silence, Deepgram fires an `UtteranceEnd` event. The buffered phrases are joined and pushed to the queue.
5. The full utterance — plus conversation history — is sent to Groq.
6. Groq either returns a text response or emits a `tool_calls` block (OpenAI function-calling format).
7. If tool use: the handler queries PostgreSQL, returns JSON, and loops back to Groq.
8. The final text response is sent to Deepgram Aura, which returns raw mulaw 8 kHz bytes natively (no resampling). Those bytes are streamed back to Twilio in 1-second chunks.
9. If the caller utters a goodbye phrase (e.g. "bye", "take care"), Sarah plays a farewell line and hangs up via Twilio's REST API.

---

### 3. Technology Choices and Rationale

#### 3.1 Telephony — Twilio Media Streams

Twilio's Media Streams API provides a bidirectional WebSocket with raw mulaw audio at 8 kHz. This avoids polling or webhook round-trips for every audio chunk and gives us full control over when and what audio is played back. The `clear` event enables barge-in: if the caller speaks while the agent is talking, we discard the buffered audio and process the interruption immediately.

**Alternative considered:** Twilio's built-in `<Gather>` TwiML is simpler but constrains turn-taking to a request-response model, which produces unnatural conversation pacing.

#### 3.2 Speech-to-Text — Deepgram Nova-2

Deepgram offers the best latency-accuracy tradeoff among streaming STT providers (~200–400 ms word error rate on conversational English). The `nova-2` model handles appliance-domain vocabulary without custom training. We use Deepgram's `UtteranceEnd` event (gated by `utterance_end_ms=2000`) as the authoritative "caller has stopped talking" signal instead of guessing from `speech_final` flags — this prevents the agent from interrupting mid-sentence when the caller pauses briefly to think. `endpointing=300` keeps short within-sentence gaps from being treated as a stop.

**Alternative considered:** OpenAI Whisper is more accurate on short clips but is not a streaming API; the batch latency (~1–2 s round-trip) would add a perceptible delay between every caller utterance and the agent response.

#### 3.3 Text-to-Speech — Deepgram Aura (`aura-asteria-en`)

Deepgram Aura produces natural-sounding speech at ~300–500 ms time-to-first-audio and — crucially — supports `encoding=mulaw&sample_rate=8000` output directly. That eliminates the PCM-decode + resample + mulaw-encode pipeline that other TTS providers force on you, simplifying the audio path and removing one source of latency. Because Aura uses the same Deepgram account as our STT, deployments need one fewer vendor relationship and one fewer API key to rotate.

**Alternatives considered:**
- **ElevenLabs Turbo v2** has marginally more expressive prosody, but their free tier blocks data-center IPs (Railway, Fly, Render) with an "unusual activity detected" 401, making it unworkable for cloud deployments without a paid plan.
- **Twilio's built-in `<Say>`** is zero-latency but uses Polly voices that sound robotic and can't be used inside Media Streams.
- **OpenAI TTS** has good quality but adds another billing relationship and doesn't natively output mulaw 8 kHz.

#### 3.4 LLM — Groq `llama-3.3-70b-versatile`

Groq's inference API exposes the OpenAI chat-completions interface, so the integration is minimal boilerplate. The hosted LPU hardware delivers ~200–500 ms time-to-first-token for a 512-token response — roughly 3–5× faster than typical cloud LLM APIs. For a voice agent where every second of silence erodes caller trust, this speed advantage is material.

`llama-3.3-70b-versatile` supports native function calling (OpenAI tool-use format). An agentic loop (max 5 iterations) lets the model call `find_available_technicians`, receive the result, then call `book_appointment` sequentially without additional orchestration code. For higher tool-call reliability, `llama3-groq-70b-8192-tool-use-preview` can be swapped in via the `GROQ_MODEL` env var.

**Alternative considered:** Claude claude-sonnet-4-6 (Anthropic) has stronger reasoning and more deterministic schema adherence for tool calls. It is the recommended upgrade path if scheduling accuracy becomes a pain point in production. LangChain was skipped — it adds abstraction overhead for a straightforward two-tool loop and obscures the message format, making debugging harder.

#### 3.5 Database — PostgreSQL with async SQLAlchemy

PostgreSQL is the right default for relational scheduling data: ACID guarantees prevent double-booking, foreign key constraints maintain referential integrity, and the `is_booked` flag is updated atomically. `asyncpg` provides a native async driver compatible with FastAPI's event loop, eliminating thread-pool overhead.

**Alternative considered:** MongoDB's flexible documents could store technician profiles, but scheduling requires transactional slot updates that are more complex to implement correctly in a document model.

#### 3.6 Backend — FastAPI + Uvicorn

FastAPI's `async` WebSocket support maps directly onto the concurrent IO pattern (Twilio WS + Deepgram STT WS + HTTP calls to Deepgram Aura and Groq, all in one event loop). Uvicorn's lifespan support cleanly manages startup/shutdown. Pydantic-settings handles environment validation at startup, failing fast rather than silently misconfiguring.

---

### 4. Scheduling Data Model

```
technicians         ←── service_areas (1:N)
     │              ←── specialties   (1:N)
     └──────────── availability_slots (1:N)
                          │
                     appointments (1:1 per slot)
```

Each `AvailabilitySlot` belongs to one technician and has an `is_booked` flag. `book_appointment` sets this flag and creates an `Appointment` record in the same transaction, preventing double-booking under concurrent calls.

---

### 5. Concurrency Model

Each incoming WebSocket connection gets:
- One `CallSession` object (in-memory state)
- One `asyncio.Queue` bridging Deepgram callbacks to the LLM processor
- One background `asyncio.Task` for `process_transcripts`
- One shared `AsyncSessionLocal` DB session (created inside the task)

Because all work is async and Python's GIL is only relevant for CPU-bound code, multiple simultaneous calls are handled concurrently within a single Uvicorn worker process with no threading complexity.

---

### 6. Tradeoffs and Known Limitations

| Concern | Current choice | Production alternative |
|---|---|---|
| Session state | In-process dict | Redis (multi-instance) |
| TTS streaming | Full response before speaking | Sentence-boundary streaming for lower TTFA |
| Barge-in | Clear-on-new-utterance | VAD-driven interruption with Twilio `mark` events |
| Retry logic | None (single attempt) | Exponential backoff for Deepgram and Groq |
| Auth | None (webhook open) | Twilio request signature validation |
| TTS voice variety | Single Aura voice | Per-language or per-persona voice routing |

---

### 7. End-to-End Latency Budget (typical turn)

| Step | Latency |
|---|---|
| Utterance-end detection (Deepgram, `utterance_end_ms=2000`) | ~2 000 ms |
| LLM inference (Groq, no tools) | ~200–400 ms |
| LLM inference (Groq, 1 tool call) | ~600–900 ms |
| TTS synthesis (Deepgram Aura, native mulaw 8 kHz) | ~300–500 ms |
| WebSocket send (no audio conversion) | ~20 ms |
| **Total (no tools)** | **~2.5–2.9 s** |
| **Total (1 tool call)** | **~2.9–3.4 s** |

`utterance_end_ms` dominates the budget. It is set high (2 000 ms) intentionally — pilot testing showed callers regularly pause 800–1 200 ms mid-sentence, and a more aggressive setting led to the agent interrupting. Groq's LPU hardware keeps LLM inference under 1 second even with tool calls, and Deepgram Aura's native mulaw output shaved ~100 ms off TTS by removing the PCM-resample step. The agent's perceived responsiveness is now bottlenecked by intentional pause detection rather than model or pipeline speed.
