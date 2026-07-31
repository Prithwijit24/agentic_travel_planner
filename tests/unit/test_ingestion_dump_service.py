import bz2

from agentic_tour_planner.config.settings import get_settings
from agentic_tour_planner.ingestion.service import IngestionService


class FakeAiStackClient:
    def __init__(self) -> None:
        self.deleted = []
        self.indexed = []

    def delete_source(self, source_id: str) -> None:
        self.deleted.append(source_id)

    def upsert_documents(self, documents):
        self.indexed.extend(documents)
        return len(documents)


class FakeGraphStore(FakeAiStackClient):
    pass


def test_ingest_wikivoyage_dump_indexes_vector_and_graph(monkeypatch, tmp_path):
    monkeypatch.setenv("OPERATIONS_DB_PATH", str(tmp_path / "plans.db"))
    monkeypatch.setenv("WIKIVOYAGE_DUMP_MIN_CONTENT_CHARS", "20")
    get_settings.cache_clear()
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    (raw_dir / "enwikivoyage-latest-pages-articles.xml.bz2").write_bytes(
        bz2.compress(
            b"""<mediawiki xmlns="http://www.mediawiki.org/xml/export-0.11/">
  <page>
    <title>Kyoto</title>
    <ns>0</ns>
    <id>42</id>
    <revision><text>{{IsPartOf|Kansai}} Kyoto has temples, gardens, markets, transit, food, and museums.</text></revision>
  </page>
</mediawiki>"""
        )
    )
    vector_store = FakeAiStackClient()
    graph_store = FakeGraphStore()

    run = IngestionService(ai_stack=vector_store, graph_store=graph_store).ingest_wikivoyage_dump(
        raw_dir,
        batch_size=1,
    )

    assert run.total_sources == 1
    assert run.indexed_sources == 1
    assert graph_store.indexed[0].source_id == "wikivoyage-dump:42"
    assert graph_store.indexed[0].source_id == "wikivoyage-dump:42"


def test_ingest_wikivoyage_dump_skips_existing_records(monkeypatch, tmp_path):
    monkeypatch.setenv("OPERATIONS_DB_PATH", str(tmp_path / "plans.db"))
    monkeypatch.setenv("WIKIVOYAGE_DUMP_MIN_CONTENT_CHARS", "20")
    get_settings.cache_clear()
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    (raw_dir / "enwikivoyage-latest-pages-articles.xml.bz2").write_bytes(
        bz2.compress(
            b"""<mediawiki xmlns="http://www.mediawiki.org/xml/export-0.11/">
  <page>
    <title>Kyoto</title>
    <ns>0</ns>
    <id>42</id>
    <revision><text>{{IsPartOf|Kansai}} Kyoto has temples, gardens, markets, transit, food, and museums.</text></revision>
  </page>
</mediawiki>"""
        )
    )
    vector_store = FakeAiStackClient()
    graph_store = FakeGraphStore()
    service = IngestionService(ai_stack=vector_store, graph_store=graph_store)

    run1 = service.ingest_wikivoyage_dump(raw_dir, batch_size=1)
    assert run1.indexed_sources == 1

    vector_store.indexed = []
    run2 = service.ingest_wikivoyage_dump(raw_dir, batch_size=1)
    assert run2.indexed_sources == 0
    assert run2.skipped_sources == 1


