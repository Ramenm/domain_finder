from __future__ import annotations

from domain_finder.application.dto import DomainSearchRequest
from domain_finder.application.use_cases import RunDomainSearchUseCase
from domain_finder.domain.errors import ProviderError
from domain_finder.domain.models import DomainCheckResult, DomainCheckStatus, DomainSearchParams


class Provider:
    def generate_domains(self, params: DomainSearchParams) -> str:
        return "alpha.com"


class FailingProvider:
    def generate_domains(self, params: DomainSearchParams) -> str:
        raise ProviderError("provider down")


class Checker:
    def check_domain(self, domain: str) -> DomainCheckResult:
        return self.check_domains([domain])[domain]

    def check_domains(self, domains: list[str]) -> dict[str, DomainCheckResult]:
        return {
            domain: DomainCheckResult(
                domain=domain,
                status=DomainCheckStatus.REGISTERED,
                source="rdap",
                checked_at=1.0,
            )
            for domain in domains
        }


class Repo:
    def get_cached_result(self, domain: str):
        return None

    def cache_result(self, result: DomainCheckResult) -> None:
        pass

    def save_available_domains(self, domains) -> None:
        pass


class Writer:
    def append_check_results(self, results) -> None:
        pass

    def append_unchecked(self, domains) -> None:
        pass


def test_use_case_emits_phase_level_progress_events() -> None:
    events = []
    use_case = RunDomainSearchUseCase(
        Provider(), Checker(), Repo(), Writer(), progress_callback=events.append
    )
    use_case.execute(DomainSearchRequest(topic="test", iterations=1, per_request=1, cooldown=0))

    assert [event.phase for event in events] == [
        "generation_start",
        "generation_complete",
        "checking_start",
        "checking_complete",
    ]
    assert all(event.iteration == 1 for event in events)
    assert all(event.iterations == 1 for event in events)


def test_use_case_emits_generation_failed_event() -> None:
    events = []
    result = RunDomainSearchUseCase(
        FailingProvider(), Checker(), Repo(), Writer(), progress_callback=events.append
    ).execute(DomainSearchRequest(topic="test", iterations=1, cooldown=0))

    assert result.iterations_failed == 1
    assert [event.phase for event in events] == ["generation_start", "generation_failed"]
