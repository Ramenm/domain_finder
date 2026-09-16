"""Result persistence implementation."""

from __future__ import annotations

import csv
import threading
from collections.abc import Iterable
from pathlib import Path

from rich import box
from rich.console import Console
from rich.table import Table

from domain_finder.domain.models import DomainCheckResult

console = Console()


class ResultWriter:
    """Deduplicating writer for generated and confirmed domain results."""

    CSV_FIELDS = ["domain", "available", "source", "checked_at"]

    def __init__(
        self,
        txt_path: str = "results.txt",
        csv_path: str | None = "results.csv",
    ) -> None:
        self.txt_path = Path(txt_path)
        self.csv_path = Path(csv_path) if csv_path else None
        self.txt_path.parent.mkdir(parents=True, exist_ok=True)
        if self.csv_path:
            self.csv_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

        if not self.txt_path.exists():
            self.txt_path.write_text("", encoding="utf-8")
        self._seen = {
            line.strip()
            for line in self.txt_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        }

        if self.csv_path and (not self.csv_path.exists() or self.csv_path.stat().st_size == 0):
            with self.csv_path.open("w", newline="", encoding="utf-8") as handle:
                csv.DictWriter(handle, fieldnames=self.CSV_FIELDS).writeheader()

    def _append_txt_once(self, domains: Iterable[str]) -> None:
        pending: list[str] = []
        for domain in domains:
            if domain in self._seen:
                continue
            self._seen.add(domain)
            pending.append(domain)
        if not pending:
            return
        with self.txt_path.open("a", encoding="utf-8") as handle:
            for domain in pending:
                handle.write(f"{domain}\n")

    def _upsert_csv(self, new_rows: list[dict[str, str]], *, overwrite: bool) -> None:
        if self.csv_path is None or not new_rows:
            return

        rows: list[dict[str, str]] = []
        positions: dict[str, int] = {}
        if self.csv_path.exists() and self.csv_path.stat().st_size:
            with self.csv_path.open(newline="", encoding="utf-8") as handle:
                for row in csv.DictReader(handle):
                    domain = row.get("domain", "").strip()
                    if not domain:
                        continue
                    normalized = {field: row.get(field, "") for field in self.CSV_FIELDS}
                    if domain in positions:
                        rows[positions[domain]] = normalized
                    else:
                        positions[domain] = len(rows)
                        rows.append(normalized)

        for row in new_rows:
            domain = row["domain"]
            if domain in positions:
                if overwrite:
                    rows[positions[domain]] = row
                continue
            positions[domain] = len(rows)
            rows.append(row)

        tmp_path = self.csv_path.with_name(f"{self.csv_path.name}.tmp")
        with tmp_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=self.CSV_FIELDS)
            writer.writeheader()
            writer.writerows(rows)
        tmp_path.replace(self.csv_path)

    def append_available(self, domain_records: Iterable[tuple[str, str, float]]) -> None:
        """Persist confirmed registrable domains, upgrading unchecked rows when needed."""
        records: dict[str, tuple[str, str, float]] = {}
        for domain, source, checked_at in domain_records:
            records.setdefault(domain, (domain, source, checked_at))
        if not records:
            return
        with self._lock:
            self._append_txt_once(records)
            self._upsert_csv(
                [
                    {
                        "domain": domain,
                        "available": "true",
                        "source": source,
                        "checked_at": str(int(checked_at)),
                    }
                    for domain, source, checked_at in records.values()
                ],
                overwrite=True,
            )

    def append_unchecked(self, domains: Iterable[str]) -> None:
        """Persist generated domains without claiming registry availability."""
        unique = list(dict.fromkeys(domains))
        if not unique:
            return
        with self._lock:
            self._append_txt_once(unique)
            self._upsert_csv(
                [
                    {
                        "domain": domain,
                        "available": "",
                        "source": "skipped",
                        "checked_at": "",
                    }
                    for domain in unique
                ],
                overwrite=False,
            )

    def append_results(self, results: list[DomainCheckResult]) -> None:
        available_records = [
            (result.domain, result.source, result.checked_at)
            for result in results
            if result.available is True
        ]
        self.append_available(available_records)

    @staticmethod
    def show_table(domains: list[str], title: str = "Confirmed Registrable Domains") -> None:
        """Display a list of domain names in a formatted table."""
        table = Table(title=title, show_lines=True, box=box.ROUNDED)
        table.add_column("#", justify="right", style="cyan")
        table.add_column("Domain", justify="left", style="green")
        for i, domain in enumerate(domains, start=1):
            table.add_row(str(i), domain)
        console.print(table)
