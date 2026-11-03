# AI Services Setup — STT, TTS, and OCR

Practical guide based on actual setup experience. Follow in order.
All services are optional — the app works without them (touch-only, text-only, Tesseract OCR).

---

## Important: How to apply any `.env` change

Every time you edit `backend/.env`, the running Docker container does **not** pick it up
automatically. You must restart it:

```bash
cd /Users/aarsh/Codes/Medi-Kiosk/infra
docker compose up -d --no-build backend
```

Verify the variable actually landed in the container before assuming it works:

```bash
docker compose exec backend env | grep <VARIABLE_NAME>
```

If it's missing — the container is still stale. Restart again.

---

## 1 — STT (Speech-to-Text / Voice Input)

The mic button on the interview screen sends audio to a Whisper-compatible endpoint.
Without this configured, the button works but returns a `[Mock ASR]` placeholder
and shows an amber warning on screen.

### Option A — Local Whisper server (free, no internet needed)

**Step 1 — Create a dedicated venv outside the project**

```bash
python3.11 -m venv ~/whisper-venv
source ~/whisper-venv/bin/activate
pip install fastapi uvicorn python-multipart faster-whisper
```

**Step 2 — Create the server script**

The file already exists at `/Users/aarsh/Codes/Medi-Kiosk/whisper_server.py`.

**Step 3 — Start the server**

```bash
source ~/whisper-venv/bin/activate
python /Users/aarsh/Codes/Medi-Kiosk/whisper_server.py
```

First run downloads the model (~244MB). Wait for:
```
Model ready.
INFO: Uvicorn running on http://0.0.0.0:8765
```

Keep this terminal open. The server must be running whenever you use the app.

**Step 4 — Find your Mac's IP address**

```bash
ipconfig getifaddr en0
```

Note the IP (e.g. `192.168.1.22`). Use this instead of `localhost` because the
backend runs inside Docker and cannot reach your Mac via `localhost`.

> `host.docker.internal` is supposed to work on Docker Desktop for Mac but is
> unreliable. Using the actual IP is more reliable.

**Step 5 — Add to `backend/.env`**

```
WHISPER_API_URL=http://192.168.1.22:8765/v1/audio/transcriptions
WHISPER_API_KEY=
WHISPER_MODEL=small
```

**Step 6 — Restart backend container**

```bash
cd /Users/aarsh/Codes/Medi-Kiosk/infra
docker compose up -d --no-build backend
```

**Step 7 — Verify**

```bash
# Check the env var is loaded
docker compose exec backend env | grep WHISPER

# Check the server is reachable from inside the container
docker compose exec backend curl -s http://192.168.1.22:8765/v1/audio/transcriptions
# Expected: 422 Unprocessable Entity (means server is up, just no file sent)
# Bad: "Connection refused" — check the IP and that whisper_server.py is running
```

Then go to http://localhost:3000, start an interview, hold the mic button and speak.
You should see "Transcribing…" → "Got it!" → your words in the green box.

**Choosing a model size:**

Edit `whisper_server.py`, change `MODEL_SIZE`:

| Value | Download size | Speed on M-series Mac | Hindi quality |
|---|---|---|---|
| `tiny` | 75 MB | Very fast | Poor |
| `small` | 244 MB | Fast | Decent ✓ recommended |
| `medium` | 1.5 GB | Moderate | Good |
| `large-v3` | 3 GB | Slow | Best |

---

### Option B — OpenAI API (easiest, costs ~₹1/day of testing)

No local server needed. Just add to `backend/.env`:

```
WHISPER_API_URL=https://api.openai.com/v1/audio/transcriptions
WHISPER_API_KEY=sk-...
WHISPER_MODEL=whisper-1
```

Get key at: https://platform.openai.com/api-keys

Restart the backend container after.

---

### Troubleshooting STT

| Symptom | Cause | Fix |
|---|---|---|
| Amber warning "ASR not configured" | `WHISPER_API_URL` not in container env | Restart backend container after editing `.env` |
| "Transcription failed" error | Server unreachable | Check IP, check whisper_server.py is running |
| Empty transcript | Audio too short or mic not recording | Hold button for at least 1–2 seconds |
| `[Mock ASR]` still showing after restart | Container not actually restarted | Run `docker compose exec backend env \| grep WHISPER` to confirm |
| Connection refused from inside Docker | Using `localhost` instead of Mac IP | Use `ipconfig getifaddr en0` to get real IP |

---

## 2 — TTS (Text-to-Speech / Spoken Question Prompts)

Questions are spoken aloud on the interview screen. Without TTS configured, questions
show as text only. `TTS_PROVIDER=none` is the default.

### Option A — Sarvam AI (recommended for Hindi)

Best choice for Indian languages. Free tier available.

**Step 1 — Get API key**

Sign up at https://dashboard.sarvam.ai → API Keys → Create new key.

**Step 2 — Add to `backend/.env`**

```
TTS_PROVIDER=sarvam
SARVAM_API_KEY=your-key-here
SARVAM_SPEAKER=anushka
SARVAM_MODEL=bulbul:v2
```

