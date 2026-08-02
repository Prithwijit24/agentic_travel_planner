from __future__ import annotations

import bz2
import gc
import re
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import quote

from agentic_tour_planner.domain.models import SourceDocument
from agentic_tour_planner.utils.logging import get_logger

logger = get_logger(__name__)


_CATEGORY_RE = re.compile(r"\[\[Category:([^|\]]+)(?:\|[^\]]*)?\]\]", re.IGNORECASE)
_HEADING_RE = re.compile(r"^\s*={2,6}\s*(.*?)\s*={2,6}\s*$", re.MULTILINE)
_IS_PART_OF_RE = re.compile(r"\{\{\s*(?:ispartof|IsPartOf)\s*\|\s*([^}|]+)", re.IGNORECASE)
_LINK_RE = re.compile(r"\[\[([^|\]#:]+)(?:\|([^\]]+))?\]\]")
_TEMPLATE_RE = re.compile(r"\{\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}\}", re.DOTALL)
_REF_RE = re.compile(r"<ref[^>]*>.*?</ref>|<ref[^/]*/>", re.DOTALL | re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")
_EXTERNAL_LINK_RE = re.compile(r"\[(?:https?|geo):[^\s\]]+(?:\s+([^\]]+))?\]", re.IGNORECASE)


class WikivoyageDumpReader:
    """Stream Wikivoyage XML dumps into SourceDocument records."""

    def __init__(
        self,
        dump_path: str | Path,
        *,
        min_content_chars: int = 200,
        include_redirects: bool = False,
    ) -> None:
        self.dump_path = Path(dump_path)
        self.min_content_chars = min_content_chars
        self.include_redirects = include_redirects
        logger.debug(
            f"Initialized WikivoyageDumpReader dump_path={self.dump_path} min_content_chars={min_content_chars} include_redirects={include_redirects}"
        )

    def count_documents(self, limit: int | None = None) -> int:
        """Count total valid documents in the dump (excluding redirects and small content)."""
        logger.info(f"Counting documents dump_path={self.dump_path} limit={limit}")
        count = 0
        with bz2.open(self.dump_path, "rb") as file_obj:
            # Local trusted Wikivoyage dump, not attacker-controlled input.
            context = ET.iterparse(file_obj, events=("end",))  # noqa: S314
            for _, elem in context:
                if _local_name(elem.tag) != "page":
                    continue
                if self._is_valid_page(elem):
                    count += 1
                elem.clear()
                if limit is not None and count >= limit:
                    break
        gc.collect()
        logger.debug(f"Document count complete count={count}")
        return count

    def _is_valid_page(self, page: ET.Element) -> bool:
        title = _child_text(page, "title")
        namespace = _child_text(page, "ns")
        page_id = _child_text(page, "id")
        redirect = _child(page, "redirect")
        if not title or namespace != "0" or not page_id:
            return False
        if redirect is not None and not self.include_redirects:
            return False
        revision = _child(page, "revision")
        raw_text = _child_text(revision, "text") if revision is not None else ""
        if not raw_text:
            return False
        content = clean_wikivoyage_wikitext(raw_text)
        return len(content) >= self.min_content_chars

    def iter_documents(self, limit: int | None = None) -> Iterator[SourceDocument]:
        logger.info(f"Iterating documents dump_path={self.dump_path} limit={limit}")
        yielded = 0
        with bz2.open(self.dump_path, "rb") as file_obj:
            # Local trusted Wikivoyage dump, not attacker-controlled input.
            context = ET.iterparse(file_obj, events=("end",))  # noqa: S314
            for _, elem in context:
                if _local_name(elem.tag) != "page":
                    continue
                document = self._document_from_page(elem)
                elem.clear()
                if document is None:
                    continue
                yield document
                yielded += 1
                if yielded % 100 == 0:
                    gc.collect()
                if limit is not None and yielded >= limit:
                    break
        logger.debug(f"Document iteration complete yielded={yielded}")

    def _document_from_page(self, page: ET.Element) -> SourceDocument | None:
        title = _child_text(page, "title")
        namespace = _child_text(page, "ns")
        page_id = _child_text(page, "id")
        redirect = _child(page, "redirect")
        if not title or namespace != "0" or not page_id:
            return None
        if redirect is not None and not self.include_redirects:
            return None
        revision = _child(page, "revision")
        raw_text = _child_text(revision, "text") if revision is not None else ""
        if not raw_text:
            return None

        metadata = extract_wikivoyage_metadata(raw_text)
        content = clean_wikivoyage_wikitext(raw_text)
        if len(content) < self.min_content_chars:
            return None
        return SourceDocument(
            source_id=f"wikivoyage-dump:{page_id}",
            source_type="wikivoyage",
            title=f"{title.replace('_', ' ')} travel guide",
            url=f"https://en.wikivoyage.org/wiki/{quote(title.replace(' ', '_'), safe='/')}",
            content=content,
            metadata={
                **metadata,
                "destination": title.replace("_", " "),
                "page_id": page_id,
                "source": "wikivoyage_dump",
                "raw_title": title,
            },
        )


def extract_wikivoyage_metadata(wikitext: str) -> dict:
    logger.debug(f"Extracting Wikivoyage metadata input_len={len(wikitext)}")
    categories = [item.replace("_", " ").strip() for item in _CATEGORY_RE.findall(wikitext)]
    headings = [item.strip() for item in _HEADING_RE.findall(wikitext)]
    parent_match = _IS_PART_OF_RE.search(wikitext)
    links = []
    for target, _ in _LINK_RE.findall(wikitext):
        normalized = target.replace("_", " ").strip()
        if normalized and not normalized.lower().startswith(("file:", "image:", "category:")):
            links.append(normalized)
    return {
        "parent": parent_match.group(1).replace("_", " ").strip() if parent_match else None,
        "categories": list(dict.fromkeys(categories)),
        "headings": list(dict.fromkeys(headings)),
        "links": list(dict.fromkeys(links))[:100],
    }


def clean_wikivoyage_wikitext(wikitext: str) -> str:
    logger.debug(f"Cleaning Wikivoyage wikitext input_len={len(wikitext)}")
    text = _CATEGORY_RE.sub("", wikitext)
    text = _REF_RE.sub("", text)
    text = _TEMPLATE_RE.sub("", text)
    text = _EXTERNAL_LINK_RE.sub(lambda match: match.group(1) or "", text)
    text = _LINK_RE.sub(lambda match: match.group(2) or match.group(1).replace("_", " "), text)
    text = _HEADING_RE.sub(lambda match: f"\n{match.group(1).strip()}\n", text)
    text = _TAG_RE.sub("", text)
    text = re.sub(r"'{2,5}", "", text)
    text = re.sub(r"^[*#:;]+\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n{3,}", "\n\n", text)
    result = "\n".join(line.strip() for line in text.splitlines() if line.strip())
    logger.debug(f"Cleaned Wikivoyage wikitext output_len={len(result)}")
    return result


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child(parent: ET.Element | None, local_name: str) -> ET.Element | None:
    if parent is None:
        return None
    for child in parent:
        if _local_name(child.tag) == local_name:
            return child
    return None


def _child_text(parent: ET.Element | None, local_name: str) -> str:
    child = _child(parent, local_name)
    return (child.text or "").strip() if child is not None else ""
