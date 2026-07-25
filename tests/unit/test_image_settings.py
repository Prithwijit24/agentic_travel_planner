"""Unit tests for image pipeline settings."""
from __future__ import annotations

import pytest
from agentic_tour_planner.config.settings import get_settings, clear_config


def test_image_settings_defaults():
    """Image pipeline settings should have sensible defaults."""
    clear_config()
    s = get_settings()
    assert s.image_clip_threshold == 0.22
    assert s.image_min_resolution == 800
    assert s.image_max_aspect_ratio == 2.5
    assert s.image_cache_ttl_seconds == 2592000
    assert s.image_dedup_threshold == 5
    assert s.image_nsfw_threshold == 0.5
    assert s.image_smart_crop_enabled is True
    assert s.image_mapillary_token is None
    assert s.image_openverse_enabled is True
    clear_config()
