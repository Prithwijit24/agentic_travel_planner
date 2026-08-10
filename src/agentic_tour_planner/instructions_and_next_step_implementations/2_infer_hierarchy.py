"""
Stage B — Infer LOCATED_IN hierarchy edges between pages.

Heuristic: Wikivoyage articles tag themselves with categories like
[[Category:East Sikkim]]. If a category name exactly matches another
page's title, we treat that page as the parent region.

This is imperfect (Wikivoyage's category naming isn't 100% consistent)
but gets you a workable hierarchy fast. Pages with no matching parent
category are left as top-level (e.g., countries/continents) — inspect
'orphans.jsonl' afterward and patch manually if needed.

Input:  pages.jsonl   (from Stage A)
Output: hierarchy_edges.jsonl   -> [{child_poi_id, parent_poi_id}]
        orphans.jsonl           -> pages with no inferred parent, for manual review

Run:
    python 2_infer_hierarchy.py
"""

import json

def slugify(text: str) -> str:
    import re
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")


def main():
    pages = [json.loads(l) for l in open("pages.jsonl", encoding="utf-8")]

    # Map: exact page title (lowercase) -> poi_id, for fast category matching
    title_to_id = {p["page_title"].strip().lower(): p["poi_id"] for p in pages}

    edges = []
    orphans = []

    for page in pages:
        parent_id = None
        for cat in page["categories"]:
            cat_norm = cat.strip().lower()
            if cat_norm in title_to_id and title_to_id[cat_norm] != page["poi_id"]:
                parent_id = title_to_id[cat_norm]
                break  # take the first matching category as primary parent

        if parent_id:
            edges.append({"child_poi_id": page["poi_id"], "parent_poi_id": parent_id})
        else:
            orphans.append(page["page_title"])

    with open("hierarchy_edges.jsonl", "w", encoding="utf-8") as f:
        for e in edges:
            f.write(json.dumps(e) + "\n")

    with open("orphans.jsonl", "w", encoding="utf-8") as f:
        for title in orphans:
            f.write(json.dumps({"page_title": title}) + "\n")

    print(f"Hierarchy edges inferred: {len(edges)}")
    print(f"Orphan pages (no parent found, likely top-level or needs manual fix): {len(orphans)}")


if __name__ == "__main__":
    main()
