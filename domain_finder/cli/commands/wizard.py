"""Wizard command for interactive domain search."""

import typer
from rich.console import Console

from domain_finder.cli.commands.run import _header, run

console = Console()


def wizard() -> None:
    """
    Interactive mode: prompts questions in terminal and runs domain search.
    """
    _header()

    topic = typer.prompt(
        "📝 Describe the domain topic/theme",
        default="neural networks, benchmarks, model comparison",
    )
    iterations = typer.prompt("🔄 Number of iterations", default=5)
    per_request = typer.prompt("📊 Number of domains to request per iteration", default=100)
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

    # Type conversion
    try:
        iterations = int(iterations)
        per_request = int(per_request)
        llm_workers = int(llm_workers)
        max_workers = int(max_workers)
        min_len = int(min_len)
        max_len = int(max_len)
        cooldown = float(cooldown)
    except (ValueError, TypeError) as e:
        console.print("[red]✗ Error: invalid numeric values. Please check your input.[/red]")
        raise typer.Exit(code=2) from e

    use_rdap = use_rdap_str.strip().lower() in ("y", "yes", "true", "1")
    whois_fallback_b = whois_fallback.strip().lower() in ("y", "yes", "true", "1")
    tld_list = [x.strip().lstrip(".").lower() for x in tld.split(",") if x.strip()]

    # Run main command
    run(
        topic=topic,
        iterations=iterations,
        per_request=per_request,
        llm_workers=llm_workers,
        tld=tld_list,
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
        cache_file="domains_cache.json",
        clear_cache=False,
        results_txt=results_txt,
        results_csv=(results_csv if results_csv else None),
        skip_check=False,
    )
