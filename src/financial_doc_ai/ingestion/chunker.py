from langchain_text_splitters import (
    MarkdownHeaderTextSplitter,
    RecursiveCharacterTextSplitter,
)


def _row_cells(line: str) -> list[str]:
    """Split one Markdown table row into its cell values (outer pipes dropped)."""
    parts = line.split("|")
    if parts and parts[0].strip() == "":
        parts = parts[1:]
    if parts and parts[-1].strip() == "":
        parts = parts[:-1]
    return [p.strip() for p in parts]


def _is_table_row(line: str) -> bool:
    return line.lstrip().startswith("|")


def _is_separator_row(line: str) -> bool:
    """A `| --- | --- |` row: every cell is only dashes/colons."""
    cells = _row_cells(line)
    return bool(cells) and all(c and set(c) <= set("-:") for c in cells)


def _prefix(header_path: str, text: str) -> str:
    return f"{header_path}\n\n{text}" if header_path else text


class MarkdownChunker:
    """Splits parsed Markdown into retrieval chunks.

    Header-split first so every chunk (prose OR table) knows its section, then
    within a section split into ordered prose/table blocks. Prose is size-split;
    each table is cleaned of layout padding, kept whole (row-split only if it
    exceeds the size limit), and carries its section heading like prose does.
    """

    def __init__(self, chunk_size: int = 16000, chunk_overlap: int = 1600):
        self._header_splitter = MarkdownHeaderTextSplitter(
            headers_to_split_on=[("#", "h1"), ("##", "h2"), ("###", "h3")],
            # Strip the heading from the content; we re-inject the full heading
            # path onto every chunk below, so this avoids a duplicate.
            strip_headers=True,
        )
        self._size_splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size, chunk_overlap=chunk_overlap
        )
        self._chunk_size = chunk_size

    def _split_blocks(self, md: str) -> list[dict]:
        """Split a section into ordered prose/table blocks (#6).

        A table starts at a row immediately followed by a `| --- |` separator and
        runs over contiguous table rows, tolerating blank lines *inside* the
        table, until real non-table text. This replaces line-by-line guessing
        that broke a table at the first internal blank line.
        """
        lines = md.splitlines()
        blocks: list[dict] = []
        i, n = 0, len(lines)
        while i < n:
            if _is_table_row(lines[i]) and i + 1 < n and _is_separator_row(lines[i + 1]):
                buf = [lines[i], lines[i + 1]]
                i += 2
                while i < n:
                    if _is_table_row(lines[i]):
                        buf.append(lines[i])
                        i += 1
                    elif lines[i].strip() == "" and i + 1 < n and _is_table_row(lines[i + 1]):
                        i += 1  # blank line inside the table — skip, stay in table
                    else:
                        break
                blocks.append({"type": "table", "text": "\n".join(buf)})
            else:
                buf = []
                while i < n:
                    if _is_table_row(lines[i]) and i + 1 < n and _is_separator_row(lines[i + 1]):
                        break
                    buf.append(lines[i])
                    i += 1
                if "\n".join(buf).strip():
                    blocks.append({"type": "prose", "text": "\n".join(buf)})
        return blocks

    def _clean_table(self, table_md: str) -> str | None:
        """Drop layout padding from a Markdown table and re-render it (#2, #1).

        10-K HTML uses tables for visual layout, so extraction leaves spacer
        columns/rows that are empty in every cell. We rebuild the grid, drop
        all-empty columns and rows, and re-render. A table with no content left
        (a pure layout table) returns None so the caller skips it.
        """
        grid = [
            _row_cells(line)
            for line in table_md.splitlines()
            if _is_table_row(line) and not _is_separator_row(line)
        ]
        if not grid:
            return None
        ncols = max(len(r) for r in grid)
        grid = [r + [""] * (ncols - len(r)) for r in grid]  # pad ragged rows
        keep = [c for c in range(ncols) if any(row[c] for row in grid)]
        if not keep:
            return None  # every column empty -> layout table
        grid = [[row[c] for c in keep] for row in grid]
        grid = [row for row in grid if any(cell for cell in row)]  # drop empty rows
        if not grid:
            return None
        header, *data = grid
        out = [
            "| " + " | ".join(header) + " |",
            "| " + " | ".join("---" for _ in header) + " |",
        ]
        out += ["| " + " | ".join(row) + " |" for row in data]
        return "\n".join(out)

    def _split_table(self, table_md: str) -> list[str]:
        """Bound a table to the size limit by splitting on rows (#5).

        Kept whole when it fits. Otherwise split by data rows, repeating the
        header + separator on each part so every piece is a valid, self-describing
        table. A safety net — normal tables fit in one chunk.
        """
        if len(table_md) <= self._chunk_size:
            return [table_md]
        header, sep, *data = table_md.splitlines()
        base = len(header) + len(sep) + 2
        parts: list[str] = []
        cur: list[str] = []
        size = base
        for row in data:
            if cur and size + len(row) + 1 > self._chunk_size:
                parts.append("\n".join([header, sep, *cur]))
                cur, size = [], base
            cur.append(row)
            size += len(row) + 1
        if cur:
            parts.append("\n".join([header, sep, *cur]))
        return parts

    def chunk(self, md: str) -> list[dict]:
        chunks: list[dict] = []
        # Header-split the whole document first, so tables inherit their section
        # heading too (not just prose).
        for section in self._header_splitter.split_text(md):
            header_path = " > ".join(section.metadata.values())
            for block in self._split_blocks(section.page_content):
                if block["type"] == "table":
                    cleaned = self._clean_table(block["text"])
                    if cleaned is None:
                        continue  # layout/empty table dropped
                    for piece in self._split_table(cleaned):
                        chunks.append({
                            "text": _prefix(header_path, piece),
                            "is_table": True,
                            "headers": section.metadata,
                        })
                else:
                    for piece in self._size_splitter.split_text(block["text"]):
                        if not piece.strip():
                            continue
                        chunks.append({
                            "text": _prefix(header_path, piece),
                            "is_table": False,
                            "headers": section.metadata,
                        })
        # Number the chunks 0, 1, 2, ... so their original order is preserved.
        for i, c in enumerate(chunks):
            c["chunk_index"] = i
        return chunks
