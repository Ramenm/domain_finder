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
    """Deduplicating writer for generated and checked domain results."""

    CSV_FIELDS = ["domain", "status", "available", "source", "checked_at", "detail"]

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

    @classmethod
    def _normalize_existing_row(cls, row: dict[str, str]) -> dict[str, str]:
        normalized = {field: row.get(field, "") or "" for field in cls.CSV_FIELDS}
        if not normalized["status"]:
            available = normalized["available"].strip().lower()
            if normalized["source"] == "skipped":
                normalized["status"] = "skipped"
            elif available == "true":
                normalized["status"] = "registrable"
            elif available == "false":
                normalized["status"] = "registered"
        return normalized

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
                    normalized = self._normalize_existing_row(row)
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

    @staticmethod
    def _availability_text(result: DomainCheckResult) -> str:
        if result.available is True:
            return "true"
        if result.available is False:
            return "false"
        return ""

    def append_check_results(self, results: Iterable[DomainCheckResult]) -> None:
        """Persist every checked result and upgrade any older unchecked row."""
        records: dict[str, DomainCheckResult] = {}
        for result in results:
            records[result.domain] = result
        if not records:
            return

        with self._lock:
            self._append_txt_once(
                result.domain for result in records.values() if result.is_registrable
            )
            self._upsert_csv(
                [
                    {
                        "domain": result.domain,
                        "status": result.status.value if result.status else "unknown",
                        "available": self._availability_text(result),
                        "source": result.source,
                        "checked_at": str(int(result.checked_at)),
                        "detail": result.detail or "",
                    }
                    for result in records.values()
                ],
                overwrite=True,
            )

    def append_available(self, domain_records: Iterable[tuple[str, str, float]]) -> None:
        """Persist confirmed registrable domains for compatibility callers."""
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
                        "status": "registrable",
                        "available": "true",
                        "source": source,
                        "checked_at": str(int(checked_at)),
                        "detail": "",
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
                        "status": "skipped",
                        "available": "",
                        "source": "skipped",
                        "checked_at": "",
                        "detail": "",
                    }
                    for domain in unique
                ],
                overwrite=False,
            )

    def append_results(self, results: list[DomainCheckResult]) -> None:
        self.append_check_results(results)

    @staticmethod
    def show_table(domains: list[str], title: str = "Confirmed Registrable Domains") -> None:
        """Display a list of domain names in a formatted table."""
        table = Table(title=title, show_lines=True, box=box.ROUNDED)
        table.add_column("#", justify="right", style="cyan")
        table.add_column("Domain", justify="left", style="green")
        for i, domain in enumerate(domains, start=1):
            table.add_row(str(i), domain)
        console.print(table)
