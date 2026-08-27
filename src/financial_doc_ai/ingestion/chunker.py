from langchain_text_splitters import (
    MarkdownHeaderTextSplitter,
    RecursiveCharacterTextSplitter,
)


class MarkdownChunker:
    """Splits parsed Markdown into chunks, keeping tables whole.

    Tables are separated out first and each kept as one whole chunk.
    Prose is split by Markdown headers, then by size if a section is
    too large. Chunk size is approximate (character-based).
    """

    def __init__(self, chunk_size: int = 8000, chunk_overlap: int = 800):
        self._header_splitter = MarkdownHeaderTextSplitter(
            headers_to_split_on=[("#", "h1"), ("##", "h2"), ("###", "h3")],
            strip_headers=False,
        )
        self._size_splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size, chunk_overlap=chunk_overlap
        )

    def _is_table_line(self, line: str) -> bool:
        return line.lstrip().startswith("|")

    def _split_tables_and_prose(self, md: str) -> list[dict]:
        """Split the doc into ordered blocks: each is prose or a whole table.

        We walk the document one line at a time, collecting lines into a
        buffer. When we cross the boundary between prose and a table, we
        flush the buffer as a finished block and start a new one. This is
        what keeps each table together as a single block.
        """
        # blocks: the finished pieces, in order. buf: lines collected so far.
        # in_table: are the lines currently in buf part of a table?
        blocks, buf, in_table = [], [], False
        for line in md.splitlines():
            if self._is_table_line(line):
                # A table line. If we were collecting prose, that prose block
                # is now finished — save it and start fresh.
                if not in_table and buf:
                    blocks.append({"type": "prose", "text": "\n".join(buf)})
                    buf = []
                in_table = True
                buf.append(line)
            else:
                # A non-table line. If we were inside a table, the table just
                # ended — save it as one whole block and start fresh.
                if in_table:
                    blocks.append({"type": "table", "text": "\n".join(buf)})
                    buf = []
                    in_table = False
                buf.append(line)
        # End of document: save whatever is left in the buffer as a final block.
        if buf:
            blocks.append(
                {"type": "table" if in_table else "prose", "text": "\n".join(buf)}
            )
        return blocks

    def chunk(self, md: str) -> list[dict]:
        chunks = []
        # Go through the document's blocks in order (prose and whole tables).
        for block in self._split_tables_and_prose(md):
            # A table is kept as a single chunk, never split, so its rows and
            # column headers stay together.
            if block["type"] == "table":
                chunks.append({"text": block["text"], "is_table": True, "headers": {}})
                continue
            # For prose: first split by Markdown headers (this tags each
            # section with its heading), then split any section that is still
            # too large by size. Each resulting piece becomes one chunk.
            for section in self._header_splitter.split_text(block["text"]):
                for piece in self._size_splitter.split_text(section.page_content):
                    chunks.append(
                        {"text": piece, "is_table": False, "headers": section.metadata}
                    )
        # Number the chunks 0, 1, 2, ... so their original order is preserved.
        for i, c in enumerate(chunks):
            c["chunk_index"] = i
        return chunks

