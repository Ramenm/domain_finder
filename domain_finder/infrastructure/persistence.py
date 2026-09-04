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
    """Deduplicating writer for available domain results."""

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
                csv.writer(handle).writerow(["domain", "available", "source", "checked_at"])

    def append_available(self, domain_records: Iterable[tuple[str, str, float]]) -> None:
        """Append each domain once, safely consuming one-shot iterables."""
        records = list(domain_records)
        if not records:
            return
        with self._lock:
            unique: list[tuple[str, str, float]] = []
            for domain, source, checked_at in records:
                if domain in self._seen:
                    continue
                self._seen.add(domain)
                unique.append((domain, source, checked_at))
            if not unique:
                return

            with self.txt_path.open("a", encoding="utf-8") as handle:
                for domain, _source, _checked_at in unique:
                    handle.write(f"{domain}\n")

            if self.csv_path:
                with self.csv_path.open("a", newline="", encoding="utf-8") as handle:
                    writer = csv.writer(handle)
                    for domain, source, checked_at in unique:
                        writer.writerow([domain, "true", source, int(checked_at)])

    def append_results(self, results: list[DomainCheckResult]) -> None:
        available_records = [
            (result.domain, result.source, result.checked_at)
            for result in results
            if result.available is True
        ]
        self.append_available(available_records)

    @staticmethod
    def show_table(available: list[str]) -> None:
        """
        Display available domains in a formatted table.

        Args:
            available: List of available domain names
        """
        table = Table(title="Found Available Domains", show_lines=True, box=box.ROUNDED)
        table.add_column("#", justify="right", style="cyan")
        table.add_column("Domain", justify="left", style="green")
        for i, domain in enumerate(available, start=1):
            table.add_row(str(i), domain)
        console.print(table)
