"""Run command for domain search."""

from __future__ import annotations

import typer
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from domain_finder.application.dto import DomainSearchRequest
from domain_finder.application.use_cases import RunDomainSearchUseCase
from domain_finder.domain.errors import ProviderError
from domain_finder.domain.models import ProviderConfig
from domain_finder.infrastructure.cache import CacheManager
from domain_finder.infrastructure.config import Settings
from domain_finder.infrastructure.llm.openai import OpenAIProvider
from domain_finder.infrastructure.persistence import ResultWriter
from domain_finder.infrastructure.whois.checker import DomainChecker

console = Console()


def _header() -> None:
    """Display application header."""
    title = "[bold cyan]Domain Finder[/] — domain name generator and checker"
    sub = (
        "[dim]Select an LLM provider (default: OpenAI), specify the topic, number of iterations, and domains per iteration.\n"
        "Registry state is checked via RDAP/WHOIS; registrability is reported separately.[/dim]"
    )
    console.print(Panel.fit(sub, title=title, border_style="cyan", box=box.ROUNDED))


def _create_provider(
    provider_name: str,
    model: str | None,
    temperature: float,
    timeout: float,
    settings: Settings,
) -> OpenAIProvider:
    """
    Create LLM provider instance.

    Args:
        provider_name: Provider name ('openai')
        model: Optional model name (uses default if not provided)
        temperature: Generation temperature
        timeout: Request timeout
        settings: Application settings

    Returns:
        Provider instance

    Raises:
        typer.BadParameter: If provider is invalid
        ProviderError: If provider initialization fails
    """
    provider_name = provider_name.lower().strip()

    if provider_name == "openai":
        model_name = model or settings.get_default_model("openai")
        config = ProviderConfig(
            provider="openai",
            model=model_name,
            temperature=temperature,
            timeout=timeout,
        )
        return OpenAIProvider(
            config=config,
            settings=settings,
            max_concurrent_requests=settings.max_concurrent_llm_requests,
        )
    else:
        raise typer.BadParameter("provider must be 'openai'")


def _create_checker(
    settings: Settings,
    use_rdap: bool,
    whois_fallback: bool,
    max_workers: int,
    dns_prefilter: bool = False,
) -> DomainChecker:
    """Create a checker with all relevant environment settings wired through."""
    return DomainChecker(
        prefer_rdap=use_rdap,
        whois_fallback=whois_fallback,
        max_workers=max_workers,
        rdap_timeout=settings.rdap_timeout,
        max_connections=settings.max_connections,
        max_keepalive_connections=settings.max_keepalive_connections,
        max_retries=settings.max_retries,
        dns_prefilter=dns_prefilter,
        registry_profile_file=settings.registry_profile_file,
        reserved_names_cache_file=settings.reserved_names_cache_file,
    )


