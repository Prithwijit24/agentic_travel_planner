"""Infer LOCATED_IN hierarchy edges between pages.

Heuristic: Wikivoyage articles tag themselves with categories like
[[Category:East Sikkim]]. If a category name exactly matches another
page's title, we treat that page as the parent region.

Input:  pages.jsonl   (from parse_dump.py)
Output: hierarchy_edges.jsonl   -> [{child_poi_id, parent_poi_id}]
        orphans.jsonl           -> pages with no inferred parent, for manual review

Run:
    python -m agentic_tour_planner.graphdb.infer_hierarchy [input-dir] [output-dir]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def slugify(text: str) -> str:
    import re
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")


def main(input_dir: str | None = None, output_dir: str | None = None) -> tuple[int, int]:
    input_path = Path(input_dir) if input_dir else Path(".")
    output_path = Path(output_dir) if output_dir else Path(".")
    output_path.mkdir(parents=True, exist_ok=True)

    pages_file = input_path / "pages.jsonl"
    pages = [json.loads(line) for line in open(pages_file, encoding="utf-8") if line.strip()]

    title_to_id = {p["page_title"].strip().lower(): p["poi_id"] for p in pages}

    edges = []
    orphans = []

    for page in pages:
        parent_id = None
        for cat in page["categories"]:
            cat_norm = cat.strip().lower()
            if cat_norm in title_to_id and title_to_id[cat_norm] != page["poi_id"]:
                parent_id = title_to_id[cat_norm]
                break

        if parent_id:
            edges.append({"child_poi_id": page["poi_id"], "parent_poi_id": parent_id})
        else:
            orphans.append(page["page_title"])

    with open(output_path / "hierarchy_edges.jsonl", "w", encoding="utf-8") as f:
        for e in edges:
            f.write(json.dumps(e) + "\n")

    with open(output_path / "orphans.jsonl", "w", encoding="utf-8") as f:
        for title in orphans:
            f.write(json.dumps({"page_title": title}) + "\n")

    print(f"Hierarchy edges inferred: {len(edges)}")
    print(f"Orphan pages (no parent found): {len(orphans)}")
    return len(edges), len(orphans)


if __name__ == "__main__":
    if not Path("pages.jsonl").exists() and len(sys.argv) < 2:
        print("Usage: python -m agentic_tour_planner.graphdb.infer_hierarchy [input-dir] [output-dir]")
        sys.exit(1)
    main(sys.argv[1] if len(sys.argv) > 1 else None, sys.argv[2] if len(sys.argv) > 2 else None)
