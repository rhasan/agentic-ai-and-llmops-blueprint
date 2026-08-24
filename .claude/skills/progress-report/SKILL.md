---
name: progress-report
description: Generate a concise status report of the blueprint — what's built, % complete across the three blueprint areas, and remaining effort estimated in work-sessions (not calendar dates). Use when the user asks how far along the project is or how long it will take.
---

# Progress Report

Produce a plain, honest status report of the blueprint's build progress. Text only — do not write files.

## Sources to read first

1. `README.md` — the three blueprint areas that define full scope (Agentic AI architecture, Storage & infrastructure, LLMOps).
2. `docs/work-in-progress.md` — the live step-by-step tracker (what's done, what's next).
3. Any relevant `docs/*-plan.md` for the stage in flight.
4. Recent git log for corroboration.

Ground every claim in these sources. Do not invent progress.

## Report structure

Output these sections, in order:

### 1. Where we are
Short bullet list of what is built (group by pipeline stage / subsystem), then a one-line "next up" pointing at the planned-but-unbuilt stage.

### 2. How far through the whole blueprint
A markdown table with one row per blueprint area (from the README) and a rough % complete with a one-phrase justification:

| Area | Status |
|------|--------|
| Storage & infra | ~X% — ... |
| Agentic AI architecture | ~X% — ... |
| LLMOps | ~X% — ... |

Follow with one honest overall %, and note whether the hard-to-retrofit foundation is already in place (which makes remaining work go faster).

### 3. Time
Do **not** give calendar dates. Estimate in **work-sessions** (sessions like the ones being worked), broken into phases with a session range each:

- Finish current pipeline stage: ~N sessions
- Online RAG path: ~N sessions
- Agent layer: ~N sessions
- LLMOps: ~N sessions
- Cloud migration: ~N sessions

Give a total session range, then name the 1–2 biggest sources of variance (usually LLMOps depth and the cost-gated cloud phase).

## Tone

Concise and plain. No slang, no hedging filler. Match the calibration in `CLAUDE.md`: report the production *shape*, not the example's scale. Be honest about what's not started.
