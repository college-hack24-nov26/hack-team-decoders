"""
Minimal OpenAI-compatible Whisper transcription server.
Uses faster-whisper directly — no broken wrapper packages.

Usage:
    source ~/whisper-venv/bin/activate
    pip install fastapi uvicorn python-multipart faster-whisper
    python whisper_server.py

Then set in backend/.env:
    WHISPER_API_URL=http://localhost:8765/v1/audio/transcriptions
    WHISPER_API_KEY=   # leave blank
    WHISPER_MODEL=small
"""

import tempfile
from pathlib import Path

import uvicorn
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import JSONResponse
from faster_whisper import WhisperModel

MODEL_SIZE = "small"   # tiny | small | medium | large-v3
DEVICE = "cpu"         # cpu (works everywhere) or cuda (needs GPU)
COMPUTE = "int8"       # int8 is fastest on CPU, float16 needs GPU

print(f"Loading Whisper model '{MODEL_SIZE}' on {DEVICE} … (downloads on first run)")
model = WhisperModel(MODEL_SIZE, device=DEVICE, compute_type=COMPUTE)
print("Model ready.")

app = FastAPI(title="whisper-local")


@app.post("/v1/audio/transcriptions")
async def transcribe(
    file: UploadFile = File(...),
    model: str = Form(default="small"),
    language: str = Form(default=None),
):
    # Save upload to a temp file — faster-whisper needs a file path
    suffix = Path(file.filename or "audio.webm").suffix or ".webm"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    try:
        segments, info = globals()["model"].transcribe(
            tmp_path,
            language=language or None,
            beam_size=5,
        )
        text = " ".join(seg.text.strip() for seg in segments)
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    return JSONResponse({"text": text, "language": info.language})


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8765)