def test_insert_or_update_dump_inserts_new(monkeypatch, tmp_path):
    monkeypatch.setenv("OPERATIONS_DB_PATH", str(tmp_path / "plans.db"))
    monkeypatch.setenv("WIKIVOYAGE_DUMP_MIN_CONTENT_CHARS", "20")
    get_settings.cache_clear()
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    (raw_dir / "enwikivoyage-latest-pages-articles.xml.bz2").write_bytes(
        bz2.compress(
            b"""<mediawiki xmlns="http://www.mediawiki.org/xml/export-0.11/">
  <page>
    <title>Kyoto</title>
    <ns>0</ns>
    <id>42</id>
    <revision><text>{{IsPartOf|Kansai}} Kyoto has temples, gardens, markets, transit, food, and museums.</text></revision>
  </page>
</mediawiki>"""
        )
    )
    vector_store = FakeAiStackClient()
    graph_store = FakeGraphStore()

    run = IngestionService(ai_stack=vector_store, graph_store=graph_store).insert_or_update_dump(
        raw_dir,
        batch_size=1,
    )

    assert run.total_sources == 1
    assert run.indexed_sources == 1
    assert graph_store.indexed[0].source_id == "wikivoyage-dump:42"


def test_insert_or_update_dump_updates_changed_content(monkeypatch, tmp_path):
    monkeypatch.setenv("OPERATIONS_DB_PATH", str(tmp_path / "plans.db"))
    monkeypatch.setenv("WIKIVOYAGE_DUMP_MIN_CONTENT_CHARS", "20")
    get_settings.cache_clear()
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    (raw_dir / "enwikivoyage-latest-pages-articles.xml.bz2").write_bytes(
        bz2.compress(
            b"""<mediawiki xmlns="http://www.mediawiki.org/xml/export-0.11/">
  <page>
    <title>Kyoto</title>
    <ns>0</ns>
    <id>42</id>
    <revision><text>{{IsPartOf|Kansai}} Kyoto has temples, gardens, markets, transit, food, and museums.</text></revision>
  </page>
</mediawiki>"""
        )
    )
    vector_store = FakeAiStackClient()
    graph_store = FakeGraphStore()
    service = IngestionService(ai_stack=vector_store, graph_store=graph_store)

    run1 = service.insert_or_update_dump(raw_dir, batch_size=1)
    assert run1.indexed_sources == 1

    vector_store.indexed = []
    (raw_dir / "enwikivoyage-latest-pages-articles.xml.bz2").write_bytes(
        bz2.compress(
            b"""<mediawiki xmlns="http://www.mediawiki.org/xml/export-0.11/">
  <page>
    <title>Kyoto</title>
    <ns>0</ns>
    <id>42</id>
    <revision><text>{{IsPartOf|Kansai}} Kyoto has been updated with new information about attractions.</text></revision>
  </page>
</mediawiki>"""
        )
    )

    run2 = service.insert_or_update_dump(raw_dir, batch_size=1)
    assert run2.indexed_sources == 1
    assert run2.skipped_sources == 0
    assert graph_store.indexed[0].content != "Kyoto has temples, gardens, markets, transit, food, and museums."


def test_insert_or_update_dump_skips_unchanged_content(monkeypatch, tmp_path):
    monkeypatch.setenv("OPERATIONS_DB_PATH", str(tmp_path / "plans.db"))
    monkeypatch.setenv("WIKIVOYAGE_DUMP_MIN_CONTENT_CHARS", "20")
    get_settings.cache_clear()
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    (raw_dir / "enwikivoyage-latest-pages-articles.xml.bz2").write_bytes(
        bz2.compress(
            b"""<mediawiki xmlns="http://www.mediawiki.org/xml/export-0.11/">
  <page>
    <title>Kyoto</title>
    <ns>0</ns>
    <id>42</id>
    <revision><text>{{IsPartOf|Kansai}} Kyoto has temples, gardens, markets, transit, food, and museums.</text></revision>
  </page>
</mediawiki>"""
        )
    )
    vector_store = FakeAiStackClient()
    graph_store = FakeGraphStore()
    service = IngestionService(ai_stack=vector_store, graph_store=graph_store)

    run1 = service.insert_or_update_dump(raw_dir, batch_size=1)
    assert run1.indexed_sources == 1

    run2 = service.insert_or_update_dump(raw_dir, batch_size=1)
    assert run2.indexed_sources == 0
    assert run2.skipped_sources == 1
