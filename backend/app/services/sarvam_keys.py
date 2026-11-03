"""Rotating pool of Sarvam API keys with in-memory health tracking.

Sarvam credits are per account, so a team hits the ceiling one member at a time.
Pooling the team's keys turns several small allowances into one usable budget:
the kiosk serves the first healthy key, and when that account runs dry it moves
to the next without the demo stuttering.

The pool size is whatever the environment provides — there is no fixed maximum
and nothing to declare up front. Add or remove a key and the count follows.

The important property is that a dead key is never tried twice. Rediscovering
"payment required" on every request would add a full round-trip of latency to
each call for the rest of the day, so the outcome is remembered:

    402 / 403  -> credits or entitlement gone. Parked permanently (for the
                  process lifetime). Topping up means a restart, which is a fair
                  trade for never paying to learn the same thing twice.
    429        -> rate limited, which is temporary and says nothing about the
                  balance. Cooled down briefly, then returned to service.

State is per-process and deliberately not persisted. A restart re-probing each
key costs one request per key, whereas a stale "exhausted" record on disk could
strand a topped-up account.

All three Sarvam services draw from this pool, so an account that runs out
during an interview fails over for speech, audio and OCR together rather than
leaving one of them broken.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)

#: HTTP statuses that mean this key has no credit left. Not worth retrying.
EXHAUSTED_STATUSES = frozenset({401, 402, 403})
#: HTTP status that means "too fast", not "out of money".
RATE_LIMITED_STATUS = 429

#: Sarvam publishes 10 requests/minute on all plans, so a minute is enough for a
#: rate-limited key to become useful again.
_RATE_LIMIT_COOLDOWN_SECONDS = 60.0


@dataclass
class _KeyState:
    """Health of one key. ``label`` is safe to log; the key itself is not."""

    key: str
    label: str
    exhausted: bool = False
    cooldown_until: float = 0.0
    failures: int = 0
    last_status: int | None = None

    def available(self, now: float) -> bool:
        return not self.exhausted and now >= self.cooldown_until


def _redact(key: str) -> str:
    """A stable, non-reversible label for logs.

    Keys must never reach a log line, but "a key is out of credit" is useless
    without knowing *which* one, so the last four characters are kept.
    """
    return f"…{key[-4:]}" if len(key) >= 4 else "…"


class SarvamKeyPool:
    """Ordered pool of keys, served first-healthy-first.

    Thread-safe because the callers are not uniform: OCR runs inside
    ``run_in_threadpool`` while TTS and ASR run on the event loop, so two
    services can report a failure for the same key concurrently.
    """

    def __init__(self, keys: list[str]) -> None:
        seen: set[str] = set()
        ordered: list[_KeyState] = []
        for key in keys:
            cleaned = key.strip()
            # Duplicates would silently halve the pool a teammate thinks they
            # contributed, and an empty entry comes free with a trailing comma.
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            # Position is part of the label so "which key died" is answerable
            # even when two keys happen to share their last four characters.
            ordered.append(_KeyState(key=cleaned, label=f"#{len(ordered) + 1} {_redact(cleaned)}"))

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

        ``None`` is a normal outcome, not an error: callers treat it the same as
        "Sarvam not configured" and fall back to their own degraded path, so a
        drained pool costs the patient a mock transcript rather than a crash.
        """
        now = time.monotonic()
        with self._lock:
            for state in self._states:
                if state.available(now):
                    return state.key

            # Nothing available. Distinguish "all out of credit" from "everything
            # is briefly cooling down", because only one of those is recoverable.
            soonest = min(
                (s.cooldown_until for s in self._states if not s.exhausted),
                default=0.0,
            )
            if soonest > now:
                logger.warning(
                    "sarvam_keys: all %d keys rate-limited; next retry in %.0fs",
                    len(self._states),
                    soonest - now,
                )
            else:
                logger.error(
                    "sarvam_keys: all %d keys are exhausted; Sarvam features will "
                    "fall back until a key is topped up and the app restarted",
                    len(self._states),
                )
            return None

    # -- reporting ---------------------------------------------------------

    def report_failure(self, key: str, status_code: int) -> bool:
        """Record an HTTP failure. Returns True if another key is worth trying.

        Only billing and rate-limit statuses affect key health. A 400 or 422 is
        the *request's* fault — rotating keys on those would burn the whole pool
        on one malformed document.
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
                        "sarvam_keys: key %s exhausted (HTTP %d); %d of %d keys left",
                        state.label,
                        status_code,
                        self._available_count(),
                        len(self._states),
                    )
            elif status_code == RATE_LIMITED_STATUS:
                state.cooldown_until = time.monotonic() + _RATE_LIMIT_COOLDOWN_SECONDS
                logger.info(
                    "sarvam_keys: key %s rate-limited; cooling down %.0fs",
                    state.label,
                    _RATE_LIMIT_COOLDOWN_SECONDS,
                )
            else:
                # Not a key problem, so don't punish the key or rotate.
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
        """Per-key health for logs. Carries a redacted label, never the key."""
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
        """Counts only — safe to expose on an unauthenticated health endpoint.

        Deliberately omits the redacted labels that :meth:`status` returns. Four
        characters of a key is not much, but /health is public and there is no
        reason to publish any of it when a count answers the operational
        question: how much budget is left before Sarvam features degrade.
        """
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


#: Auto-discovered per-teammate keys: SARVAM_API_KEY_1, _2, _3, … unbounded.
#: Anchored so it cannot swallow ``SARVAM_API_KEYS`` (plural) or any other
#: SARVAM_* setting.
_NUMBERED_KEY = re.compile(r"^SARVAM_API_KEY_(\d+)$", re.IGNORECASE)


def _numbered_keys_from_env() -> list[str]:
    """Return every ``SARVAM_API_KEY_<n>`` present, in numeric order.

    Sorted numerically rather than by name, or ``_10`` would come between ``_1``
    and ``_2`` and the spending order would not match what was written down.
    """
    found: list[tuple[int, str]] = []
    for name, value in os.environ.items():
        match = _NUMBERED_KEY.match(name)
        if match and value.strip():
            found.append((int(match.group(1)), value))
    return [value for _index, value in sorted(found, key=lambda pair: pair[0])]


def _read_keys_from_env() -> list[str]:
    """Collect every Sarvam key the environment offers. No fixed maximum.

    Three sources, all optional, combined and de-duplicated in this order:

      1. ``SARVAM_API_KEYS`` — one comma-separated list. Compact.
      2. ``SARVAM_API_KEY_1``, ``SARVAM_API_KEY_2``, … — discovered
         automatically, however many exist. Better when the count is unknown or
         changing: each teammate appends their own line instead of everyone
         editing one shared string, which is where typos and lost keys come from.
      3. ``SARVAM_API_KEY`` — the original single-key setting, still honoured so
         existing .env files keep working untouched.

    Nothing declares how many keys there are; the pool is whatever is present.
    """
    pooled = os.getenv("SARVAM_API_KEYS", "")
    single = os.getenv("SARVAM_API_KEY", "")
    return [*pooled.split(","), *_numbered_keys_from_env(), single]


_pool: SarvamKeyPool | None = None
_pool_lock = threading.Lock()


def get_pool() -> SarvamKeyPool:
    """Return the process-wide pool, building it on first use."""
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                _pool = SarvamKeyPool(_read_keys_from_env())
                if _pool.configured:
                    logger.info("sarvam_keys: pool initialised with %d key(s)", len(_pool))
    return _pool


def reset_pool(keys: list[str] | None = None) -> SarvamKeyPool:
    """Rebuild the pool. For tests, and for reloading keys without a restart."""
    global _pool
    with _pool_lock:
        _pool = SarvamKeyPool(keys if keys is not None else _read_keys_from_env())
    return _pool


# ---------------------------------------------------------------------------
# Call-site helpers
# ---------------------------------------------------------------------------
#
# The three Sarvam services each own their request shape, so they run their own
# retry loop rather than sharing a wrapper. These helpers keep that loop to a
# few lines and degrade cleanly when no pool is configured, so a single-key
# deployment behaves exactly as it did before pooling existed.


def acquire_key(fallback: str = "") -> str | None:
    """Return a usable key, falling back to a caller-supplied single key."""
    pool = get_pool()
    if not pool.configured:
        return fallback or None
    return pool.acquire()


def report_key_failure(key: str, status_code: int, fallback: str = "") -> bool:
    """Record a failure. Returns True when a different key is worth trying."""
    pool = get_pool()
    if not pool.configured:
        return False  # nothing to rotate to
    if key == fallback and pool._find(key) is None:
        return False
    return pool.report_failure(key, status_code)


def report_key_success(key: str) -> None:
    pool = get_pool()
    if pool.configured:
        pool.report_success(key)


def attempt_budget() -> int:
    """How many keys are worth trying for one logical request.

    At least 1 so an unconfigured pool still makes its single attempt.
    """
    return max(1, len(get_pool()))
