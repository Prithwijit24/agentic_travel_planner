import bz2

from agentic_tour_planner.ingestion.wikivoyage_dump import WikivoyageDumpReader


def test_wikivoyage_dump_reader_streams_mainspace_articles(tmp_path):
    dump_path = tmp_path / "enwikivoyage.xml.bz2"
    dump_path.write_bytes(
        bz2.compress(
            b"""<mediawiki xmlns="http://www.mediawiki.org/xml/export-0.11/">
  <page>
    <title>Kyoto</title>
    <ns>0</ns>
    <id>42</id>
    <revision>
      <text>{{pagebanner}}
{{IsPartOf|Kansai}}
Kyoto is a historic city.
==See==
* [[Kiyomizu-dera]] temple
[[Category:Guide articles]]
</text>
    </revision>
  </page>
  <page>
    <title>Kyoto old title</title>
    <ns>0</ns>
    <id>43</id>
    <redirect title="Kyoto" />
    <revision><text>#REDIRECT [[Kyoto]]</text></revision>
  </page>
  <page>
    <title>User:Sandbox</title>
    <ns>2</ns>
    <id>44</id>
    <revision><text>Ignore me</text></revision>
  </page>
</mediawiki>"""
        )
    )

    docs = list(WikivoyageDumpReader(dump_path, min_content_chars=20).iter_documents())

    assert len(docs) == 1
    assert docs[0].source_id == "wikivoyage-dump:42"
    assert docs[0].title == "Kyoto travel guide"
    assert "Kyoto is a historic city" in docs[0].content
    assert docs[0].metadata["parent"] == "Kansai"
    assert docs[0].metadata["links"] == ["Kiyomizu-dera"]
    assert docs[0].metadata["categories"] == ["Guide articles"]


def test_count_documents_counts_valid_pages(tmp_path):
    dump_path = tmp_path / "enwikivoyage.xml.bz2"
    dump_path.write_bytes(
        bz2.compress(
            b"""<mediawiki xmlns="http://www.mediawiki.org/xml/export-0.11/">
  <page>
    <title>Kyoto</title>
    <ns>0</ns>
    <id>42</id>
    <revision><text>{{IsPartOf|Kansai}} Kyoto has temples, gardens, markets, transit, food, and museums.</text></revision>
  </page>
  <page>
    <title>Redirect page</title>
    <ns>0</ns>
    <id>43</id>
    <redirect title="Kyoto" />
    <revision><text>#REDIRECT [[Kyoto]]</text></revision>
  </page>
  <page>
    <title>User:Sandbox</title>
    <ns>2</ns>
    <id>44</id>
    <revision><text>Ignore me</text></revision>
  </page>
</mediawiki>"""
        )
    )

    reader = WikivoyageDumpReader(dump_path, min_content_chars=20)
    count = reader.count_documents()

    assert count == 1
