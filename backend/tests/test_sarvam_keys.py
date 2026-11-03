"""Rotating Sarvam key pool.

Six teammates, six accounts, one budget. What these tests pin is that a spent
key is never tried again — rediscovering "payment required" on every request
would add a round-trip of latency to every call for the rest of the day.
"""

from __future__ import annotations

import pytest

from app.services import sarvam_keys as sk
from app.services.sarvam_keys import (
    EXHAUSTED_STATUSES,
    RATE_LIMITED_STATUS,
    SarvamKeyPool,
    acquire_key,
    attempt_budget,
    report_key_failure,
    reset_pool,
)

SIX_KEYS = [f"sk-team-{n}" for n in range(1, 7)]


@pytest.fixture(autouse=True)
def _isolate_pool():
    """The pool is process-wide state; don't leak it between tests."""
    reset_pool([])
    yield
    reset_pool([])


class TestPoolConstruction:
    def test_six_keys_are_all_registered(self):
        pool = SarvamKeyPool(SIX_KEYS)
        assert len(pool) == 6
        assert pool.configured is True

    def test_blanks_and_whitespace_are_dropped(self):
        """A trailing comma in .env otherwise contributes a phantom key."""
        pool = SarvamKeyPool(["sk-a", "", "  ", "  sk-b  "])
        assert len(pool) == 2
        assert pool.acquire() == "sk-a"

    def test_duplicates_are_collapsed(self):
        """Two teammates pasting the same key should not look like two accounts."""
        pool = SarvamKeyPool(["sk-a", "sk-a", "sk-b"])
        assert len(pool) == 2

    def test_empty_pool_is_not_configured(self):
        pool = SarvamKeyPool([])
        assert pool.configured is False
        assert pool.acquire() is None

    def test_status_never_leaks_key_material(self):
        """Health output goes to logs, so it must carry no usable secret."""
        pool = SarvamKeyPool(["sk-supersecret-value"])
        rendered = repr(pool.status())
        assert "supersecret" not in rendered
        assert "sk-supersecret-value" not in rendered


class TestRotationOrder:
    def test_serves_the_first_key_while_it_is_healthy(self):
        pool = SarvamKeyPool(SIX_KEYS)
        assert pool.acquire() == "sk-team-1"
        assert pool.acquire() == "sk-team-1", "must not round-robin needlessly"

    def test_moves_to_the_next_key_once_one_is_spent(self):
        pool = SarvamKeyPool(SIX_KEYS)
        pool.report_failure("sk-team-1", 402)
        assert pool.acquire() == "sk-team-2"

    def test_walks_the_whole_team_in_order(self):
        pool = SarvamKeyPool(SIX_KEYS)
        for n in range(1, 7):
            assert pool.acquire() == f"sk-team-{n}"
            pool.report_failure(f"sk-team-{n}", 402)
        assert pool.acquire() is None, "pool is spent"

    def test_a_parked_key_is_never_handed_out_again(self):
        """The whole point: no repeat round-trips to a dead account."""
        pool = SarvamKeyPool(SIX_KEYS)
        pool.report_failure("sk-team-1", 402)

        for _ in range(20):
            assert pool.acquire() != "sk-team-1"


class TestFailureClassification:
    @pytest.mark.parametrize("status", sorted(EXHAUSTED_STATUSES))
    def test_billing_statuses_park_the_key(self, status):
        pool = SarvamKeyPool(["sk-a", "sk-b"])
        pool.report_failure("sk-a", status)

        entry = next(s for s in pool.status() if s["key"].endswith("sk-a"[-4:]))
        assert entry["exhausted"] is True
        assert entry["available"] is False

    def test_rate_limit_is_a_cooldown_not_a_death_sentence(self):
        """429 says "too fast", not "out of credit" — the key must come back."""
        pool = SarvamKeyPool(["sk-a", "sk-b"])
        pool.report_failure("sk-a", RATE_LIMITED_STATUS)

        entry = pool.status()[0]
        assert entry["exhausted"] is False
        assert entry["cooldown_seconds"] > 0
        assert pool.acquire() == "sk-b", "meanwhile serve someone else's key"

    def test_cooled_key_returns_to_service(self, monkeypatch):
        pool = SarvamKeyPool(["sk-a", "sk-b"])
        pool.report_failure("sk-a", RATE_LIMITED_STATUS)
        assert pool.acquire() == "sk-b"

        # Jump past the cooldown rather than sleeping through it.
        base = sk.time.monotonic()
        monkeypatch.setattr(sk.time, "monotonic", lambda: base + 3600)

        assert pool.acquire() == "sk-a"

    @pytest.mark.parametrize("status", [400, 404, 413, 422, 500, 503])
    def test_request_errors_do_not_burn_keys(self, status):
        """A malformed document fails identically everywhere.

        Rotating on it would spend the entire team's pool on one bad upload.
        """
        pool = SarvamKeyPool(SIX_KEYS)
        rotated = pool.report_failure("sk-team-1", status)

        assert rotated is False
        assert pool.acquire() == "sk-team-1"
        assert all(not s["exhausted"] for s in pool.status())

    def test_report_failure_says_whether_another_key_exists(self):
        pool = SarvamKeyPool(["sk-a", "sk-b"])
        assert pool.report_failure("sk-a", 402) is True, "sk-b remains"
        assert pool.report_failure("sk-b", 402) is False, "nothing left"

    def test_unknown_key_is_ignored(self):
        pool = SarvamKeyPool(["sk-a"])
        assert pool.report_failure("sk-not-in-pool", 402) is False
        assert pool.acquire() == "sk-a"

    def test_success_clears_a_cooldown_early(self):
        pool = SarvamKeyPool(["sk-a", "sk-b"])
        pool.report_failure("sk-a", RATE_LIMITED_STATUS)
        pool.report_success("sk-a")
        assert pool.acquire() == "sk-a"

    def test_success_cannot_revive_an_exhausted_key(self):
        """Credits do not come back because a later call happened to work."""
        pool = SarvamKeyPool(["sk-a", "sk-b"])
        pool.report_failure("sk-a", 402)
        pool.report_success("sk-a")
        assert pool.acquire() == "sk-b"


