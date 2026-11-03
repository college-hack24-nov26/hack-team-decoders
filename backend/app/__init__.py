"""MediKiosk backend application package.

Loads ``.env`` into the process environment before any submodule is imported.

This has to happen here, at package import, because the app reads configuration
two different ways:

  - ``app.core.config.Settings`` uses pydantic-settings with ``env_file=".env"``,
    which parses the file itself and never touches ``os.environ``.
  - ``app.interview.tts`` and ``app.interview.asr`` read ``os.getenv`` at module
    import time, which only sees the real process environment.

So without this, every provider setting in ``.env`` was silently ignored by the
TTS and ASR modules: ``TTS_PROVIDER`` fell through to its ``"none"`` default and
``SARVAM_API_KEY`` came back empty, no matter what the file said. Audio and
transcription degraded to their fallbacks and nothing logged an error, because
"no provider configured" is a supported state rather than a failure.

It went unnoticed because Docker Compose passes those settings as real
environment variables, where ``os.getenv`` works. Only running locally against a
``.env`` file exposed the gap.

``override=False`` is deliberate: a real environment variable must win over the
file, so Compose and CI keep the last word.
"""

from pathlib import Path

from dotenv import load_dotenv

# app/__init__.py -> app/ -> backend/
_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"

load_dotenv(_ENV_PATH, override=False)
