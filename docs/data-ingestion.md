# Data Ingestion

## Data sources
- **Filings (feed):** SEC **EDGAR** — 10-K/10-Q/8-K, free, no auth (`User-Agent` required, ~10 req/s). SEC Financial Statement Data Sets + XBRL/Frames API give structured ground-truth numbers to reconcile against parse/OCR.
- **Contracts (upload):** **CUAD** (510 contracts, 13k+ clause annotations) primary; LEDGAR + EDGAR material-contract exhibits add messier/scanned OCR cases.

## EDGAR = plain client, not MCP
Acquisition is scheduler-driven batch with no LLM in the loop, so MCP (a runtime tool-calling protocol) is the wrong layer. Test: *is an LLM deciding, at runtime, to call this?* No → plain client. MCP is justified only for an optional future runtime "fetch-if-missing" tool.

## Ingestion design
- Offline acquisition stage ends at **raw immutable storage**, before parse/embed. Raw bytes are the audit source of truth.
- Two acquirers, one output contract: **EDGAR** (scheduled batch) and **CUAD** (one-time seed) both emit *raw file + manifest record*.
- **Idempotency** via content hash; **supersession by natural ID** (new version = new record, never overwrite) — old versions are audit evidence.
- **Deterministic tests** via recorded HTTP (VCR.py) — CI runs without hitting EDGAR.

## Orchestration: Dagster
Acquisition is **node 1** of a growable asset DAG (raw → parsed → chunked → indexed); later stages added incrementally. Storage sits behind an **I/O manager**, so local FS → Blob is a config swap, not a DAG rewrite. Start local (container, local-FS I/O manager, in-process executor); migrate to cloud later. Same asset graph throughout.

**Why Dagster:** asset/lineage model maps 1:1 onto the pipeline and showcases the lineage + audit themes; I/O managers are exactly the local→cloud seam; separates *what the pipeline does* from *where it runs/stores*, so local-first now and cloud-later is config, not code.

**Why not:** Prefect — storage lives in task code, so local→cloud is manual and lineage weaker. Airflow — always-on scheduler+webserver, poor teardown/cost fit. Plain jobs/scheduled Actions — cheapest but demonstrate no orchestration pattern.

**Caveat:** more concept load (assets, I/O managers, resources) and runs as a container with a metadata store even locally — accepted because those concepts *are* the blueprint's teaching content.