class TestExhaustion:
    def test_drained_pool_returns_none_rather_than_raising(self):
        """None is a normal outcome: callers degrade to their own fallback."""
        pool = SarvamKeyPool(["sk-a"])
        pool.report_failure("sk-a", 402)
        assert pool.acquire() is None

    def test_failure_counts_are_tracked_per_key(self):
        pool = SarvamKeyPool(["sk-a", "sk-b"])
        pool.report_failure("sk-a", 429)
        pool.report_failure("sk-a", 429)

        entry = pool.status()[0]
        assert entry["failures"] == 2
        assert entry["last_status"] == 429


class TestUnboundedPoolSize:
    """The pool is however many keys exist — no declared maximum.

    Team size is not known up front, so anything that assumes a fixed count
    would silently drop a teammate's contribution.
    """

    @pytest.mark.parametrize("count", [1, 2, 7, 13, 40])
    def test_any_number_of_keys_is_accepted(self, count):
        pool = SarvamKeyPool([f"sk-{n}" for n in range(count)])

        assert len(pool) == count
        assert pool.summary()["total"] == count
        assert pool.summary()["available"] == count

    @pytest.mark.parametrize("count", [1, 3, 11, 25])
    def test_every_key_gets_used_before_the_pool_is_spent(self, count):
        reset_pool([f"sk-{n}" for n in range(count)])

        used = []
        for _ in range(count):
            key = acquire_key()
            assert key is not None
            used.append(key)
            report_key_failure(key, 402)

        assert len(set(used)) == count, "each key must be tried exactly once"
        assert acquire_key() is None

    def test_attempt_budget_tracks_the_actual_count(self):
        reset_pool([f"sk-{n}" for n in range(17)])
        assert attempt_budget() == 17


class TestNumberedKeyAutoDiscovery:
    """SARVAM_API_KEY_1, _2, _3 … discovered without declaring how many.

    Lets each teammate append one line instead of everyone editing a shared
    comma-separated string, which is where lost keys and typos come from.
    """

    def test_numbered_keys_are_picked_up(self, monkeypatch):
        monkeypatch.delenv("SARVAM_API_KEYS", raising=False)
        monkeypatch.delenv("SARVAM_API_KEY", raising=False)
        for n in range(1, 5):
            monkeypatch.setenv(f"SARVAM_API_KEY_{n}", f"sk-{n}")

        pool = reset_pool()

        assert len(pool) == 4
        assert pool.acquire() == "sk-1"

    def test_ordering_is_numeric_not_lexicographic(self, monkeypatch):
        """Name sort would place _10 between _1 and _2."""
        monkeypatch.delenv("SARVAM_API_KEYS", raising=False)
        monkeypatch.delenv("SARVAM_API_KEY", raising=False)
        for n in (1, 2, 10, 11):
            monkeypatch.setenv(f"SARVAM_API_KEY_{n}", f"sk-{n}")

        reset_pool()

        order = []
        for _ in range(4):
            key = acquire_key()
            order.append(key)
            report_key_failure(key, 402)

        assert order == ["sk-1", "sk-2", "sk-10", "sk-11"]

    def test_gaps_in_numbering_are_fine(self, monkeypatch):
        """A teammate leaving does not require renumbering everyone else."""
        monkeypatch.delenv("SARVAM_API_KEYS", raising=False)
        monkeypatch.delenv("SARVAM_API_KEY", raising=False)
        monkeypatch.setenv("SARVAM_API_KEY_1", "sk-1")
        monkeypatch.setenv("SARVAM_API_KEY_5", "sk-5")

        pool = reset_pool()

        assert len(pool) == 2
        assert pool.acquire() == "sk-1"

    def test_plural_variable_is_not_mistaken_for_a_numbered_one(self, monkeypatch):
        """SARVAM_API_KEYS must not be swallowed by the numbered pattern."""
        monkeypatch.setenv("SARVAM_API_KEYS", "sk-csv-a,sk-csv-b")
        monkeypatch.delenv("SARVAM_API_KEY", raising=False)

        pool = reset_pool()

        assert len(pool) == 2
        assert pool.acquire() == "sk-csv-a"

    def test_blank_numbered_entries_are_skipped(self, monkeypatch):
        monkeypatch.delenv("SARVAM_API_KEYS", raising=False)
        monkeypatch.delenv("SARVAM_API_KEY", raising=False)
        monkeypatch.setenv("SARVAM_API_KEY_1", "sk-1")
        monkeypatch.setenv("SARVAM_API_KEY_2", "")

        assert len(reset_pool()) == 1

    def test_all_three_sources_combine(self, monkeypatch):
        monkeypatch.setenv("SARVAM_API_KEYS", "sk-csv")
        monkeypatch.setenv("SARVAM_API_KEY_1", "sk-numbered")
        monkeypatch.setenv("SARVAM_API_KEY", "sk-single")

        pool = reset_pool()

        assert len(pool) == 3

    def test_a_key_listed_twice_across_sources_counts_once(self, monkeypatch):
        monkeypatch.setenv("SARVAM_API_KEYS", "sk-shared")
        monkeypatch.setenv("SARVAM_API_KEY_1", "sk-shared")
        monkeypatch.setenv("SARVAM_API_KEY", "sk-shared")

        assert len(reset_pool()) == 1


