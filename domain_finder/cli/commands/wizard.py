"""Wizard command for interactive domain search."""

import typer
from rich.console import Console

from domain_finder.cli.commands.run import _header, run

console = Console()


def wizard() -> None:
    """
    Интерактивный режим: задаёт вопросы в терминале и запускает поиск доменов.
    """
    _header()

    topic = typer.prompt("📝 Опишите тематику доменов", default="нейросети, бенчмарки, сравнение моделей")
    iterations = typer.prompt("🔄 Количество итераций", default=5)
    per_request = typer.prompt("📊 Количество доменов для запроса за одну итерацию", default=100)
    llm_workers = typer.prompt("⚡ Количество параллельных запросов к LLM на итерацию", default=1)
    tld = typer.prompt("🌐 Доменные зоны (через запятую, без точки, например: com, io, ai)", default="com")
    provider = typer.prompt("🤖 Провайдер LLM", default="openai")
    model = typer.prompt("🎯 Модель (нажмите Enter для значения по умолчанию)", default="")
    language = typer.prompt("🌍 Язык промпта (ru/en)", default="ru")
    use_rdap_str = typer.prompt("🔍 Использовать RDAP для проверки? (y/n)", default="y")
    whois_fallback = typer.prompt("🔄 Использовать WHOIS как резервный метод, если RDAP неуверен? (y/n)", default="n")
    max_workers = typer.prompt("👷 Количество потоков для проверки доменов", default=20)
    min_len = typer.prompt("📏 Минимальная длина имени домена (без TLD)", default=4)
    max_len = typer.prompt("📏 Максимальная длина имени домена (без TLD)", default=15)
    cooldown = typer.prompt("⏱️  Пауза между итерациями (секунды)", default=2.0)
    results_txt = typer.prompt("💾 Файл для сохранения результатов (.txt)", default="results.txt")
    results_csv = typer.prompt("📄 Файл для сохранения CSV-отчёта (Enter — пропустить)", default="results.csv")

    # Преобразование типов
    try:
        iterations = int(iterations)
        per_request = int(per_request)
        llm_workers = int(llm_workers)
        max_workers = int(max_workers)
        min_len = int(min_len)
        max_len = int(max_len)
        cooldown = float(cooldown)
    except (ValueError, TypeError) as e:
        console.print(f"[red]✗ Ошибка: некорректные числовые значения. Проверьте введённые данные.[/red]")
        raise typer.Exit(code=2)

    use_rdap = use_rdap_str.strip().lower() in ("y", "yes", "true", "1")
    whois_fallback_b = whois_fallback.strip().lower() in ("y", "yes", "true", "1")
    tld_list = [x.strip().lstrip(".").lower() for x in tld.split(",") if x.strip()]

    # Запуск основной команды
    run(
        topic=topic,
        iterations=iterations,
        per_request=per_request,
        llm_workers=llm_workers,
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

