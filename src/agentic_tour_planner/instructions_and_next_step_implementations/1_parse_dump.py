"""
Stage A — Parse the Wikivoyage XML dump into structured POI + page records.

Input:  enwikivoyage-latest-pages-articles.xml  (downloaded separately)
Output: pois.jsonl        -> one JSON object per POI (see/do/eat/drink/sleep/buy)
        pages.jsonl       -> one JSON object per page (city/region/country) with
                              its own geo-coordinate (if present) and raw categories

Run:
    pip install mwparserfromhell --break-system-packages
    python 1_parse_dump.py enwikivoyage-latest-pages-articles.xml
"""

import json
import re
import sys
import xml.etree.ElementTree as ET

import mwparserfromhell

# Wikivoyage listing template names -> our POI category
LISTING_TEMPLATES = {
    "see": "see",
    "do": "do",
    "eat": "eat",
    "drink": "drink",
    "sleep": "sleep",
    "buy": "buy",
    "listing": "listing",  # generic fallback template some articles use
}

# MediaWiki XML namespace (varies by dump version, this is the common one)
NS = {"mw": "http://www.mediawiki.org/xml/export-0.10/"}


def slugify(text: str) -> str:
    """Turn 'Rumtek Monastery' -> 'rumtek_monastery' for stable IDs."""
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")


def safe_float(val):
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def extract_listings(wikitext: str, page_title: str):
    """
    Parse one page's wikitext and pull out every {{see}}/{{do}}/{{eat}}/... template
    as a structured POI dict. Returns a list of POI dicts (possibly empty).
    """
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
                # .value gives wikitext; strip remaining markup crudely
                val = str(template.get(param).value).strip()
                val = re.sub(r"\[\[|\]\]|\{\{|\}\}", "", val)
                return val
            return default

        name = get("name")
        if not name:
            continue  # skip malformed listings with no name

        poi = {
            "poi_id": f"{slugify(page_title)}__{slugify(name)}",
            "name": name,
            "category": LISTING_TEMPLATES[tname],
            "base_page": page_title,  # the article this listing lives under
            "address": get("address"),
            "lat": safe_float(get("lat")),
            "long": safe_float(get("long")),
            "hours": get("hours"),
            "price": get("price"),
            "phone": get("phone"),
            "long_description_raw": get("content"),  # wikitext, still needs cleaning
        }
        pois.append(poi)

    return pois


def clean_wikitext_to_plain(raw: str) -> str:
    """Strip remaining wikitext markup from a description field so it's plain prose."""
    if not raw:
        return ""
    wikicode = mwparserfromhell.parse(raw)
    return wikicode.strip_code().strip()


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


def main(dump_path: str):
    poi_out = open("pois.jsonl", "w", encoding="utf-8")
    page_out = open("pages.jsonl", "w", encoding="utf-8")

    page_count = 0
    poi_count = 0

    # iterparse streams the file instead of loading it all into memory
    context = ET.iterparse(dump_path, events=("end",))
    for event, elem in context:
        tag = elem.tag.split("}")[-1]  # strip namespace prefix
        if tag != "page":
            continue

        ns_el = elem.find("mw:ns", NS)
        # ns == '0' means main article namespace (skip Talk:, User:, etc.)
        ns_val = ns_el.text if ns_el is not None else elem.findtext("ns")
        if ns_val not in ("0", None):
            elem.clear()
            continue

        title_el = elem.find("mw:title", NS) or elem.find("title")
        title = title_el.text if title_el is not None else elem.findtext("title")

        revision = elem.find("mw:revision", NS) or elem.find("revision")
        text_el = None
        if revision is not None:
            text_el = revision.find("mw:text", NS) or revision.find("text")
        wikitext = text_el.text if text_el is not None and text_el.text else ""

        if title and wikitext:
            # Skip disambiguation / redirect stubs
            if wikitext.strip().lower().startswith("#redirect"):
                elem.clear()
                continue

            lat, lon = extract_page_geo(wikitext)
            categories = extract_categories(wikitext)

            page_record = {
                "page_title": title,
                "poi_id": slugify(title),  # the page itself can BE a city/region node
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

        elem.clear()  # free memory — critical for large dumps

        if page_count % 2000 == 0 and page_count > 0:
            print(f"...processed {page_count} pages, {poi_count} POIs so far")

    poi_out.close()
    page_out.close()
    print(f"DONE. Pages: {page_count}, POIs extracted: {poi_count}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python 1_parse_dump.py <path-to-dump.xml>")
        sys.exit(1)
    main(sys.argv[1])
