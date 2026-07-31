"""Shared AiStackClient singleton for the images module."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agentic_tour_planner.tools.ai_stack_client import AiStackClient

_ai_stack: AiStackClient | None = None


def get_ai_stack() -> AiStackClient:
    """Get or create the shared AiStackClient singleton."""
    global _ai_stack
    if _ai_stack is None:
        from agentic_tour_planner.tools.ai_stack_client import AiStackClient
        _ai_stack = AiStackClient()
    return _ai_stack
