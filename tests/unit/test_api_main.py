"""Unit tests for job-level error reporting in the FastAPI app."""

from agentic_tour_planner.api.main import PLAN_TIMEOUT_SECONDS, _job_error_message


def test_plan_timeout_is_generous() -> None:
    """The pipeline cap must comfortably exceed a slow multi-day LLM run."""
    assert PLAN_TIMEOUT_SECONDS >= 1800


def test_job_error_message_timeout_is_readable() -> None:
    """asyncio.TimeoutError has an empty str(); the message must be meaningful."""
    msg = _job_error_message(TimeoutError())
    assert "timed out" in msg
    assert str(PLAN_TIMEOUT_SECONDS) in msg


def test_job_error_message_passthrough() -> None:
    assert _job_error_message(RuntimeError("boom")) == "boom"


def test_job_error_message_empty_string_falls_back_to_repr() -> None:
    msg = _job_error_message(ValueError(""))
    assert "ValueError" in msg
