from __future__ import annotations

import sys

from loguru import logger

from agentic_tour_planner.config.settings import get_settings

_initialized = False


def configure_logging(level: str | None = None) -> None:
    """Configure the single global loguru sink. Idempotent unless an explicit
    ``level`` is provided, in which case the sink is re-created at that level so
    callers like the CLI ``--log-level`` flag can override ``settings.log_level``."""
    global _initialized
    if _initialized and level is None:
        return

    resolved = (level or get_settings().log_level).upper()
    logger.remove()
    logger.add(
        sys.stdout,
        level=resolved,
        colorize=True,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> ||| "
            "<level>{level}</level> ||| "
            "<cyan>{name:<30}</cyan> ||| "
            "<level>{message}</level>"
        ),
    )
    _initialized = True


def get_logger(name: str):
    """Return a loguru logger bound with the module ``name`` for easy debugging."""
    configure_logging()
    return logger.bind(name=name)
