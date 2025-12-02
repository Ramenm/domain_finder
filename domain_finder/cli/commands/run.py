"""Run command for domain search."""

from __future__ import annotations

from typing import List, Optional

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
from domain_finder.infrastructure.persistence import ResultWriter
from domain_finder.infrastructure.whois.checker import DomainChecker
from domain_finder.infrastructure.llm.openai import OpenAIProvider

console = Console()


def _header() -> None:
    """Display application header."""
    title = "[bold cyan]Domain Finder[/] — генератор и проверщик доменных имён"
    sub = (
        "[dim]Выберите провайдера LLM (по умолчанию: OpenAI), укажите тематику, количество итераций и доменов за итерацию.\n"
        "Проверка доступности выполняется через RDAP (быстро и надёжно).[/dim]"
    )
    console.print(Panel.fit(sub, title=title, border_style="cyan", box=box.ROUNDED))


def _create_provider(
    provider_name: str,
    model: Optional[str],
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


def run(
    topic: str = typer.Option(
        ..., "--topic", "-t", help="Тематика доменов (например: 'сравнение нейросетей, бенчмарки, метрики')."
    ),
    iterations: int = typer.Option(5, "--iterations", "-i", min=1, help="Количество проходов генерации и проверки."),
    per_request: int = typer.Option(100, "--per-request", "-n", min=1, max=300, help="Количество доменов для запроса у модели за одну итерацию."),
    llm_workers: int = typer.Option(1, "--llm-workers", min=1, help="Количество параллельных запросов к LLM на итерацию (результаты объединяются и парсятся один раз)."),
    tld: List[str] = typer.Option(["com"], "--tld", help="Список доменных зон. Указывайте без точки: com, io, ai."),
    language: str = typer.Option("ru", "--lang", help="Язык промпта для LLM (ru/en)."),
    provider: str = typer.Option("openai", "--provider", "-p", help="Провайдер LLM (openai)."),
    model: Optional[str] = typer.Option(None, "--model", "-m", help="Имя модели. По умолчанию берётся из переменной OPENAI_MODEL в .env."),
    temperature: float = typer.Option(0.7, "--temperature", help="Температура генерации для LLM (0.0-2.0)."),
    timeout: float = typer.Option(60.0, "--timeout", help="Таймаут запроса к LLM в секундах."),
    use_rdap: Optional[bool] = typer.Option(
        None,
        "--rdap/--whois",
        help="Предпочитать RDAP (--rdap) или WHOIS (--whois). Если не указано, значение берётся из переменной USE_RDAP в .env.",
    ),
    whois_fallback: bool = typer.Option(
        False, "--whois-fallback", help="Использовать WHOIS как резервный метод, если RDAP не дал однозначного ответа."
    ),
    max_workers: int = typer.Option(20, "--workers", help="Количество потоков для параллельной проверки доменов через RDAP/WHOIS."),
    min_len: int = typer.Option(4, "--min-len", help="Минимальная длина второй части домена (без TLD)."),
    max_len: int = typer.Option(15, "--max-len", help="Максимальная длина второй части домена (без TLD)."),
    cooldown: float = typer.Option(2.0, "--cooldown", help="Пауза в секундах между итерациями."),
    cache_file: str = typer.Option("domains_cache.json", "--cache-file", help="Путь к файлу кэша с результатами проверок доменов."),
    clear_cache: bool = typer.Option(False, "--clear-cache", help="Очистить кэш перед запуском."),
    results_txt: str = typer.Option("results.txt", "--results", help="Путь к файлу для сохранения доступных доменов (.txt)."),
    results_csv: Optional[str] = typer.Option("results.csv", "--results-csv", help="Путь к файлу для сохранения CSV-отчёта с результатами."),
    skip_check: bool = typer.Option(False, "--skip-check", help="Пропустить проверку доступности (RDAP/WHOIS) и сохранить только сгенерированные домены."),
) -> None:
    """
    Основной сценарий: генерация доменов -> фильтрация/нормализация -> проверка доступности -> сохранение результата.
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
        console.print(f"[green]✓ Провайдер:[/] {provider_display}  [green]Модель:[/] {llm_provider.config.model}")
    except ProviderError as e:
        console.print(f"[red]✗ Ошибка инициализации LLM-провайдера:[/] {e}")
        raise typer.Exit(code=2)
    except Exception as e:  # noqa: BLE001
        console.print(f"[red]✗ Неверные параметры провайдера:[/] {e}")
        raise typer.Exit(code=2)

    # Create infrastructure components
    cache = CacheManager(cache_file)
    if clear_cache:
        cache.clear()
        console.print("[yellow]⚠ Кэш очищен.[/yellow]")

    writer = ResultWriter(txt_path=results_txt, csv_path=results_csv)
    checker = DomainChecker(
        prefer_rdap=use_rdap,
        whois_fallback=whois_fallback,
        max_workers=max_workers,
        max_connections=settings.max_connections,
        max_keepalive_connections=settings.max_keepalive_connections,
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
        language=language,
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
        console.print(f"[red]✗ Ошибка выполнения:[/] {e}")
        raise typer.Exit(code=1)

    # Display results
    console.rule("[bold]Результаты поиска[/bold]")
    table = Table(title="Статистика сессии", box=box.SIMPLE)
    table.add_column("Параметр", style="cyan")
    table.add_column("Значение", style="green")
    table.add_row("Итераций выполнено", str(result.total_iterations))
    table.add_row("Доменов сгенерировано (уникальных)", str(result.total_generated))
    table.add_row("Доступных доменов найдено", str(result.total_available))
    table.add_row("Файл результатов (.txt)", result.results_txt)
    table.add_row("Файл результатов (.csv)", result.results_csv or "—")
    console.print(table)

    if result.available_domains:
        ResultWriter.show_table(result.available_domains)

    console.print("[green]✓ Поиск завершён успешно.[/green]")