def run(
    topic: str = typer.Option(
        ...,
        "--topic",
        "-t",
        help="Domain topic/theme (e.g., 'neural network comparison, benchmarks, metrics').",
    ),
    iterations: int = typer.Option(
        5, "--iterations", "-i", min=1, help="Number of generation and checking passes."
    ),
    per_request: int = typer.Option(
        100,
        "--per-request",
        "-n",
        min=1,
        max=300,
        help="Number of domains to request from the model per iteration.",
    ),
    llm_workers: int = typer.Option(
        1,
        "--llm-workers",
        min=1,
        help="Number of parallel LLM requests per iteration (results are merged and parsed once).",
    ),
    tld: list[str] = typer.Option(
        ["com"], "--tld", help="List of top-level domains. Specify without dot: com, io, ai."
    ),
    provider: str = typer.Option("openai", "--provider", "-p", help="LLM provider (openai)."),
    model: str | None = typer.Option(
        None,
        "--model",
        "-m",
        help="Model name. Defaults to OPENAI_MODEL environment variable from .env.",
    ),
    temperature: float = typer.Option(
        0.7, "--temperature", help="Generation temperature for LLM (0.0-2.0)."
    ),
    timeout: float = typer.Option(60.0, "--timeout", help="LLM request timeout in seconds."),
    use_rdap: bool | None = typer.Option(
        None,
        "--rdap/--whois",
        help="Prefer RDAP (--rdap) or WHOIS (--whois). If not specified, value is taken from USE_RDAP environment variable in .env.",
    ),
    whois_fallback: bool = typer.Option(
        True,
        "--whois-fallback",
        help="Use WHOIS as a fallback method if RDAP did not provide a definitive answer.",
    ),
    max_workers: int = typer.Option(
        20, "--workers", help="Number of threads for parallel domain checking via RDAP/WHOIS."
    ),
    min_len: int = typer.Option(
        4, "--min-len", help="Minimum length of the second-level domain label (without TLD)."
    ),
    max_len: int = typer.Option(
        15, "--max-len", help="Maximum length of the second-level domain label (without TLD)."
    ),
    cooldown: float = typer.Option(
        0.0, "--cooldown", min=0.0, help="Optional pause in seconds between iterations."
    ),
    cache_file: str = typer.Option(
        "domains_cache.sqlite3",
        "--cache-file",
        help="Path to cache file with domain check results.",
    ),
    clear_cache: bool = typer.Option(False, "--clear-cache", help="Clear cache before starting."),
    results_txt: str = typer.Option(
        "results.txt",
        "--results",
        help="Path to file for saving confirmed registrable domains (.txt).",
    ),
    results_csv: str | None = typer.Option(
        "results.csv", "--results-csv", help="Path to file for saving CSV report with results."
    ),
    skip_check: bool = typer.Option(
        False,
        "--skip-check",
        help="Skip registry-state checking and save only generated domains.",
    ),
) -> None:
    """
    Main workflow: domain generation -> filtering/normalization -> registry-state check -> result saving.
    """
    _header()

    # Load settings
    settings = Settings()
    if use_rdap is None:
        use_rdap = settings.use_rdap

    # Create provider
    try:
        llm_provider = _create_provider(provider, model, temperature, timeout, settings)
        provider_display = getattr(llm_provider, "display_name", provider)
        console.print(
            f"[green]✓ Provider:[/] {provider_display}  [green]Model:[/] {llm_provider.config.model}"
        )
    except ProviderError as e:
        console.print(f"[red]✗ LLM provider initialization error:[/] {e}")
        raise typer.Exit(code=2) from e
    except Exception as e:  # noqa: BLE001
        console.print(f"[red]✗ Invalid provider parameters:[/] {e}")
        raise typer.Exit(code=2) from e

    # Create infrastructure components
    cache = CacheManager(cache_file)
    if clear_cache:
        cache.clear()
        console.print("[yellow]⚠ Cache cleared.[/yellow]")

    writer = ResultWriter(txt_path=results_txt, csv_path=results_csv)
    checker = _create_checker(
        settings=settings,
        use_rdap=use_rdap,
        whois_fallback=whois_fallback,
        max_workers=max_workers,
    )

    # Create use case
    use_case = RunDomainSearchUseCase(
        provider=llm_provider,
        checker=checker,
        repository=cache,
        writer=writer,
    )

    # Create request
    request = DomainSearchRequest(
        topic=topic,
        iterations=iterations,
        per_request=per_request,
        llm_workers=llm_workers,
        tlds=tld,
        provider=provider,
        model=model,
        temperature=temperature,
        timeout=timeout,
        use_rdap=use_rdap,
        whois_fallback=whois_fallback,
        max_workers=max_workers,
        min_len=min_len,
        max_len=max_len,
        cooldown=cooldown,
        cache_file=cache_file,
        clear_cache=clear_cache,
        results_txt=results_txt,
        results_csv=results_csv,
        skip_check=skip_check,
    )

    # Execute use case
    try:
        result = use_case.execute(request)
    except Exception as e:  # noqa: BLE001
        console.print(f"[red]✗ Execution error:[/] {e}")
        raise typer.Exit(code=1) from e

    # Display results
    console.rule("[bold]Search Results[/bold]")
    table = Table(title="Session Statistics", box=box.SIMPLE)
    table.add_column("Parameter", style="cyan")
    table.add_column("Value", style="green")
    table.add_row("Iterations completed", str(result.total_iterations))
    table.add_row("Domains generated (unique)", str(result.total_generated))
    table.add_row("Confirmed registrable domains", str(result.total_available))
    table.add_row("Unregistered (not purchase-confirmed)", str(result.total_unregistered))
    table.add_row("Results file (.txt)", result.results_txt)
    table.add_row("Results file (.csv)", result.results_csv or "—")
    console.print(table)

    if result.available_domains:
        ResultWriter.show_table(result.available_domains)
    if result.unregistered_domains:
        ResultWriter.show_table(
            result.unregistered_domains,
            title="Unregistered Domains (registrability not confirmed)",
        )

    console.print("[green]✓ Search completed successfully.[/green]")
