import json

from agentic_tour_planner.ingestion.manifest import load_manifest


def test_load_manifest_reads_seed_defaults(tmp_path):
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "name": "sample",
                "defaults": {
                    "crawl_backend": "trafilatura",
                    "refresh_days": 14,
                    "max_concurrency": 2,
                },
                "seeds": [
                    {
                        "kind": "wikivoyage",
                        "identifier": "Kyoto",
                        "destination": "Kyoto",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    manifest = load_manifest(manifest_path)

    assert manifest.description == "sample"
    assert manifest.defaults.refresh_days == 14
    assert manifest.seeds[0].title == "Kyoto"

