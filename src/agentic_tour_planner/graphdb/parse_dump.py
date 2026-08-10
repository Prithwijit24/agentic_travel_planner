"""Parse the Wikivoyage XML dump into structured POI + page records.

Input:  enwikivoyage-latest-pages-articles.xml  (downloaded separately)
Output: pois.jsonl        -> one JSON object per POI (see/do/eat/drink/sleep/buy)
        pages.jsonl       -> one JSON object per page (city/region/country) with
                              its own geo-coordinate (if present) and raw categories

Run:
    python -m agentic_tour_planner.graphdb.parse_dump enwikivoyage-latest-pages-articles.xml
"""

from __future__ import annotations

import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import mwparserfromhell

LISTING_TEMPLATES = {
    "see": "see",
    "do": "do",
    "eat": "eat",
    "drink": "drink",
    "sleep": "sleep",
    "buy": "buy",
    "listing": "listing",
}

NS = {"mw": "http://www.mediawiki.org/xml/export-0.10/"}


def _register_namespaces():
    """Register the mw namespace prefix so ElementTree find() works with iterparse."""
    ET.register_namespace("mw", NS["mw"])


def slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")


def safe_float(val):
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def post_clean(text: str) -> str:
    """Catch what mwparserfromhell.strip_code() leaves behind."""
    if not text:
        return ""
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\bSee also\b\.?$", "", text)
    text = re.sub(r"\s+\.", ".", text)
    return text.strip()


def extract_listings(wikitext: str, page_title: str):
    """Parse one page's wikitext and pull out every {{see}}/{{do}}/{{eat}}/... template."""
    pois = []
    try:
        parsed = mwparserfromhell.parse(wikitext)
    except Exception:
        return pois

    for template in parsed.filter_templates():
        tname = str(template.name).strip().lower()
        if tname not in LISTING_TEMPLATES:
            continue

        def get(param, default=""):
            if template.has(param):
                val = str(template.get(param).value).strip()
                val = re.sub(r"\[\[|\]\]|\{\{|\}\}", "", val)
                return val
            return default

        name = get("name")
        if not name:
            continue

        poi = {
            "poi_id": f"{slugify(page_title)}__{slugify(name)}",
            "name": name,
            "category": LISTING_TEMPLATES[tname],
            "base_page": page_title,
            "address": get("address"),
            "lat": safe_float(get("lat")),
            "long": safe_float(get("long")),
            "hours": get("hours"),
            "price": get("price"),
            "phone": get("phone"),
            "long_description_raw": get("content"),
        }
        pois.append(poi)

    return pois


def clean_wikitext_to_plain(raw: str) -> str:
    """Strip remaining wikitext markup from a description field so it's plain prose."""
    if not raw:
        return ""
    wikicode = mwparserfromhell.parse(raw)
    return post_clean(wikicode.strip_code().strip())


def extract_page_geo(wikitext: str):
    """Pages often have their own {{geo|lat|long}} template for the city/region center."""
    parsed = mwparserfromhell.parse(wikitext)
    for template in parsed.filter_templates():
        if str(template.name).strip().lower() == "geo":
            params = [str(p).strip() for p in template.params]
            if len(params) >= 2:
                return safe_float(params[0]), safe_float(params[1])
    return None, None


def extract_categories(wikitext: str):
    return re.findall(r"\[\[Category:([^\]|]+)", wikitext)


def main(dump_path: str, output_dir: str | None = None) -> tuple[int, int]:
    output_path = Path(output_dir) if output_dir else Path(".")
    output_path.mkdir(parents=True, exist_ok=True)

    poi_out = open(output_path / "pois.jsonl", "w", encoding="utf-8")
    page_out = open(output_path / "pages.jsonl", "w", encoding="utf-8")

    page_count = 0
    poi_count = 0

    context = ET.iterparse(dump_path, events=("end",))
    for event, elem in context:
        tag = elem.tag.split("}")[-1]
        if tag != "page":
            continue

        ns_el = elem.find("mw:ns", NS)
        ns_val = ns_el.text if ns_el is not None else elem.findtext("ns")
        if ns_val not in ("0", None):
            elem.clear()
            continue

        title_el = elem.find("mw:title", NS)
        if title_el is None:
            title_el = elem.find("title")
        title = title_el.text if title_el is not None else elem.findtext("title")

        revision = elem.find("mw:revision", NS)
        if revision is None:
            revision = elem.find("revision")
        text_el = None
        if revision is not None:
            text_el = revision.find("mw:text", NS)
            if text_el is None:
                text_el = revision.find("text")
        wikitext = text_el.text if text_el is not None and text_el.text else ""

        if title and wikitext:
            if wikitext.strip().lower().startswith("#redirect"):
                elem.clear()
                continue

            lat, lon = extract_page_geo(wikitext)
            categories = extract_categories(wikitext)

            page_record = {
                "page_title": title,
                "poi_id": slugify(title),
                "lat": lat,
                "long": lon,
                "categories": categories,
            }
            page_out.write(json.dumps(page_record, ensure_ascii=False) + "\n")
            page_count += 1

            listings = extract_listings(wikitext, title)
            for poi in listings:
                poi["long_description"] = clean_wikitext_to_plain(poi.pop("long_description_raw"))
                poi_out.write(json.dumps(poi, ensure_ascii=False) + "\n")
                poi_count += 1

        elem.clear()

        if page_count % 2000 == 0 and page_count > 0:
            print(f"...processed {page_count} pages, {poi_count} POIs so far")

    poi_out.close()
    page_out.close()
    print(f"DONE. Pages: {page_count}, POIs extracted: {poi_count}")
    return page_count, poi_count


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m agentic_tour_planner.graphdb.parse_dump <path-to-dump.xml> [output-dir]")
        sys.exit(1)
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
