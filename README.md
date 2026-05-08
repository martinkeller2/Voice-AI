# Sears Home Services — Voice AI Agent

An inbound voice call agent that helps homeowners diagnose appliance problems and schedule technician visits.

## Architecture Overview

```
Caller ──── Twilio ──── FastAPI (WebSocket)
                            │
                     ┌──────┴───────┐
                  Deepgram       ElevenLabs
                  (STT)          (TTS)
                     │              │
                     └──── Groq -───┘
                           (LLM + tools)
                                │
                           PostgreSQL
                        (technician scheduling)
```

## Quick Start

### Prerequisites
- Docker + Docker Compose
- Accounts for: Twilio, Deepgram, ElevenLabs, Groq
- `ngrok` (for local development) **or** a server with a public HTTPS URL

### 1. Configure environment

```bash
cp .env.example .env
# Edit .env with your API keys
```

### 2. Expose your local server (development only)

```bash
ngrok http 8000
# Copy the https://... URL into BASE_URL in .env
```

### 3. Launch with Docker Compose

```bash
docker compose up --build
```

This starts:
- `db` — PostgreSQL database
- `init` — one-time DB setup + seed (10 technicians, 2 weeks of slots)
- `app` — FastAPI server on port 8000

### 4. Configure Twilio

1. In [Twilio Console](https://console.twilio.com), go to your phone number settings.
2. Set **A CALL COMES IN** → **Webhook** → `https://<your-base-url>/incoming-call` (HTTP POST).
3. Save. Call the number to test.

### 5. Verify health

```bash
curl http://localhost:8000/health
# → {"status": "ok"}
```

---

## Project Structure

```
.
├── app.py                  # FastAPI application entry point
├── config.py               # Environment-based configuration (pydantic-settings)
├── init_db.py              # One-time DB creation + seed runner
├── database/
│   ├── connection.py       # Async SQLAlchemy engine + session factory
│   ├── models.py           # ORM models: Technician, ServiceArea, Specialty, AvailabilitySlot, Appointment
│   └── seed.py             # 10 technicians with service areas, specialties, and 2-week availability
├── agent/
│   ├── prompts.py          # System prompt defining Sarah's persona and diagnostic flow
│   ├── tools.py            # Tool schemas (Groq) + async DB handlers
│   └── session.py          # Per-call state: conversation history, collected info, queues
├── services/
│   ├── llm.py              # Groq tool-use loop
│   └── tts.py              # ElevenLabs → PCM 16 kHz → mulaw 8 kHz conversion
└── routers/
    └── twilio_router.py    # POST /incoming-call + WebSocket /media-stream
```

---

## Database Schema

| Table | Key columns |
|---|---|
| `technicians` | id, name, email, phone |
| `service_areas` | technician_id, zip_code |
| `specialties` | technician_id, appliance_type |
| `availability_slots` | technician_id, date, start_time, end_time, is_booked |
| `appointments` | technician_id, slot_id, customer_name, customer_phone, customer_zip, appliance_type, issue_description |

Seed data covers **10 technicians** across Chicago-area zip codes (60601–60660) with specialties spanning all supported appliance types.

---

## Supported Appliances

`washer` · `dryer` · `refrigerator` · `dishwasher` · `oven` · `microwave` · `freezer`

---

## Environment Variables

| Variable | Description |
|---|---|
| `TWILIO_ACCOUNT_SID` | Twilio account SID |
| `TWILIO_AUTH_TOKEN` | Twilio auth token |
| `TWILIO_PHONE_NUMBER` | Your Twilio phone number |
| `DEEPGRAM_API_KEY` | Deepgram API key (STT) |
| `ELEVENLABS_API_KEY` | ElevenLabs API key (TTS) |
| `ELEVENLABS_VOICE_ID` | ElevenLabs voice ID (default: Sarah) |
| `GROQ_API_KEY` | Groq API key |
| `BASE_URL` | Public HTTPS URL (ngrok or production) |
| `DATABASE_URL` | PostgreSQL async URL (set automatically by Compose) |

---

## Development (without Docker)

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Start PostgreSQL locally (adjust DATABASE_URL in .env)
python init_db.py          # create tables + seed
uvicorn app:app --reload   # start server
```

---

## Notes

- Requires **Python 3.11** (audioop is used for audio resampling; removed in 3.13)
- TTS latency is ~0.5–1 s; STT utterance-end detection adds ~1 s of silence padding
- Conversation state is held in memory per WebSocket connection — no Redis needed for single-instance deployments
- For multi-instance deployments, move session state to Redis
