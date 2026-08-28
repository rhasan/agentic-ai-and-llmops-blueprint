# Semantic Chunking Strategy

When preparing parsed financial documents (like 10-K filings) for vector embeddings and RAG, we must ensure that the structural integrity of the document is maintained—especially for highly complex financial tables.

## The Problem with Traditional Chunking
Traditional text chunking uses strict character or token limits (e.g., splitting every 1000 characters). 
If a hard split falls in the middle of a table, the bottom half of the table loses its column headers and context. An LLM cannot accurately answer questions like "What was the total revenue for 2024?" if it only retrieves a row of raw numbers without headers.

## The Solution: Semantic Chunking
Instead of chunking by strict limits, we chunk by **structure**. 
Since our documents have been parsed into clean Markdown, we can use the Markdown syntax to intelligently divide the text.

1. **Keep Tables Whole:** We identify Markdown table boundaries (which typically start and end with blank lines) and ensure the entire table remains together in a single chunk.
2. **Chunk by Headers & Paragraphs:** For standard text, we split along natural structural lines—such as Markdown headers (`#`, `##`) or paragraph breaks (`\n\n`)—rather than cutting a sentence in half.

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

### What if a table exceeds the context window?
Modern embedding models and LLMs have very large context windows, so a single Markdown table almost always fits easily within a single chunk (e.g., 2000 tokens).

If a table is truly astronomical in size, we rely on fallbacks:
- **Header Duplication:** Programmatically splitting the table by rows but re-attaching the column headers to every new chunk.
- **Table Summarization:** Using an LLM offline to write a textual summary of the table and embedding that summary alongside the table data.

*For our ingestion pipeline, adhering strictly to Semantic Chunking (keeping tables whole) is our primary strategy.*
