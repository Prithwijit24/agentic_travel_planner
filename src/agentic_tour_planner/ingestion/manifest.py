from __future__ import annotations

import json
from pathlib import Path

from agentic_tour_planner.domain.models import SourceManifest


def load_manifest(path: str | Path) -> SourceManifest:
    manifest_path = Path(path)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if "name" in payload and "description" not in payload:
        payload["description"] = payload["name"]
    if "seeds" in payload:
        normalized_seeds = []
        for seed in payload["seeds"]:
            normalized_seed = dict(seed)
            if "kind" in normalized_seed and "source_type" not in normalized_seed:
                normalized_seed["source_type"] = normalized_seed.pop("kind")
            if "identifier" in normalized_seed:
                identifier = normalized_seed.pop("identifier")
                normalized_seed.setdefault("destination", str(identifier))
                normalized_seed.setdefault("title", str(identifier))
                if normalized_seed.get("source_type") == "wikivoyage":
                    normalized_seed.setdefault(
                        "url",
                        f"https://en.wikivoyage.org/wiki/{str(identifier).replace(' ', '_')}",
                    )
            normalized_seeds.append(normalized_seed)
        payload["seeds"] = normalized_seeds
    return SourceManifest.model_validate(payload)
