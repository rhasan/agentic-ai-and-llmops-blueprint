from financial_doc_ai.ingestion.chunker import MarkdownChunker


def test_table_kept_whole():
  md = """# Section
Some intro prose.

| Year | Revenue |
| --- | --- |
| 2024 | 100 |
| 2023 | 90 |

More prose after the table.
"""
  chunks = MarkdownChunker().chunk(md)
  tables = [c for c in chunks if c["is_table"]]
  assert len(tables) == 1
  assert "2024" in tables[0]["text"] and "2023" in tables[0]["text"]


def test_headers_captured():
  md = "# Item 1A\nRisk factors prose here.\n"
  chunks = MarkdownChunker().chunk(md)
  assert any("Item 1A" in str(c["headers"]) or "Item 1A" in c["text"]
             for c in chunks)


def test_heading_prepended_to_every_subchunk():
  # A section long enough to force the size splitter to break it into several
  # pieces. Every piece must carry the heading, not just the first.
  prose = "Supply chain risk sentence. " * 200
  md = f"# Item 1A. Risk Factors\n{prose}\n"
  chunks = MarkdownChunker(chunk_size=300, chunk_overlap=30).chunk(md)
  assert len(chunks) > 1  # the section really was split
  assert all(c["text"].startswith("Item 1A. Risk Factors") for c in chunks)


def test_heading_not_duplicated():
  # strip_headers=True removes the heading from the content, so after we
  # re-inject it the heading text appears exactly once per chunk.
  md = "# Item 1A. Risk Factors\nRisk factors prose here.\n"
  chunks = MarkdownChunker().chunk(md)
  assert all(c["text"].count("Item 1A. Risk Factors") == 1 for c in chunks)


def test_nested_heading_path_joined():
  # Multi-level headings are joined into a single path so a sub-chunk carries
  # its full location in the document.
  md = "# 10-K\n## Item 1A. Risk Factors\nRisk prose here.\n"
  chunks = MarkdownChunker().chunk(md)
  prose = [c for c in chunks if not c["is_table"]]
  assert all(c["text"].startswith("10-K > Item 1A. Risk Factors") for c in prose)


def test_layout_table_dropped():
  # A pure layout table (every cell empty) carries no content and must not
  # become a chunk.
  md = """# Cover
|  |  |  |
| --- | --- | --- |
|  |  |  |
|  |  |  |
"""
  chunks = MarkdownChunker().chunk(md)
  assert [c for c in chunks if c["is_table"]] == []


def test_data_table_padding_removed():
  # Spacer columns (empty in every row) are dropped so labels line up with
  # values again.
  md = """# Financials
| Item |  | 2023 |  | 2022 |
| --- | --- | --- | --- | --- |
| Net sales |  | 383285 |  | 394328 |
"""
  chunks = MarkdownChunker().chunk(md)
  table = [c for c in chunks if c["is_table"]][0]
  assert "| Net sales | 383285 | 394328 |" in table["text"]
  assert "|  |" not in table["text"]  # no empty spacer cells left


def test_table_carries_section_heading():
  # A table must inherit its section heading, in both text and metadata (#3).
  md = """## Item 8. Financial Statements
| Metric | Value |
| --- | --- |
| Revenue | 100 |
"""
  table = [c for c in MarkdownChunker().chunk(md) if c["is_table"]][0]
  assert table["text"].startswith("Item 8. Financial Statements")
  assert table["is_table"] is True
  assert "Item 8" in str(table["headers"])


def test_blank_line_inside_table_kept_whole():
  # A blank line inside a table must not split it into two chunks (#6).
  md = """# T
| A | B |
| --- | --- |
| 1 | 2 |

| 3 | 4 |
"""
  tables = [c for c in MarkdownChunker().chunk(md) if c["is_table"]]
  assert len(tables) == 1
  assert all(v in tables[0]["text"] for v in ("1", "2", "3", "4"))


def test_large_table_split_repeats_header():
  # A table over the size limit is split by rows, repeating the header +
  # separator on each part so every piece is a valid table (#5).
  rows = "\n".join(f"| r{i} | {i} |" for i in range(200))
  md = f"# Big\n| Name | Val |\n| --- | --- |\n{rows}\n"
  tables = [c for c in MarkdownChunker(chunk_size=200, chunk_overlap=20).chunk(md)
            if c["is_table"]]
  assert len(tables) > 1
  assert all("| Name | Val |" in c["text"] for c in tables)
  assert all("| --- | --- |" in c["text"] for c in tables)