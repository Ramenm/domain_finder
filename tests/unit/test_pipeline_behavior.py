from __future__ import annotations

import pytest

from domain_finder.application.dto import DomainSearchRequest
from domain_finder.application.use_cases import RunDomainSearchUseCase
from domain_finder.domain.errors import ProviderError
from domain_finder.domain.models import DomainSearchParams


class FailingProvider:
    def generate_domains(self, params: DomainSearchParams) -> str:
        raise ProviderError("provider unavailable")


class NoopChecker:
    def check_domain(self, domain):
        raise NotImplementedError

    def check_domains(self, domains):
        return {}


class NoopRepo:
    def get_cached_result(self, domain):
        return None

    def cache_result(self, result):
        pass

    def save_available_domains(self, domains):
        pass


class NoopWriter:
    def append_available(self, records):
        pass


def test_all_failed_parallel_workers_raise_provider_error() -> None:
    use_case = RunDomainSearchUseCase(FailingProvider(), NoopChecker(), NoopRepo(), NoopWriter())
    params = DomainSearchParams(topic="test", tlds=["com"], count=4, min_len=4, max_len=15)
    with pytest.raises(ProviderError):
        use_case._generate_domains_parallel(params, workers=4)


def test_failed_iterations_are_reported_as_failed_not_completed() -> None:
    use_case = RunDomainSearchUseCase(FailingProvider(), NoopChecker(), NoopRepo(), NoopWriter())
    result = use_case.execute(
        DomainSearchRequest(topic="test", iterations=3, llm_workers=1, skip_check=True, cooldown=0)
    )
    assert result.iterations_attempted == 3
    assert result.iterations_completed == 0
    assert result.iterations_failed == 3
    assert result.total_iterations == 0


def test_default_cooldown_is_zero() -> None:
    assert DomainSearchRequest(topic="test").cooldown == 0.0


def test_safe_whois_fallback_is_enabled_by_default() -> None:
    request = DomainSearchRequest(topic="test")
    assert request.whois_fallback is True
