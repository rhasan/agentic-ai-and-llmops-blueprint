# Semantic Chunking Strategy

When preparing parsed financial documents (like 10-K filings) for vector embeddings and RAG, we must ensure that the structural integrity of the document is maintained—especially for highly complex financial tables.

## The Problem with Traditional Chunking
Traditional text chunking uses strict character or token limits (e.g., splitting every 1000 characters). 
If a hard split falls in the middle of a table, the bottom half of the table loses its column headers and context. An LLM cannot accurately answer questions like "What was the total revenue for 2024?" if it only retrieves a row of raw numbers without headers.

## The Solution: Semantic Chunking
Instead of chunking by strict limits, we chunk by **structure**. Since our
documents have been parsed into clean Markdown, we use the Markdown syntax to
divide the text. `MarkdownChunker` header-splits the whole document first (so
every chunk knows its section), then within each section splits into ordered
prose and table blocks.

1. **Chunk by Headers & Size:** Prose is split first along Markdown headers
   (`#`, `##`, `###`), then any oversized section is split by size
   (~16,000 chars ≈ 4,000 tokens, 10% overlap) — well under the embedding
   model's limit, large enough that whole sections usually stay intact.
2. **Keep Tables Whole:** Each Markdown table is one chunk (see the table
   handling below), never split by the prose size splitter — its rows and
   column headers stay together.

### Section context on every chunk (header injection)
Splitting a long section by size leaves all but the first piece **headless** —
their embeddings lose the section context and lose to keyword-dense boilerplate
(a query for "risk factors" then matches a disclaimer that merely names the
section instead of the section itself). So we prepend the section's full heading
path (e.g. `10-K > Item 1A. Risk Factors`) into the **text** of every chunk —
prose *and* tables — before embedding. `strip_headers=True` removes the original
heading line so it is not duplicated. This puts the section into the vector
itself. A table for "Net Sales" under Item 7 would otherwise be just anonymous
numbers with no words to match on. See [retrieval-limitations.md](specs/retrieval-limitations.md).

### Table handling
10-K HTML uses tables heavily for **visual layout** (spacing/alignment), not just
data, and the dumb HTML→Markdown dump converts every one of them verbatim. Left
alone, ~half the chunks become tables and most are empty padding — pure retrieval
noise. All table cleanup is a **Markdown-side** transform in the chunker (the
parser stays a dumb dump):

- **Robust detection:** a table is a row followed by a `| --- |` separator,
  continuing over contiguous rows and **tolerating blank lines inside** it — so a
  stray blank no longer splits one table into two.
- **Drop layout padding:** rebuild the grid, drop columns/rows that are empty in
  every cell, and re-render. Labels line up with values again; a pure-layout
  table (nothing left after the drop) is discarded entirely.
- **Attach the section heading** (as above) so the table is findable by topic.

## Denoising before chunking: running headers/footers

Before chunking, the parser strips **page furniture** — running headers/footers
that print on every page (e.g. `Apple Inc. | 2024 Form 10-K | 57`). These survive
HTML extraction as noise, and because 10-K financial sections are wall-to-wall
tables, a lone footer line sandwiched between two tables gets isolated as its own
one-line chunk. Left in, those junk chunks surface as top retrieval hits and starve
generation of real content.

The rule is **frequency, not position or length**: a line whose *normalized* form
(digits collapsed, whitespace squeezed — so `... | 57` and `... | 58` match)
recurs across many pages is furniture and is dropped; a line that appears once is
content and is kept. This is what protects footnotes — they are load-bearing in
financial docs (`(1) Excludes $2.3B restructuring charge`) and never repeat, so
they are never flagged. Normalization is only a comparison key: kept lines,
including their numbers, are written verbatim. Blank and table lines are never
touched. See `FilingParser._strip_repeated_lines`.

This cleanup is format-agnostic — it runs on the extracted Markdown, so a future
PDF extractor feeds the same step (see [work-in-progress.md](work-in-progress.md)).

### What if a table exceeds the size limit?
A cleaned table almost always fits in one chunk (~4,000 tokens), so keeping it
whole is the primary path. As a safety net, a table larger than the chunk size is
**row-split with the header + separator repeated on every part**, so each piece is
a valid, self-describing table rather than a headless block of numbers. See
`MarkdownChunker._split_table`.

A further offline option, not currently used: **table summarization** — an LLM
writes a textual summary of a large table and that summary is embedded alongside
the raw data.
