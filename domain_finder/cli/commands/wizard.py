"""Wizard command for interactive domain search."""

import typer
from pydantic import ValidationError
from rich.console import Console

from domain_finder.application.dto import DomainSearchRequest
from domain_finder.cli.commands.run import (
    _execute_request,
    _header,
    _load_settings,
    _validation_message,
)

console = Console()


def wizard() -> None:
    """Interactive mode: prompt for a validated domain search request."""
    _header()

    topic = typer.prompt(
        "📝 Describe the domain topic/theme",
        default="neural networks, benchmarks, model comparison",
    )
    iterations = typer.prompt("🔄 Number of iterations", default=5)
    per_request = typer.prompt(
        "📊 Number of domains to request per iteration",
        default=100,
    )
    llm_workers = typer.prompt("Number of parallel LLM requests per iteration", default=1)
    tld = typer.prompt(
        "🌐 Top-level domains (comma-separated, without dot, e.g.: com, io, ai)", default="com"
    )
    provider = typer.prompt("LLM provider", default="openai")
    model = typer.prompt("🎯 Model (press Enter for default value)", default="")
    use_rdap_str = typer.prompt("Use RDAP for checking? (y/n)", default="y")
    whois_fallback = typer.prompt(
        "🔄 Use WHOIS as fallback method if RDAP is uncertain? (y/n)", default="y"
    )
    max_workers = typer.prompt("👷 Number of threads for domain checking", default=20)
    min_len = typer.prompt("📏 Minimum domain name length (without TLD)", default=4)
    max_len = typer.prompt("📏 Maximum domain name length (without TLD)", default=15)
    cooldown = typer.prompt("⏱️  Pause between iterations (seconds)", default=2.0)
    results_txt = typer.prompt("💾 File for saving results (.txt)", default="results.txt")
    results_csv = typer.prompt(
        "📄 File for saving CSV report (Enter to skip)", default="results.csv"
    )

    use_rdap = use_rdap_str.strip().lower() in ("y", "yes", "true", "1")
    whois_fallback_b = whois_fallback.strip().lower() in ("y", "yes", "true", "1")
    tld_list = [x.strip() for x in tld.split(",") if x.strip()]

    try:
        request = DomainSearchRequest(
            topic=topic,
            iterations=iterations,
            per_request=per_request,
            llm_workers=llm_workers,
            tlds=tld_list,
            provider=provider,
            model=(model or None),
            temperature=0.7,
            timeout=60.0,
            use_rdap=use_rdap,
            whois_fallback=whois_fallback_b,
            max_workers=max_workers,
            min_len=min_len,
            max_len=max_len,
            cooldown=cooldown,
            cache_file="domains_cache.sqlite3",
            clear_cache=False,
            results_txt=results_txt,
            results_csv=(results_csv if results_csv else None),
            skip_check=False,
        )
    except ValidationError as e:
        console.print(f"[red]✗ Invalid input:[/] {_validation_message(e)}")
        raise typer.Exit(code=2) from e

    _execute_request(request, _load_settings())
