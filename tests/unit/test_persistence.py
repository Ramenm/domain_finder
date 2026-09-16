from __future__ import annotations

import csv
from pathlib import Path

from domain_finder.infrastructure.persistence import ResultWriter


def test_append_available_deduplicates_within_and_across_writers(tmp_path: Path) -> None:
    txt = tmp_path / "results.txt"
    report = tmp_path / "results.csv"
    writer = ResultWriter(str(txt), str(report))
    writer.append_available(
        [
            ("alpha.com", "rdap", 1.0),
            ("alpha.com", "rdap", 2.0),
            ("beta.com", "rdap", 3.0),
        ]
    )

    reopened = ResultWriter(str(txt), str(report))
    reopened.append_available([("alpha.com", "rdap", 4.0), ("gamma.com", "rdap", 5.0)])

    assert txt.read_text(encoding="utf-8").splitlines() == ["alpha.com", "beta.com", "gamma.com"]
    with report.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert [row["domain"] for row in rows] == ["alpha.com", "beta.com", "gamma.com"]


def test_generator_records_are_written_to_both_outputs(tmp_path: Path) -> None:
    writer = ResultWriter(str(tmp_path / "results.txt"), str(tmp_path / "results.csv"))
    records = ((domain, "rdap", float(index)) for index, domain in enumerate(["a.com", "b.com"], 1))
    writer.append_available(records)

    assert (tmp_path / "results.txt").read_text(encoding="utf-8").splitlines() == ["a.com", "b.com"]
    with (tmp_path / "results.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert [row["domain"] for row in rows] == ["a.com", "b.com"]


def test_csv_writer_quotes_fields_safely(tmp_path: Path) -> None:
    writer = ResultWriter(str(tmp_path / "results.txt"), str(tmp_path / "results.csv"))
    writer.append_available([("odd,name.com", "rdap,registry", 1.0)])

    with (tmp_path / "results.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["domain"] == "odd,name.com"
    assert rows[0]["source"] == "rdap,registry"


def test_confirmed_result_upgrades_prior_unchecked_record(tmp_path: Path) -> None:
    txt = tmp_path / "results.txt"
    report = tmp_path / "results.csv"
    ResultWriter(str(txt), str(report)).append_unchecked(["alpha.com"])

    reopened = ResultWriter(str(txt), str(report))
    reopened.append_available([("alpha.com", "rdap", 42.0)])

    assert txt.read_text(encoding="utf-8").splitlines() == ["alpha.com"]
    with report.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert rows == [
        {
            "domain": "alpha.com",
            "status": "registrable",
            "available": "true",
            "source": "rdap",
            "checked_at": "42",
            "detail": "",
        }
    ]


def test_append_check_results_persists_all_statuses_and_upgrades_skipped(tmp_path: Path) -> None:
    from domain_finder.domain.models import DomainCheckResult, DomainCheckStatus

    txt = tmp_path / "results.txt"
    report = tmp_path / "results.csv"
    writer = ResultWriter(str(txt), str(report))
    writer.append_unchecked(["taken.com", "maybe.com"])

    writer.append_check_results(
        [
            DomainCheckResult(
                domain="taken.com",
                status=DomainCheckStatus.REGISTERED,
                source="rdap",
                checked_at=42.0,
                detail="domain object exists",
            ),
            DomainCheckResult(
                domain="maybe.com",
                status=DomainCheckStatus.NETWORK_ERROR,
                source="unknown",
                checked_at=43.0,
                detail="timeout",
            ),
        ]
    )

    with report.open(newline="", encoding="utf-8") as handle:
        rows = {row["domain"]: row for row in csv.DictReader(handle)}
    assert rows["taken.com"] == {
        "domain": "taken.com",
        "status": "registered",
        "available": "false",
        "source": "rdap",
        "checked_at": "42",
        "detail": "domain object exists",
    }
    assert rows["maybe.com"] == {
        "domain": "maybe.com",
        "status": "network_error",
        "available": "",
        "source": "unknown",
        "checked_at": "43",
        "detail": "timeout",
    }


def test_legacy_csv_is_migrated_when_new_result_is_written(tmp_path: Path) -> None:
    from domain_finder.domain.models import DomainCheckResult, DomainCheckStatus

    txt = tmp_path / "results.txt"
    report = tmp_path / "results.csv"
    report.write_text(
        "domain,available,source,checked_at\nalpha.com,,skipped,\n",
        encoding="utf-8",
    )
    writer = ResultWriter(str(txt), str(report))
    writer.append_check_results(
        [
            DomainCheckResult(
                domain="alpha.com",
                status=DomainCheckStatus.RESERVED,
                source="policy",
                checked_at=50.0,
                detail="reserved name",
            )
        ]
    )

    with report.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["status"] == "reserved"
    assert rows[0]["available"] == "false"
    assert rows[0]["detail"] == "reserved name"
