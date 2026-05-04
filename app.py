import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routers.twilio_router import router as twilio_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)

app = FastAPI(
    title="Sears Home Services Voice Agent",
    description="Inbound call agent for appliance diagnostics and technician scheduling.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(twilio_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
