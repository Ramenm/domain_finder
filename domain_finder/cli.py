from __future__ import annotations

import os
import sys
import time
from typing import List, Optional

import typer
from dotenv import load_dotenv
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .providers import Chat01Provider, OpenRouterProvider, BaseProvider, LLMProviderError
from .utils import CacheManager, ResultWriter, extract_domains_from_text
from .checkers import check_domains_concurrent

app = typer.Typer(add_completion=False, help="⚡ Поиск свободных доменов с генерацией через LLM и RDAP/WHOIS проверкой.")
console = Console()


def _header() -> None:
    title = "[bold cyan]Domain Finder[/] — генератор и проверщик доменов"
    sub = (
        "[dim]Выбирайте провайдера (по умолчанию chat01:gpt-5-thinking), тематику, количество итераций и доменов за итерацию.\n"
        "Проверка доступности — RDAP по умолчанию (быстро и надёжно).[/dim]"
    )
    console.print(Panel.fit(sub, title=title, border_style="cyan", box=box.ROUNDED))


def _pick_provider(
    provider: str,
    model: Optional[str],
    temperature: float,
    timeout: float,
) -> BaseProvider:
    provider = provider.lower().strip()
    if provider == "chat01":
        return Chat01Provider(
            model=model or "gpt-5-thinking",
            temperature=temperature,
            timeout=timeout,
        )
    if provider == "openrouter":
        return OpenRouterProvider(
            model=model or "google/gemini-2.0-flash-lite-preview-02-05:free",
            temperature=temperature,
            timeout=timeout,
        )
    raise typer.BadParameter("provider должен быть 'chat01' или 'openrouter'")


@app.command("run")
def run(
    topic: str = typer.Option(
        ..., "--topic", "-t", help="Тематика доменов (напр.: 'сравнение нейросетей, бенчмарки, метрики')."
    ),
    iterations: int = typer.Option(5, "--iterations", "-i", min=1, help="Сколько проходов генерации/проверки выполнить."),
    per_request: int = typer.Option(100, "--per-request", "-n", min=1, max=300, help="Сколько доменов запросить у модели за одну итерацию."),
    tld: List[str] = typer.Option(["com"], "--tld", help="Список доменных зон. Указывайте без точки: com, io, ai."),
    language: str = typer.Option("ru", "--lang", help="Язык промпта (ru/en)."),
    provider: str = typer.Option("chat01", "--provider", "-p", help="Провайдер LLM: chat01 или openrouter."),
    model: Optional[str] = typer.Option(None, "--model", "-m", help="Имя модели. По умолчанию: chat01=gpt-5-thinking."),
    temperature: float = typer.Option(0.7, "--temperature", help="Температура генерации LLM."),
    timeout: float = typer.Option(60.0, "--timeout", help="Таймаут запроса к LLM (сек)."),
    use_rdap: Optional[bool] = typer.Option(
        None,
        "--rdap/--whois",
        help="Предпочитать RDAP (да) или WHOIS (нет). Если не указано — читается из .env USE_RDAP.",
    ),
    whois_fallback: bool = typer.Option(
        False, "--whois-fallback", help="Если RDAP не даст однозначного ответа — пробовать WHOIS."
    ),
    max_workers: int = typer.Option(20, "--workers", help="Кол-во потоков для проверки RDAP/WHOIS."),
    min_len: int = typer.Option(4, "--min-len", help="Мин. длина второй части домена."),
    max_len: int = typer.Option(15, "--max-lен", help="Макс. длина второй части домена."),
    cooldown: float = typer.Option(2.0, "--cooldown", help="Пауза (сек) между итерациями."),
    cache_file: str = typer.Option("domains_cache.json", "--cache-file", help="Файл кэша с результатами проверок."),
    clear_cache: bool = typer.Option(False, "--clear-cache", help="Очистить кэш перед запуском."),
    results_txt: str = typer.Option("results.txt", "--results", help="Файл для сохранения доступных доменов (.txt)."),
    results_csv: Optional[str] = typer.Option("results.csv", "--results-csv", help="Файл для сохранения CSV-отчёта."),
    skip_check: bool = typer.Option(False, "--skip-check", help="Не выполнять RDAP/WHOIS — просто сохранить сгенерированные домены."),
):
    """
    Основной сценарий: генерация доменов -> фильтрация/нормализация -> проверка доступности -> сохранение результата.
    """
    load_dotenv()
    _header()

    # Настройка предпочтения RDAP/WHOIS
    if use_rdap is None:
        env_flag = os.getenv("USE_RDAP", "true").lower().strip() in ("1", "true", "yes", "y")
        use_rdap = env_flag

    # Провайдер LLM
    try:
        llm: BaseProvider = _pick_provider(provider, model, temperature, timeout)
        console.print(f"[green]Провайдер:[/] {provider}  [green]Модель:[/] {llm.model}")
    except LLMProviderError as e:
        console.print(f"[red]Ошибка инициализации LLM:[/] {e}")
        raise typer.Exit(code=2)
    except Exception as e:  # noqa: BLE001
        console.print(f"[red]Неверные параметры провайдера:[/] {e}")
        raise typer.Exit(code=2)

    # Подготовка кэша/результатов
    cache = CacheManager(cache_file)
    if clear_cache:
        cache.clear()
        console.print("[yellow]Кэш очищен.[/yellow]")

    writer = ResultWriter(txt_path=results_txt, csv_path=results_csv)

    # Глобальные контейнеры
    all_suggested: List[str] = []
    all_available: List[str] = []

    for it in range(1, iterations + 1):
        console.rule(f"[bold]Итерация {it}/{iterations}[/bold]")
        # 1) Генерация доменов
        try:
            raw_text = llm.generate_domains(
                topic=topic,
                tlds=[t.lstrip(".").lower() for t in tld],
                count=per_request,
                language=language,
                min_len=min_len,
                max_len=max_len,
            )
        except LLMProviderError as e:
            console.print(f"[red]Не удалось получить предложения от LLM:[/] {e}")
            # Переходим к следующей итерации
            time.sleep(cooldown)
            continue

        # 2) Парсинг/нормализация
        suggestions = extract_domains_from_text(
            raw_text,
            allowed_tlds=[t.lstrip(".").lower() for t in tld],
            limit=per_request,
            min_len=min_len,
            max_len=max_len,
            force_tld=(tld[0] if len(tld) == 1 else None),
        )

        # Уберём те, что уже есть в кэше или уже предлагались ранее
        suggestions_uni = []
        seen = set(all_suggested) | set(cache.known().keys())
        for d in suggestions:
            if d not in seen:
                suggestions_uni.append(d)

        if not suggestions_uni:
            console.print("[yellow]Нет новых доменов в этой итерации (все уже были).[/yellow]")
            time.sleep(cooldown)
            continue

        console.print(f"[cyan]Сгенерировано новых доменов:[/] {len(suggestions_uni)}")

        # 3) Проверка доступности
        if skip_check:
            # Просто сохраняем список без проверки
            writer.append_available((d, "skipped", time.time()) for d in suggestions_uni)
            all_available.extend(suggestions_uni)
            all_suggested.extend(suggestions_uni)
            console.print(f"[green]Сохранено без проверки:[/] {len(suggestions_uni)} доменов")
            time.sleep(cooldown)
            continue

        results = check_domains_concurrent(
            suggestions_uni,
            prefer_rdap=use_rdap,
            max_workers=max_workers,
            rdap_timeout=10.0,
            whois_fallback=whois_fallback,
        )

        # 4) Обновление кэша и сохранение доступных
        newly_available: List[str] = []
        to_write = []
        for dom, res in results.items():
            cache.set(dom, res.available, res.source)
            if res.available:
                newly_available.append(dom)
                to_write.append((dom, res.source, res.checked_at))

        cache.save()
        if newly_available:
            writer.append_available(to_write)
            all_available.extend(newly_available)
            console.print(f"[bold green]Найдено доступных:[/] {len(newly_available)}")
        else:
            console.print("[yellow]Доступных доменов не обнаружено в этой итерации.[/yellow]")

        all_suggested.extend(suggestions_uni)
        time.sleep(cooldown)

    # Финальный отчёт
    console.rule("[bold]Итоги[/bold]")
    table = Table(title="Статистика сессии", box=box.SIMPLE)
    table.add_column("Параметр")
    table.add_column("Значение")
    table.add_row("Итераций", str(iterations))
    table.add_row("Сгенерировано (уник.)", str(len(set(all_suggested))))
    table.add_row("Доступно найдено", str(len(set(all_available))))
    table.add_row("Файл .txt", results_txt)
    table.add_row("Файл .csv", results_csv or "—")
    console.print(table)

    if all_available:
        from .utils import ResultWriter as _RW  # re-use helper to pretty table
        _RW.show_table(sorted(set(all_available)))

    console.print("[dim]Готово.[/dim]")


