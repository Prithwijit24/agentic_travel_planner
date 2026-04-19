import pytest
from pydantic import ValidationError

from agentic_tour_planner.domain.models import PlanningRequest


def test_planning_request_requires_destination():
    with pytest.raises(ValidationError):
        PlanningRequest(destination="", trip_length_days=3)