Available speakers:
- Female: `anushka`, `manisha`, `vidya`, `arya`
- Male: `abhilash`, `karun`, `hitesh`

**Step 3 — Restart backend container**

```bash
cd /Users/aarsh/Codes/Medi-Kiosk/infra
docker compose up -d --no-build backend
```

**Step 4 — Verify**

```bash
docker compose exec backend env | grep -E "TTS|SARVAM"
# Must show TTS_PROVIDER=sarvam and SARVAM_API_KEY=<your key>
# If TTS_PROVIDER=none is still showing — the container is stale
```

Then start an interview — the first question should be spoken automatically.

---

### Option B — Google Cloud TTS

Better English quality. 1 million characters/month free.

**Step 1 — Get API key**

Go to https://console.cloud.google.com → APIs & Services → Credentials → Create API Key.
Restrict it to "Cloud Text-to-Speech API" only.

**Step 2 — Add to `backend/.env`**

```
TTS_PROVIDER=google
GOOGLE_TTS_API_KEY=AIza...
```

**Step 3 — Restart backend container**

```bash
docker compose up -d --no-build backend
```

---

### Common TTS mistake — hardcoded env vars overriding `.env`

The `docker-compose.yml` `environment:` block overrides `env_file:`.
If you see `TTS_PROVIDER=none` in the container after editing `.env`,
check `infra/docker-compose.yml` for any hardcoded `TTS_PROVIDER:` line
and remove it. (This was fixed — but worth knowing if you see it again.)

---

### Troubleshooting TTS

| Symptom | Cause | Fix |
|---|---|---|
| No audio, questions text-only | `TTS_PROVIDER=none` in container | Restart container after editing `.env` |
| `TTS_PROVIDER=none` after restart | Hardcoded in `docker-compose.yml` | Remove the line from the `environment:` block |
| Audio plays once then stops | Browser autoplay blocked | Click the 🔊 "Hear the question again" button |
| Sarvam returns 401 | Wrong API key | Double-check key on dashboard.sarvam.ai |

---

## 3 — OCR (Document Text Extraction)

Used when a patient uploads a prescription or lab report on the document upload screen.

### Default — Tesseract (already works, no setup needed)

Tesseract is installed inside the Docker container automatically.
Handles clean printed text in English and Hindi.

**Limitations:**
- Poor on handwriting
- Struggles with low-quality phone photos
- No table structure detection

**Verify it's working:**

Upload any printed document (prescription photo, lab report scan) on the document
upload screen. Check the backend logs:

```bash
cd /Users/aarsh/Codes/Medi-Kiosk/infra
docker compose logs backend --tail=30 | grep -i "ocr\|document\|entities"
```

Look for `ocr_status: done` and `entities: <number>`. If entities is 0, the document
either has no recognisable medical content or the image quality is too low.

---

### Upgrade — Google Cloud Vision (better accuracy, 1000 free requests/month)

Handles tables, mixed languages, and moderately handwritten text far better than Tesseract.

**Step 1 — Enable the API**

Go to https://console.cloud.google.com → APIs & Services → Enable APIs →
search "Cloud Vision API" → Enable.

**Step 2 — Get an API key**

Same credentials page as TTS. You can reuse the same API key — just make sure
Cloud Vision API is also enabled for it.

**Step 3 — Add to `backend/.env`**

```
OCR_ENGINE=google_vision
GOOGLE_VISION_API_KEY=AIza...
```

**Step 4 — Restart backend container**

```bash
docker compose up -d --no-build backend
docker compose exec backend env | grep OCR
# Should show: OCR_ENGINE=google_vision
```

---

### Troubleshooting OCR

| Symptom | Cause | Fix |
|---|---|---|
| "No entities extracted" | Normal — document has no recognisable medical content | Upload a real prescription or lab report |
| "No entities extracted" on a real prescription | Low image quality | Retake photo in better light, flat surface |
| OCR_ENGINE still `tesseract` after changing `.env` | Container not restarted | `docker compose up -d --no-build backend` |
| Google Vision returns 403 | API not enabled or wrong key | Enable Cloud Vision API in Google Cloud Console |

---

## Quick reference — full working `.env` for all three services

```
# backend/.env

DATABASE_URL=postgresql://medikiosk:medikiosk@localhost:5432/medikiosk
JWT_SECRET=any-random-string

# STT — local Whisper
WHISPER_API_URL=http://192.168.1.22:8765/v1/audio/transcriptions
WHISPER_API_KEY=
WHISPER_MODEL=small

# TTS — Sarvam AI
TTS_PROVIDER=sarvam
SARVAM_API_KEY=your-sarvam-key
SARVAM_SPEAKER=anushka
SARVAM_MODEL=bulbul:v2

# OCR — Google Vision (or leave as tesseract)
OCR_ENGINE=tesseract
# OCR_ENGINE=google_vision
# GOOGLE_VISION_API_KEY=AIza...
```

After any change: `docker compose up -d --no-build backend`
After that: `docker compose exec backend env | grep -E "WHISPER|TTS|OCR|SARVAM"` to confirm.
