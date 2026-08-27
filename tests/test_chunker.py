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