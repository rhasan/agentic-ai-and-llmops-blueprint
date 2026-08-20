# The Storyline: Governance, Equity Plans & Supply Chain Risk

This document describes the financial domain context, the 3 sample contracts selected for Apple Inc. (CIK `0000320193`), how they connect to Apple's 10-K annual reports, and the showcase Q&A queries they enable.

---

## Domain Context: Why Contracts + 10-Ks Matter

In financial analysis for regulated institutions:
- **Form 10-K (Annual Report):** Discloses high-level numbers, business operations, and risk warnings (e.g., *"We rely on single-source suppliers"* or *"We award restricted stock units to directors"*).
- **Exhibit 10 (Material Contracts):** Contains the actual legally binding agreements that govern those numbers and risks.

An analyst uses the Q&A system to ask questions across both sources—cross-referencing high-level 10-K statements against the underlying legal clauses with exact citations.

---

## The 3 Selected Contracts & Their 10-K Connections

### 1. Apple Non-Employee Director Stock Plan (Amended & Restated)
* **Exhibit Type:** `EX-10.1` (Form 8-K)
* **Filing Index Page:** [Apple 8-K Filing Index (0001140361-26-006577)](https://www.sec.gov/Archives/edgar/data/320193/000114036126006577/0001140361-26-006577-index.htm)
* **Direct Document URL:** [ef20060722_ex10-1.htm](https://www.sec.gov/Archives/edgar/data/320193/000114036126006577/ef20060722_ex10-1.htm)
* **10-K Connection:** Connects to Apple FY2025 10-K *Item 11 (Executive Compensation)* & Note on *Share-Based Compensation*.
* **Showcase Analyst Query:**
  > *"What is the annual equity grant value limit for non-employee directors under Apple's amended stock plan?"*

---

### 2. Form of Restricted Stock Unit (RSU) Award Agreement
* **Exhibit Type:** `EX-10.2` (Form 8-K)
* **Filing Index Page:** [Apple 8-K Filing Index (0001140361-26-006577)](https://www.sec.gov/Archives/edgar/data/320193/000114036126006577/0001140361-26-006577-index.htm)
* **Direct Document URL:** [ef20065677_ex10-2.htm](https://www.sec.gov/Archives/edgar/data/320193/000114036126006577/ef20065677_ex10-2.htm)
* **10-K Connection:** Connects to Apple FY2025 10-K *Item 12 (Security Ownership & Management)* & Note on *Share-Based Information (Vesting & Forfeiture Rules)*.
* **Showcase Analyst Query:**
  > *"What happens to unvested RSUs if a director terminates service prior to the vesting date?"*

---

### 3. Apple Component Purchase & Supply Agreement
* **Exhibit Type:** `EX-10.B.19` (Form 10-K Exhibit / Material Contract)
* **Filing Index Page:** [Apple Filing Index (0001104659-05-058421)](https://www.sec.gov/Archives/edgar/data/320193/000110465905058421/0001104659-05-058421-index.htm)
* **Direct Document URL:** [a05-20674_1ex10dbd19.htm](https://www.sec.gov/Archives/edgar/data/320193/000110465905058421/a05-20674_1ex10dbd19.htm)
* **10-K Connection:** Connects to Apple FY2025 / FY2024 10-K *Item 1 (Business - Manufacturing & Components)* and *Item 1A (Risk Factors: Dependence on third-party single-source component suppliers)*.
* **Showcase Analyst Query:**
  > *"What are Apple's remedies and indemnification rights if a component supplier fails to meet quality or delivery schedules?"*

---

## Which 10-Ks Pair with This Storyline?

Pair these contracts with **Apple's FY2025 10-K** (accession `0000320193-25-000079`) and **FY2024 10-K** (`0000320193-24-000106`).

### Storyline & 10-K Section Mapping:
1. **Governance ➔ Contract 1 (`EX-10.1`):**
   * **10-K Mapping:** *Item 11 (Executive Compensation)* & Note on *Share-Based Compensation*.
   * **Topic:** Governance policies and director compensation caps.
2. **Equity Plans ➔ Contract 2 (`EX-10.2`):**
   * **10-K Mapping:** *Item 12 (Security Ownership & Management)* & Note on *Share-Based Information*.
   * **Topic:** Vesting schedules, termination rules, and forfeiture mechanics.
3. **Supply Chain Risk ➔ Contract 3 (`EX-10.B.19`):**
   * **10-K Mapping:** *Item 1 (Business - Manufacturing & Components)* and *Item 1A (Risk Factors: Single-source suppliers)*.
   * **Topic:** Supplier indemnification, purchase commitments, and supply reliability.

*Note:* Materializing the Dagster `raw_filings` asset automatically fetches the 3 most recent Apple 10-Ks (FY2025, FY2024, FY2023) directly from SEC EDGAR into `/app/data/raw/edgar/` and records them in `manifest.jsonl`.

---

## How to Download & Store the Contracts

1. Open each contract's **Filing Index Page** or **Direct Document URL** in your browser.
2. Save the files locally (`Ctrl+S` → Save As HTML).
3. Place them in `data/seed_contracts/` (or `data/raw/cuad/`) for ingestion by the storage layer into `RawStore`.