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
