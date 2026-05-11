from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Twilio
    TWILIO_ACCOUNT_SID: str = ""
    TWILIO_AUTH_TOKEN: str = ""
    TWILIO_PHONE_NUMBER: str = ""

    # Deepgram (STT + TTS — same API key for both)
    DEEPGRAM_API_KEY: str = ""
    DEEPGRAM_TTS_MODEL: str = "aura-asteria-en"  # professional female voice
    # ── Legacy / optional ── retained so older .env files don't error out
    ELEVENLABS_API_KEY: str = ""
    ELEVENLABS_VOICE_ID: str = ""

    # Groq (LLM)
    GROQ_API_KEY: str = ""
    GROQ_MODEL: str = "llama-3.3-70b-versatile"

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://voiceai:voiceai@db:5432/voiceai"

    # Public base URL for Twilio callbacks (ngrok or production hostname)
    BASE_URL: str = "https://your-ngrok-url.ngrok.io"

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
