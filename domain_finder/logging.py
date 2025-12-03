"""Logging configuration with rich integration."""

from __future__ import annotations

import logging
import sys

from rich.console import Console
from rich.logging import RichHandler


def setup_logging(
    level: str | int = logging.INFO,
    console: Console | None = None,
    enable_rich: bool = True,
) -> logging.Logger:
    """
    Set up structured logging with rich integration.

    Args:
        level: Logging level (string or int)
        console: Optional Rich Console instance
        enable_rich: Whether to use RichHandler for beautiful output

    Returns:
        Configured root logger
    """
    if isinstance(level, str):
        level = getattr(logging, level.upper(), logging.INFO)

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Remove existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    if enable_rich:
        # Use RichHandler for beautiful console output
        rich_console = console or Console(stderr=True)
        handler = RichHandler(
            console=rich_console,
            show_time=True,
            show_path=True,
            markup=True,
            rich_tracebacks=True,
        )
    else:
        # Fallback to standard StreamHandler
        handler = logging.StreamHandler(sys.stderr)

    handler.setLevel(level)
    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(formatter)
    root_logger.addHandler(handler)

    return root_logger


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance for the given name."""
    return logging.getLogger(name)