@app.command("wizard")
def wizard() -> None:
    """
    Интерактивный режим: задаёт вопросы в терминале и запускает поиск.
    """
    load_dotenv()
    _header()

    topic = typer.prompt("Опишите тематику (напр.: 'нейросети, бенчмарки, сравнение моделей')", default="нейросети, бенчмарки, сравнение моделей")
    iterations = typer.prompt("Сколько итераций выполнить?", default=5)
    per_request = typer.prompt("Сколько доменов запрашивать за раз?", default=100)
    tld = typer.prompt("Доменные зоны (через запятую, без точки)", default="com")
    provider = typer.prompt("Провайдер (chat01 / openrouter)", default="chat01")
    model = typer.prompt("Модель (Enter — по умолчанию)", default="")
    language = typer.prompt("Язык промпта (ru/en)", default="ru")
    use_rdap_str = typer.prompt("Проверка через RDAP? (y/n)", default="y")
    whois_fallback = typer.prompt("Использовать fallback через WHOIS, если RDAP неуверен? (y/n)", default="n")
    max_workers = typer.prompt("Потоков для проверки", default=20)
    min_len = typer.prompt("Мин. длина имени", default=4)
    max_len = typer.prompt("Макс. длина имени", default=15)
    cooldown = typer.prompt("Пауза между итерациями (сек)", default=2.0)
    results_txt = typer.prompt("Файл результатов (.txt)", default="results.txt")
    results_csv = typer.prompt("Файл результатов (.csv, Enter — пропустить)", default="results.csv")

    # Преобразование типов
    try:
        iterations = int(iterations)
        per_request = int(per_request)
        max_workers = int(max_workers)
        min_len = int(min_len)
        max_len = int(max_len)
        cooldown = float(cooldown)
    except Exception:
        console.print("[red]Некорректные числовые значения.[/red]")
        raise typer.Exit(code=2)

    use_rdap = use_rdap_str.strip().lower() in ("y", "yes", "true", "1")
    whois_fallback_b = whois_fallback.strip().lower() in ("y", "yes", "true", "1")
    tld_list = [x.strip().lstrip(".").lower() for x in tld.split(",") if x.strip()]

    # Запуск основной команды
    run(
        topic=topic,
        iterations=iterations,
        per_request=per_request,
        tld=tld_list,
        language=language,
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
