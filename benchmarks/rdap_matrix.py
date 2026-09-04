"""Reproducible cross-TLD live benchmark for Domain Finder checkers."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

REGISTERED = {
    "com": "google.com",
    "net": "speedtest.net",
    "org": "wikipedia.org",
    "io": "github.io",
    "ai": "character.ai",
    "dev": "web.dev",
    "app": "cash.app",
    "xyz": "abc.xyz",
    "me": "about.me",
    "de": "google.de",
    "uk": "gov.uk",
}


def deterministic_label(tld: str, attempt: int) -> str:
    digest = hashlib.sha256(f"domain-finder-benchmark:{tld}:{attempt}".encode()).hexdigest()[:20]
    return f"dfb{digest}"


def discover_verified_matrix(root: Path) -> list[dict[str, str]]:
    sys.path.insert(0, str(root))
    from domain_finder.domain.models import DomainCheckStatus
    from domain_finder.infrastructure.whois.checker import DomainChecker

    checker = DomainChecker(whois_fallback=False, max_workers=12, rdap_per_host=4)
    rows: list[dict[str, str]] = []
    try:
        for tld, domain in REGISTERED.items():
            result = checker.check_domain(domain)
            status = getattr(result.status, "value", str(result.status))
            if status == DomainCheckStatus.REGISTERED.value:
                rows.append({"domain": domain, "tld": tld, "expected": "registered"})

        for tld in REGISTERED:
            for attempt in range(1, 6):
                domain = f"{deterministic_label(tld, attempt)}.{tld}"
                result = checker.check_domain(domain)
                status = getattr(result.status, "value", str(result.status))
                if status == DomainCheckStatus.AVAILABLE.value:
                    rows.append({"domain": domain, "tld": tld, "expected": "available"})
                    break
    finally:
        checker.close()
    return rows


PROBE_CODE = r"""
import json, sys, time
from pathlib import Path
root = Path(sys.argv[1])
matrix_file = Path(sys.argv[2])
workers = int(sys.argv[3])
sys.path.insert(0, str(root))
from domain_finder.infrastructure.whois.checker import DomainChecker
rows = json.loads(matrix_file.read_text())
domains = [row["domain"] for row in rows]
checker = DomainChecker(whois_fallback=False, max_workers=workers)
started = time.perf_counter()
try:
    results = checker.check_domains(domains)
finally:
    close = getattr(checker, "close", None)
    if callable(close): close()
elapsed = time.perf_counter() - started
out = []
for row in rows:
    result = results[row["domain"]]
    status = getattr(getattr(result, "status", None), "value", None)
    if status is None:
        status = "available" if result.available else ("unknown" if result.source == "unknown" else "registered")
    out.append({**row, "status": status, "source": result.source,
                "latency_ms": getattr(result, "latency_ms", None),
                "retries": getattr(result, "retries", 0),
                "detail": getattr(result, "detail", None)})
print(json.dumps({"elapsed": elapsed, "count": len(rows), "rows": out}))
"""


def probe(root: Path, matrix: list[dict[str, str]], workers: int) -> dict:
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
        json.dump(matrix, handle)
        matrix_path = Path(handle.name)
    try:
        completed = subprocess.run(
            [sys.executable, "-c", PROBE_CODE, str(root), str(matrix_path), str(workers)],
            check=True,
            capture_output=True,
            text=True,
            timeout=180,
        )
        return json.loads(completed.stdout.strip().splitlines()[-1])
    finally:
        matrix_path.unlink(missing_ok=True)


def summarize(name: str, workers: int, payload: dict) -> dict:
    rows = payload["rows"]
    correct = sum(row["status"] == row["expected"] for row in rows)
    elapsed = float(payload["elapsed"])
    return {
        "implementation": name,
        "workers": workers,
        "count": len(rows),
        "correct": correct,
        "accuracy": correct / len(rows) if rows else 0.0,
        "elapsed_s": elapsed,
        "domains_per_s": len(rows) / elapsed if elapsed else 0.0,
        "unknown": sum(row["status"] not in {"available", "registered"} for row in rows),
    }


def discover_baseline_root(modern_root: Path) -> Path | None:
    """Find the main checkout when running from a git worktree."""
    try:
        completed = subprocess.run(
            ["git", "-C", str(modern_root), "rev-parse", "--git-common-dir"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    common_dir = Path(completed.stdout.strip())
    if not common_dir.is_absolute():
        common_dir = (modern_root / common_dir).resolve()
    candidate = common_dir.parent.resolve()
    if candidate == modern_root.resolve() or not (candidate / "pyproject.toml").exists():
        return None
    return candidate


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--modern-root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--baseline-root",
        type=Path,
        default=None,
        help="Baseline checkout. If omitted, auto-detect the main checkout from a git worktree.",
    )
    parser.add_argument("--output-dir", type=Path, default=Path("benchmark-results"))
    parser.add_argument("--workers", default="1,5,10,20")
    args = parser.parse_args()

    matrix = discover_verified_matrix(args.modern_root.resolve())
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "matrix.json").write_text(json.dumps(matrix, indent=2), encoding="utf-8")
    print(f"verified matrix: {len(matrix)} domains across {len({r['tld'] for r in matrix})} TLDs")

    baseline_root = (
        args.baseline_root.resolve()
        if args.baseline_root
        else discover_baseline_root(args.modern_root.resolve())
    )
    implementations = [("modernized", args.modern_root.resolve())]
    if baseline_root is not None:
        implementations.insert(0, ("baseline", baseline_root))

    summaries: list[dict] = []
    details: list[dict] = []
    for workers in [int(value) for value in args.workers.split(",") if value.strip()]:
        for name, root in implementations:
            payload = probe(root, matrix, workers)
            summaries.append(summarize(name, workers, payload))
            details.extend(
                {"implementation": name, "workers": workers, **row} for row in payload["rows"]
            )
            print(summaries[-1])

    with (args.output_dir / "summary.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(summaries[0].keys()) if summaries else [])
        if summaries:
            writer.writeheader()
            writer.writerows(summaries)
    with (args.output_dir / "details.jsonl").open("w", encoding="utf-8") as handle:
        for row in details:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
