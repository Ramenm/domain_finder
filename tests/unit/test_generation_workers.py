from __future__ import annotations

import threading

from domain_finder.application.use_cases import RunDomainSearchUseCase
from domain_finder.domain.models import DomainSearchParams


class RecordingProvider:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.strategies: list[str | None] = []

    def generate_domains(self, params: DomainSearchParams) -> str:
        strategy = getattr(params, "strategy", None)
        with self.lock:
            self.strategies.append(strategy)
            index = len(self.strategies)
        return f"name{index:02d}.com"


class Dummy:
    def check_domain(self, domain):
        raise NotImplementedError

    def check_domains(self, domains):
        return {}

    def get_cached_result(self, domain):
        return None

    def cache_result(self, result):
        pass

    def save_available_domains(self, domains):
        pass


class DummyWriter:
    def append_available(self, records):
        pass


def test_parallel_workers_receive_distinct_generation_strategies() -> None:
    provider = RecordingProvider()
    dummy = Dummy()
    use_case = RunDomainSearchUseCase(provider, dummy, dummy, DummyWriter())
    params = DomainSearchParams(
        topic="analytics",
        tlds=["com"],
        count=4,
        min_len=4,
        max_len=15,
    )

    candidates = use_case._generate_domains_parallel(params, workers=4)
    assert len(set(provider.strategies)) == 4
    assert len(candidates) == 4
