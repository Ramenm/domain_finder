"""Typer application factory."""

import typer

from domain_finder.cli.commands import run, wizard

app = typer.Typer(
    add_completion=False,
    help="⚡ Domain Finder — генератор и проверщик доменов с LLM и RDAP/WHOIS проверкой.",
)

# Register commands
app.command("run")(run.run)
app.command("wizard")(wizard.wizard)

