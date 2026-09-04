from __future__ import annotations

import pytest

from domain_finder.infrastructure.whois.host_limiter import PerHostLimiter


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def test_rate_limit_penalty_spaces_future_requests() -> None:
    clock = FakeClock()
    limiter = PerHostLimiter(per_host=2, clock=clock.monotonic, sleeper=clock.sleep)
    limiter.penalize("registry.example")

    with limiter.acquire("registry.example"):
        pass
    with limiter.acquire("registry.example"):
        pass

    assert clock.sleeps == pytest.approx([0.25, 0.25])


def test_penalty_is_isolated_per_host() -> None:
    clock = FakeClock()
    limiter = PerHostLimiter(per_host=1, clock=clock.monotonic, sleeper=clock.sleep)
    limiter.penalize("slow.example")

    with limiter.acquire("fast.example"):
        pass

    assert clock.sleeps == []


def test_success_gradually_recovers_rate() -> None:
    clock = FakeClock()
    limiter = PerHostLimiter(per_host=1, clock=clock.monotonic, sleeper=clock.sleep)
    limiter.penalize("registry.example")
    before = limiter.rate_interval("registry.example")

    limiter.reward("registry.example")

    assert 0 <= limiter.rate_interval("registry.example") < before


def test_retry_after_can_raise_penalty_floor() -> None:
    clock = FakeClock()
    limiter = PerHostLimiter(per_host=1, clock=clock.monotonic, sleeper=clock.sleep)
    limiter.penalize("registry.example", retry_after=2.0)
    assert limiter.rate_interval("registry.example") == pytest.approx(2.0)


def test_throttle_window_expires_without_permanent_whois_diversion() -> None:
    clock = FakeClock()
    limiter = PerHostLimiter(per_host=1, clock=clock.monotonic, sleeper=clock.sleep)
    limiter.penalize("registry.example")
    assert limiter.is_throttled("registry.example") is True

    clock.now += 0.3

    assert limiter.is_throttled("registry.example") is False


def test_waiting_request_observes_penalty_set_while_queued() -> None:
    import threading

    clock = FakeClock()
    limiter = PerHostLimiter(per_host=1, clock=clock.monotonic, sleeper=clock.sleep)
    first_entered = threading.Event()
    release_first = threading.Event()
    second_done = threading.Event()

    def first() -> None:
        with limiter.acquire("shared.registry"):
            first_entered.set()
            release_first.wait(timeout=2)

    def second() -> None:
        with limiter.acquire("shared.registry"):
            second_done.set()

    t1 = threading.Thread(target=first)
    t2 = threading.Thread(target=second)
    t1.start()
    first_entered.wait(timeout=2)
    t2.start()
    limiter.penalize("shared.registry", retry_after=1.0)
    release_first.set()
    t1.join(timeout=2)
    t2.join(timeout=2)

    assert second_done.is_set()
    assert clock.now >= 1.0


def test_rate_limit_reduces_backend_concurrency() -> None:
    limiter = PerHostLimiter(per_host=6)
    assert limiter.current_limit("registry.example") == 6

    limiter.penalize("registry.example")

    assert limiter.current_limit("registry.example") == 3


def test_definitive_successes_gradually_restore_backend_concurrency() -> None:
    limiter = PerHostLimiter(per_host=6)
    limiter.penalize("registry.example")
    reduced = limiter.current_limit("registry.example")

    for _ in range(10):
        limiter.reward("registry.example")

    assert limiter.current_limit("registry.example") > reduced
    assert limiter.current_limit("registry.example") <= 6
