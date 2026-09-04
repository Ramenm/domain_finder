from __future__ import annotations

import threading
import time
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass


@dataclass
class _HostState:
    interval: float
    concurrency_limit: int
    next_start: float = 0.0
    in_flight: int = 0
    success_streak: int = 0


class PerHostLimiter:
    """Adapt concurrency and request spacing independently per registry backend."""

    def __init__(
        self,
        per_host: int = 6,
        global_limit: int | None = None,
        min_interval: float = 0.0,
        max_interval: float = 5.0,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if per_host < 1:
            raise ValueError("per_host must be >= 1")
        if min_interval < 0 or max_interval < min_interval:
            raise ValueError("invalid rate interval bounds")
        self.per_host = per_host
        self.min_interval = min_interval
        self.max_interval = max_interval
        self._global = threading.BoundedSemaphore(global_limit) if global_limit else None
        self._clock = clock
        self._sleep = sleeper
        self._lock = threading.RLock()
        self._condition = threading.Condition(self._lock)
        self._hosts: dict[str, _HostState] = {}

    def _state_for_host(self, host: str) -> _HostState:
        with self._lock:
            state = self._hosts.get(host)
            if state is None:
                state = _HostState(
                    interval=self.min_interval,
                    concurrency_limit=self.per_host,
                )
                self._hosts[host] = state
            return state

    def _acquire_host_slot(self, host: str) -> _HostState:
        with self._condition:
            state = self._state_for_host(host)
            while state.in_flight >= state.concurrency_limit:
                self._condition.wait()
            state.in_flight += 1
            return state

    def _release_host_slot(self, state: _HostState) -> None:
        with self._condition:
            state.in_flight -= 1
            self._condition.notify_all()

    def _wait_for_rate_slot(self, host: str) -> None:
        with self._lock:
            state = self._state_for_host(host)
            now = self._clock()
            start_at = max(now, state.next_start)
            wait = start_at - now
            state.next_start = start_at + state.interval
        if wait > 0:
            self._sleep(wait)

    def penalize(self, host: str, retry_after: float | None = None) -> None:
        """Slow only the backend that reported a quota/rate-limit signal."""
        state = self._state_for_host(host)
        with self._condition:
            grown = max(0.25, state.interval * 2 if state.interval else 0.25)
            if retry_after is not None:
                grown = max(grown, retry_after)
            state.interval = min(self.max_interval, grown)
            state.next_start = max(state.next_start, self._clock() + state.interval)
            state.concurrency_limit = max(1, state.concurrency_limit // 2)
            state.success_streak = 0
            self._condition.notify_all()

    def reward(self, host: str) -> None:
        """Recover spacing first, then concurrency after a stable success streak."""
        state = self._state_for_host(host)
        with self._condition:
            if state.interval > self.min_interval:
                state.interval = max(self.min_interval, state.interval * 0.8 - 0.01)
            state.success_streak += 1
            recovery_threshold = max(self.min_interval, 0.05)
            if (
                state.success_streak >= 8
                and state.concurrency_limit < self.per_host
                and state.interval <= recovery_threshold
            ):
                state.concurrency_limit += 1
                state.success_streak = 0
                self._condition.notify_all()

    def rate_interval(self, host: str) -> float:
        state = self._state_for_host(host)
        with self._lock:
            return state.interval

    def current_limit(self, host: str) -> int:
        """Expose the learned concurrency ceiling for diagnostics."""
        state = self._state_for_host(host)
        with self._lock:
            return state.concurrency_limit

    def is_throttled(self, host: str) -> bool:
        state = self._state_for_host(host)
        with self._lock:
            return state.next_start > self._clock()

    @contextmanager
    def acquire(self, host: str):
        # Acquire the adaptive backend slot before computing the rate slot so a
        # queued request observes any penalty learned by the request ahead of it.
        state = self._acquire_host_slot(host)
        global_acquired = False
        try:
            self._wait_for_rate_slot(host)
            if self._global is not None:
                self._global.acquire()
                global_acquired = True
            yield
        finally:
            if global_acquired and self._global is not None:
                self._global.release()
            self._release_host_slot(state)
