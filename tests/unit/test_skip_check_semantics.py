from __future__ import annotations

import csv
from pathlib import Path

from domain_finder.application.dto import DomainSearchRequest
from domain_finder.application.use_cases import RunDomainSearchUseCase
from domain_finder.domain.models import DomainSearchParams
from domain_finder.infrastructure.persistence import ResultWriter


class StaticProvider:
    def generate_domains(self, params: DomainSearchParams) -> str:
        return '["alphaedge.com"]'


class NeverChecker:
    def check_domain(self, domain: str):
        raise AssertionError("checker must not run when skip_check=True")

    def check_domains(self, domains: list[str]):
        raise AssertionError("checker must not run when skip_check=True")


class EmptyRepo:
    def get_cached_result(self, domain: str):
        return None

    def cache_result(self, result) -> None:
        pass

    def save_available_domains(self, domains) -> None:
        pass


def test_skip_check_saves_generated_domains_without_claiming_availability(tmp_path: Path) -> None:
    txt = tmp_path / "results.txt"
    report = tmp_path / "results.csv"
    use_case = RunDomainSearchUseCase(
        StaticProvider(),
        NeverChecker(),
        EmptyRepo(),
        ResultWriter(str(txt), str(report)),
    )

    result = use_case.execute(
        DomainSearchRequest(
            topic="developer tools",
            iterations=1,
            per_request=1,
            skip_check=True,
            cooldown=0,
            results_txt=str(txt),
            results_csv=str(report),
        )
    )

    assert result.total_generated == 1
    assert result.total_available == 0
    assert result.available_domains == []
    assert txt.read_text(encoding="utf-8").splitlines() == ["alphaedge.com"]
    with report.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert rows == [
        {
            "domain": "alphaedge.com",
            "status": "skipped",
            "available": "",
            "source": "skipped",
            "checked_at": "",
            "detail": "",
        }
    ]
