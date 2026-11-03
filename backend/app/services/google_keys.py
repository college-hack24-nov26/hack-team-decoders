"""Rotating pool of Google AI API keys with in-memory health tracking.

Google AI services (TTS, Vision OCR, Gemini) all issue per-project API keys.
A team running on free-tier or starter credits hits the ceiling one project at
a time.  Pooling several keys turns those small allowances into one usable
budget: the kiosk serves the first healthy key, and when that project runs dry
it moves to the next without the demo stuttering.

The pool is shared across all three Google services so state is consistent —
an exhausted key is retired for TTS, Vision *and* Gemini simultaneously.

Key health rules mirror the Sarvam pool:

    403 / 429 (quota exceeded, billing disabled, project suspended)
        → credits or entitlement gone.  Parked permanently for the process
          lifetime.  Topping up means a restart, which is a fair trade for
          never paying to rediscover the same thing on every call.
    429 (rateLimitExceeded in the error body, or plain HTTP 429)
        → rate-limited, which is temporary.  Cooled down for 60 s, then
          returned to service.

State is per-process and not persisted.  A restart re-probes each key at a
cost of one request per key, which is much cheaper than a stale "exhausted"
record stranding a topped-up project.

Google error shapes differ slightly by service:
  - Vision / TTS REST: HTTP 403 means "billing disabled or key invalid";
    HTTP 429 means "quota exceeded" (either rate or daily).
  - Gemini via the OpenAI-compatible endpoint: HTTP 429 body may contain
    "RESOURCE_EXHAUSTED" (daily quota) or "rateLimitExceeded" (per-minute).
    HTTP 403 means "API key invalid or project suspended".
    HTTP 402 means "billing required".
    HTTP 401 means "invalid API key".

The caller decides which status codes are "exhausted" vs "rate-limited" by
passing ``is_rate_limit=True`` when the body confirms it is temporary.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

#: HTTP statuses that mean this key / project has no usable budget left.
EXHAUSTED_STATUSES = frozenset({401, 402, 403})
#: HTTP status that means "too fast" or "daily quota hit" — may be temporary.
RATE_LIMITED_STATUS = 429

#: Google's free-tier quotas reset daily, but for a running demo a 60-second
#: cooldown is enough to smooth out per-minute spikes.  Daily exhaustion is
#: reported by the *body* (RESOURCE_EXHAUSTED) and handled as a permanent park.
_RATE_LIMIT_COOLDOWN_SECONDS = 60.0

#: Substrings in a 429 response body that mean the daily quota is gone —
#: treat like exhausted, not like a brief rate-limit.
_DAILY_QUOTA_MARKERS = (
    "RESOURCE_EXHAUSTED",
    "resource_exhausted",
    "quota exceeded",
    "Quota exceeded",
    "dailyLimitExceeded",
    "userRateLimitExceeded",  # actually per-user daily, not per-minute
)


def _is_daily_quota(body: str) -> bool:
    """Return True when a 429 body signals a daily (permanent) exhaustion."""
    return any(marker in body for marker in _DAILY_QUOTA_MARKERS)


@dataclass
class _KeyState:
    """Health of one key.  ``label`` is safe to log; the key itself is not."""

    key: str
    label: str
    exhausted: bool = False
    cooldown_until: float = 0.0
    failures: int = 0
    last_status: int | None = None
    services_used: list[str] = field(default_factory=list)

    def available(self, now: float) -> bool:
        return not self.exhausted and now >= self.cooldown_until


def _redact(key: str) -> str:
    """A stable, non-reversible label for logs — last four chars only."""
    return f"…{key[-4:]}" if len(key) >= 4 else "…"


class GoogleKeyPool:
    """Ordered pool of Google AI API keys, served first-healthy-first.

    Thread-safe: OCR may run inside ``run_in_threadpool`` while TTS and Gemini
    run on the event loop, so two services can report a failure concurrently.
    """

    def __init__(self, keys: list[str]) -> None:
        seen: set[str] = set()
        ordered: list[_KeyState] = []
        for key in keys:
            cleaned = key.strip()
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            ordered.append(
                _KeyState(
                    key=cleaned,
                    label=f"#{len(ordered) + 1} {_redact(cleaned)}",
                )
            )

        self._states = ordered
        self._lock = threading.Lock()

    # -- queries -----------------------------------------------------------

    def __len__(self) -> int:
        return len(self._states)

    @property
    def configured(self) -> bool:
        return bool(self._states)

    def acquire(self) -> str | None:
        """Return the first usable key, or ``None`` when the pool is spent.

        ``None`` is a normal outcome: callers treat it the same as
        "Google not configured" and fall back to their own degraded path.
        """
        now = time.monotonic()
        with self._lock:
            for state in self._states:
                if state.available(now):
                    return state.key

            soonest = min(
                (s.cooldown_until for s in self._states if not s.exhausted),
                default=0.0,
            )
            if soonest > now:
                logger.warning(
                    "google_keys: all %d keys rate-limited; next retry in %.0fs",
                    len(self._states),
                    soonest - now,
                )
            else:
                logger.error(
                    "google_keys: all %d keys are exhausted; Google features will "
                    "fall back until a key is topped up and the app restarted",
                    len(self._states),
                )
            return None

    # -- reporting ---------------------------------------------------------

    def report_failure(self, key: str, status_code: int, body: str = "") -> bool:
        """Record an HTTP failure.  Returns True if another key is worth trying.

        ``body`` is the raw response text — needed to distinguish a temporary
        per-minute 429 from a permanent daily-quota 429.

        Only billing/quota/rate-limit statuses affect key health.  A 400 is
        the request's fault; rotating would burn the whole pool on one bad file.
        """
        with self._lock:
            state = self._find(key)
            if state is None:
                return False

            state.failures += 1
            state.last_status = status_code

            if status_code in EXHAUSTED_STATUSES:
                if not state.exhausted:
                    state.exhausted = True
                    logger.warning(
                        "google_keys: key %s exhausted (HTTP %d); %d of %d keys left",
                        state.label,
                        status_code,
                        self._available_count(),
                        len(self._states),
                    )

            elif status_code == RATE_LIMITED_STATUS:
                if _is_daily_quota(body):
                    # Daily quota gone — treat as permanently exhausted for today.
                    if not state.exhausted:
                        state.exhausted = True
                        logger.warning(
                            "google_keys: key %s daily quota exhausted (HTTP 429); "
                            "%d of %d keys left",
                            state.label,
                            self._available_count(),
                            len(self._states),
                        )
                else:
                    # Per-minute rate limit — brief cooldown, then back in service.
                    state.cooldown_until = time.monotonic() + _RATE_LIMIT_COOLDOWN_SECONDS
                    logger.info(
                        "google_keys: key %s rate-limited; cooling down %.0fs",
                        state.label,
                        _RATE_LIMIT_COOLDOWN_SECONDS,
                    )
            else:
                # Not a key problem (e.g. 400 bad request) — don't rotate.
                return False

        return self.acquire() is not None

    def report_success(self, key: str) -> None:
        """Clear a cooldown early: a working call proves the key is fine."""
        with self._lock:
            state = self._find(key)
            if state is not None and not state.exhausted:
                state.cooldown_until = 0.0

    # -- diagnostics -------------------------------------------------------

    def status(self) -> list[dict]:
        """Per-key health snapshot for logs.  Carries a redacted label, never the key."""
        now = time.monotonic()
        with self._lock:
            return [
                {
                    "key": s.label,
                    "available": s.available(now),
                    "exhausted": s.exhausted,
                    "cooldown_seconds": max(0.0, round(s.cooldown_until - now, 1)),
                    "failures": s.failures,
                    "last_status": s.last_status,
                }
                for s in self._states
            ]

    def summary(self) -> dict[str, int]:
        """Counts only — safe to expose on the /health endpoint."""
        now = time.monotonic()
        with self._lock:
            return {
                "total": len(self._states),
                "available": sum(1 for s in self._states if s.available(now)),
                "exhausted": sum(1 for s in self._states if s.exhausted),
                "cooling_down": sum(
                    1 for s in self._states if not s.exhausted and s.cooldown_until > now
                ),
            }

    # -- internals ---------------------------------------------------------

    def _find(self, key: str) -> _KeyState | None:
        return next((s for s in self._states if s.key == key), None)

    def _available_count(self) -> int:
        now = time.monotonic()
        return sum(1 for s in self._states if s.available(now))


# ---------------------------------------------------------------------------
# Process-wide pool
# ---------------------------------------------------------------------------

#: Numbered key pattern: GOOGLE_AI_API_KEY_1, _2, _3, …
#: Anchored so it cannot swallow GOOGLE_AI_API_KEYS (plural).
_NUMBERED_KEY = re.compile(r"^GOOGLE_AI_API_KEY_(\d+)$", re.IGNORECASE)


def _numbered_keys_from_env() -> list[str]:
    """Return every ``GOOGLE_AI_API_KEY_<n>`` present, in numeric order."""
    found: list[tuple[int, str]] = []
    for name, value in os.environ.items():
        match = _NUMBERED_KEY.match(name)
        if match and value.strip():
            found.append((int(match.group(1)), value))
    return [value for _index, value in sorted(found, key=lambda pair: pair[0])]


def _read_keys_from_env() -> list[str]:
    """Collect every Google AI key the environment offers.

    Three sources, combined and de-duplicated in this order:

      1. ``GOOGLE_AI_API_KEYS``   — comma-separated list. Compact.
      2. ``GOOGLE_AI_API_KEY_1``, ``_2``, … — one per line, auto-discovered.
         Better when the team is growing: each person appends their own line.
      3. ``GOOGLE_AI_API_KEY``    — the original single-key setting, still
         honoured so existing .env files keep working untouched.

    All three Google services (TTS, Vision OCR, Gemini) draw from this one pool,
    so an account that runs out loses all three services simultaneously and fails
    over to the next key for all three at once.
    """
    pooled = os.getenv("GOOGLE_AI_API_KEYS", "")
    single = os.getenv("GOOGLE_AI_API_KEY", "")
    return [*pooled.split(","), *_numbered_keys_from_env(), single]


_pool: GoogleKeyPool | None = None
_pool_lock = threading.Lock()


def get_pool() -> GoogleKeyPool:
    """Return the process-wide pool, building it on first use."""
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                _pool = GoogleKeyPool(_read_keys_from_env())
                if _pool.configured:
                    logger.info("google_keys: pool initialised with %d key(s)", len(_pool))
    return _pool


def reset_pool(keys: list[str] | None = None) -> GoogleKeyPool:
    """Rebuild the pool.  For tests, and for reloading keys without a restart."""
    global _pool
    with _pool_lock:
        _pool = GoogleKeyPool(keys if keys is not None else _read_keys_from_env())
    return _pool


# ---------------------------------------------------------------------------
# Call-site helpers  (same interface as sarvam_keys helpers)
# ---------------------------------------------------------------------------


def acquire_key(fallback: str = "") -> str | None:
    """Return a usable key, falling back to a caller-supplied single key."""
    pool = get_pool()
    if not pool.configured:
        return fallback or None
    return pool.acquire()


def report_key_failure(key: str, status_code: int, body: str = "", fallback: str = "") -> bool:
    """Record a failure.  Returns True when a different key is worth trying."""
    pool = get_pool()
    if not pool.configured:
        return False
    if key == fallback and pool._find(key) is None:
        return False
    return pool.report_failure(key, status_code, body=body)


def report_key_success(key: str) -> None:
    pool = get_pool()
    if pool.configured:
        pool.report_success(key)


def attempt_budget() -> int:
    """How many keys are worth trying for one logical request.

    At least 1 so an unconfigured pool still makes its single attempt.
    """
    return max(1, len(get_pool()))
