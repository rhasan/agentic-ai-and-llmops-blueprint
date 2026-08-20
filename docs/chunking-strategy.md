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

### What if a table exceeds the context window?
Modern embedding models and LLMs have very large context windows, so a single Markdown table almost always fits easily within a single chunk (e.g., 2000 tokens).

If a table is truly astronomical in size, we rely on fallbacks:
- **Header Duplication:** Programmatically splitting the table by rows but re-attaching the column headers to every new chunk.
- **Table Summarization:** Using an LLM offline to write a textual summary of the table and embedding that summary alongside the table data.

*For our ingestion pipeline, adhering strictly to Semantic Chunking (keeping tables whole) is our primary strategy.*