class TestSummaryForHealthEndpoint:
    def test_counts_reflect_key_health(self):
        pool = SarvamKeyPool(["sk-a", "sk-b", "sk-c"])
        pool.report_failure("sk-a", 402)
        pool.report_failure("sk-b", RATE_LIMITED_STATUS)

        assert pool.summary() == {
            "total": 3,
            "available": 1,
            "exhausted": 1,
            "cooling_down": 1,
        }

    def test_summary_exposes_no_key_material_at_all(self):
        """/health is unauthenticated, so not even a redacted label belongs."""
        pool = SarvamKeyPool(["sk-supersecret-abcd"])
        rendered = repr(pool.summary())

        assert "abcd" not in rendered
        assert "supersecret" not in rendered
        assert set(pool.summary()) == {"total", "available", "exhausted", "cooling_down"}


class TestEnvironmentWiring:
    def test_pooled_keys_are_read_from_sarvam_api_keys(self, monkeypatch):
        monkeypatch.setenv("SARVAM_API_KEYS", ",".join(SIX_KEYS))
        monkeypatch.delenv("SARVAM_API_KEY", raising=False)

        pool = reset_pool()

        assert len(pool) == 6
        assert pool.acquire() == "sk-team-1"

    def test_single_key_setting_still_works(self, monkeypatch):
        """Existing .env files must keep working untouched."""
        monkeypatch.delenv("SARVAM_API_KEYS", raising=False)
        monkeypatch.setenv("SARVAM_API_KEY", "sk-solo")

        pool = reset_pool()

        assert len(pool) == 1
        assert pool.acquire() == "sk-solo"

    def test_pooled_and_single_are_combined_without_duplication(self, monkeypatch):
        monkeypatch.setenv("SARVAM_API_KEYS", "sk-a,sk-b")
        monkeypatch.setenv("SARVAM_API_KEY", "sk-a")

        pool = reset_pool()

        assert len(pool) == 2, "sk-a appears in both and must count once"


class TestCallSiteHelpers:
    def test_unconfigured_pool_falls_back_to_a_single_key(self):
        """Keeps every pre-pooling deployment behaving exactly as before."""
        reset_pool([])
        assert acquire_key("sk-legacy") == "sk-legacy"
        assert acquire_key() is None

    def test_pool_takes_precedence_over_the_fallback(self):
        reset_pool(["sk-pooled"])
        assert acquire_key("sk-legacy") == "sk-pooled"

    def test_attempt_budget_is_one_key_per_attempt(self):
        reset_pool(SIX_KEYS)
        assert attempt_budget() == 6

    def test_attempt_budget_is_at_least_one(self):
        """An unconfigured pool must still make its single attempt."""
        reset_pool([])
        assert attempt_budget() == 1

    def test_failure_on_the_legacy_key_does_not_rotate(self):
        reset_pool([])
        assert report_key_failure("sk-legacy", 402, fallback="sk-legacy") is False

    def test_helpers_share_state_across_services(self):
        """TTS, STT and OCR must see the same exhaustion, not each rediscover it."""
        reset_pool(["sk-a", "sk-b"])

        # TTS burns the first key...
        assert acquire_key() == "sk-a"
        report_key_failure("sk-a", 402)

        # ...and OCR, a separate call site, must not retry it.
        assert acquire_key() == "sk-b"
