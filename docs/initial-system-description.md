# Financial Document Analysis (w7sysa) — Plain English Summary

## What it is
A **Q&A tool for financial analysts**. They ask questions about filings (10-Ks, contracts) and get short, direct answers — but **every answer must quote the exact source passage it came from**. It's RAG (retrieval + LLM), built for a regulated setting where a wrong answer has legal/financial cost.

## The three rules that drive the whole design
1. **Always cite** — no answer without a source passage to back it.
2. **Abstain over guess** — if nothing in the docs supports an answer, say "I couldn't find it." A confident wrong answer is worse than no answer.
3. **Log everything, permanently** — every query gets an immutable 7-year audit record. If the audit write fails, the request fails.

Priority when they conflict: **correct citation > abstaining > completeness.**

## How it works
**Offline (indexing):** Filings arrive via feed, contracts via upload (scanned ones go through OCR). Documents get parsed (tables kept whole, never split), chunked, tagged with metadata (company, type, period, **version**), embedded, and stored in a vector index. Old versions are never deleted — they're audit evidence.

**Online (answering a question):**
1. Authenticate (enterprise SSO).
2. **Query rewrite** → pull out filters (which company, filing type, period).
3. **Retrieve** matching chunks.
4. **Generate** a draft answer with citations.
5. **Grounding check** — verify the answer actually matches the cited text (LLM grader *plus* an exact-match check for numbers). Pass → return it. Fail → abstain.
6. **Audit log** written synchronously before the answer is released.

## Key engineering choices
- **Not web-scale** — ~50 analysts, ~3k queries/day, peak 0.25 QPS. One instance handles it; a second replica is for resilience, not throughput.
- **Grounding is on the critical path and there's no token streaming** — deliberately trading ~2s of latency to never show an uncited claim.
- **Biggest cost** = generation tokens (table-heavy prefill) + the second LLM call for grounding.

## The subtle risk
The worst failure is **mis-extraction**: the query rewrite picks the wrong company/period, so the answer is correctly grounded — in the *wrong document*. The grounding check can't catch this because the answer genuinely matches its (wrong) source. That's why filters are shown to the analyst for verification.
