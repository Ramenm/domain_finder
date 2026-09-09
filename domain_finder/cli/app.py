"""Typer application factory."""

import typer

from domain_finder.cli.commands import run, wizard

app = typer.Typer(
    add_completion=False,
    help="Domain name generator and registry-state checker using RDAP and WHOIS.",
)

# Register commands
app.command("run")(run.run)
app.command("wizard")(wizard.wizard)
