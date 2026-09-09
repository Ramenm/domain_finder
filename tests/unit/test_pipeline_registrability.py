from __future__ import annotations

from domain_finder.application.dto import DomainSearchRequest
from domain_finder.application.use_cases import RunDomainSearchUseCase
from domain_finder.domain.models import DomainCheckResult, DomainCheckStatus, DomainSearchParams


class TwoDomainProvider:
    def generate_domains(self, params: DomainSearchParams) -> str:
        return "alpha.com,beta.com"


class RegistrabilityChecker:
    def check_domain(self, domain: str) -> DomainCheckResult:
        return self.check_domains([domain])[domain]

    def check_domains(self, domains: list[str]) -> dict[str, DomainCheckResult]:
        statuses = {
            "alpha.com": DomainCheckStatus.UNREGISTERED,
            "beta.com": DomainCheckStatus.REGISTRABLE,
        }
        return {
            domain: DomainCheckResult(
                domain=domain,
                status=statuses[domain],
                source="rdap" if domain == "alpha.com" else "whois",
                checked_at=1.0,
            )
            for domain in domains
        }


class MemoryRepo:
    def __init__(self) -> None:
        self.items: dict[str, DomainCheckResult] = {}

    def get_cached_result(self, domain: str):
        return self.items.get(domain)

    def cache_result(self, result: DomainCheckResult) -> None:
        self.items[result.domain] = result

    def save_available_domains(self, domains) -> None:
        pass


class RecordingWriter:
    def __init__(self) -> None:
        self.available = []

    def append_available(self, records) -> None:
        self.available.extend(records)


def test_pipeline_reports_unregistered_separately_from_registrable() -> None:
    writer = RecordingWriter()
    use_case = RunDomainSearchUseCase(
        TwoDomainProvider(), RegistrabilityChecker(), MemoryRepo(), writer
    )
    result = use_case.execute(
        DomainSearchRequest(
            topic="test",
            iterations=1,
            per_request=2,
            tlds=["com"],
            cooldown=0,
        )
    )

    assert result.available_domains == ["beta.com"]
    assert result.total_available == 1
    assert result.unregistered_domains == ["alpha.com"]
    assert result.total_unregistered == 1
    assert [row[0] for row in writer.available] == ["beta.com"]
