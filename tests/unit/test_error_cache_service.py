from __future__ import annotations

from domain_finder.domain.models import DomainCheckResult, DomainCheckStatus
from domain_finder.domain.services import DomainCheckService


class Repository:
    def __init__(self) -> None:
        self.cached: list[DomainCheckResult] = []

    def get_cached_result(self, domain: str):
        return None

    def cache_result(self, result: DomainCheckResult) -> None:
        self.cached.append(result)

    def save_available_domains(self, domains):
        pass


class Checker:
    def check_domain(self, domain: str):
        raise NotImplementedError

    def check_domains(self, domains: list[str]):
        return {
            domain: DomainCheckResult(
                domain=domain,
                status=DomainCheckStatus.RATE_LIMITED,
                source="rdap",
                checked_at=1.0,
            )
            for domain in domains
        }


def test_transient_result_is_given_to_ttl_cache() -> None:
    repo = Repository()
    DomainCheckService(Checker(), repo).check_domains_with_cache(["example.com"])
    assert repo.cached[0].status is DomainCheckStatus.RATE_LIMITED
