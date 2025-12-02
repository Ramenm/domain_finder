"""Result persistence implementation."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, List, Optional, Tuple

from rich import box
from rich.console import Console
from rich.table import Table

from domain_finder.domain.models import DomainCheckResult

console = Console()


class ResultWriter:
    """Writer for domain search results to files."""

    def __init__(
        self,
        txt_path: str = "results.txt",
        csv_path: Optional[str] = "results.csv",
    ) -> None:
        """
        Initialize result writer.

        Args:
            txt_path: Path to text file for available domains
            csv_path: Optional path to CSV file for detailed results
        """
        self.txt_path = Path(txt_path)
        self.csv_path = Path(csv_path) if csv_path else None

        # Ensure files exist
        if not self.txt_path.exists():
            self.txt_path.write_text("", encoding="utf-8")
        if self.csv_path and not self.csv_path.exists():
            self.csv_path.write_text("domain,available,source,checked_at\n", encoding="utf-8")

    def append_available(self, domain_records: Iterable[Tuple[str, str, float]]) -> None:
        """
        Append available domains to output files.

        Args:
            domain_records: Iterable of tuples (domain, source, checked_at)
        """
        with self.txt_path.open("a", encoding="utf-8") as f_txt:
            for domain, source, ts in domain_records:
                f_txt.write(f"{domain}\n")

        if self.csv_path:
            with self.csv_path.open("a", encoding="utf-8") as f_csv:
                for domain, source, ts in domain_records:
                    f_csv.write(f"{domain},true,{source},{int(ts)}\n")

    def append_results(self, results: List[DomainCheckResult]) -> None:
        """
        Append domain check results to output files.

        Args:
            results: List of domain check results
        """
        available_records = [
            (r.domain, r.source, r.checked_at) for r in results if r.available
        ]
        if available_records:
            self.append_available(available_records)

    @staticmethod
    def show_table(available: List[str]) -> None:
        """
        Display available domains in a formatted table.

        Args:
            available: List of available domain names
        """
        table = Table(title="Найденные доступные домены", show_lines=True, box=box.ROUNDED)
        table.add_column("#", justify="right", style="cyan")
        table.add_column("Домен", justify="left", style="green")
        for i, domain in enumerate(available, start=1):
            table.add_row(str(i), domain)
        console.print(table)

