"""Typer application factory."""

import typer

from domain_finder.cli.commands import run, wizard

app = typer.Typer(
    add_completion=False,
    help="⚡ Domain Finder — генератор и проверщик доменных имён с использованием LLM и проверкой доступности через RDAP/WHOIS.",
)

# Register commands
app.command("run")(run.run)
app.command("wizard")(wizard.wizard)

