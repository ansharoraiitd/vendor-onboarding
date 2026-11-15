# Vendor Onboarding Automation — Specification
**Version:** 0.4 · **Date:** 2026-11-13 · **Market:** India · **Stack:** Python / FastAPI / SQLite

> [!IMPORTANT]
> **SPEC FROZEN at v0.4.** No further amendments.

---

> [!IMPORTANT]
> **Core principle:** The LLM extracts fields from documents and writes human-readable explanations only.
> Every approve / reject / flag decision is produced by deterministic rule code.
> The LLM **never** decides outcomes. Extracted fields are inputs to rules, and each extracted field
> is **gated by its per-field confidence score** before it can trigger a Hard or Soft check.

---

## Table of Contents
1. [Process Map](#1-process-map)
2. [Data Model](#2-data-model)
3. [Rules Table](#3-rules-table)
4. [Decision Logic](#4-decision-logic)
5. [Vendor Communication](#5-vendor-communication)
6. [Audit Log & Hash Chain](#6-audit-log--hash-chain)
7. [Configuration](#7-configuration)
8. [External Adapter Contract](#8-external-adapter-contract)
9. [PDF Metadata Signals](#9-pdf-metadata-signals)
10. [Entity Type Matrix](#10-entity-type-matrix)
11. [Out of Scope / Future Work](#11-out-of-scope--future-work)
12. [UI Specification](#12-ui-specification)

> [!NOTE]
> **Changelog v0.2 → v0.3:**
> Add §3.13 cross-document consistency checks (CD1–CD6).
> DV1 refined: same GSTIN → Hard; same PAN + different GSTIN + matching name → additional-site flag (allowed); other PAN collision → human_review.
> B3 escalation: Hard only when B3 failed in a **previous run**; drop co-failing-check clause.
> Confidence gate: low-confidence Soft → skipped (no score contribution); only Hard checks gated to Fixable.
> Rejected email categories via deterministic `check_name → category` table; no LLM involvement.
> Core principle reworded: extracted fields are inputs gated by confidence.
> Audit chain writes in a single transaction (seq + hash together).
> PDF metadata: missing or epoch dates produce no signal.
> Eval: add ~8 end-to-end cases with generated PDFs; include legit near-miss vendors; report false-rejection rate.
> Add §12 UI specification.

> [!NOTE]
> **Changelog v0.3 → v0.4:**
> Delete stale §11 bullet: B3 severity does NOT escalate when `attempt_no > 1`; escalation is based on prior-run failure, not attempt count.
> Repeat-failure escalation (B3, CD2, CD4, CD5b): only prior failures where the original extracted-field confidence ≥ `min_confidence` count. Low-confidence prior failures use message "Document unreadable, please re-upload a clearer copy", not the mismatch message.
> CD1, CD3, CD5a, CD6: raw PDF text search first; found → pass. If not found, LLM extraction: edit distance ≤ 2 → Fixable (OCR error). Hard only when confidently different (confidence ≥ min_confidence AND edit distance > 2).
> Add "Escalate" severity to legend; DV1 (PAN collision + name mismatch) → **Escalate**; DV2 → **Escalate**; §4.1 pseudocode updated with escalate tier at top.
> Add `agreed_payment_days` to `vendor_submission` table (buyer-side input; NULL → 15-day MSMED default).
> §12: add Submit page (§12.7) and vendor resubmission view (§12.8); pipeline runs as background task writing events to DB; SSE replays from DB; `human_review` shown externally as "Pending (Under Review)".
> Eval: labels written from domain reasoning before rules; tune/holdout split (~20/~18); ~15 of 38 records legitimate; false-rejection rate shown with n (e.g. "2/15 legitimate vendors incorrectly rejected").
> Audit §6.1: reading last hash and inserting new row must both occur inside the same `BEGIN IMMEDIATE` transaction.

---

## 1. Process Map

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│  INGESTION                                                                       │
│                                                                                  │
│  Vendor submits:                                                                 │
│  ┌────────────────────────┐    ┌──────────────────────────────┐                 │
│  │  submission.json       │    │  Uploaded Documents (PDFs)   │                 │
│  │  (structured fields)   │    │  • Cancelled cheque /        │                 │
│  │                        │    │    bank letter               │                 │
│  │  - legal_name          │    │  • PAN card                  │                 │
│  │  - trade_name          │    │  • GST certificate           │                 │
│  │  - entity_type         │    │  • COI / LLPIN cert          │                 │
│  │  - pan                 │    │  • Udyam certificate         │                 │
│  │  - gstin               │    │  • Address proof             │                 │
│  │  - cin / llpin         │    │                              │                 │
│  │  - ifsc                │    └──────────────────────────────┘                 │
│  │  - bank_account_number │                   │                                 │
│  │  - udyam_number        │                   │                                 │
│  │  - address / state     │                   │                                 │
│  └────────────────────────┘                   │                                 │
│              │                                │                                 │
└──────────────┼────────────────────────────────┼─────────────────────────────────┘
               │                                │
               ▼                                ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│  EXTRACTION  (LLM — read-only role)                                              │
│                                                                                  │
│  For each uploaded PDF:                                                          │
│  • Extract named fields (account holder name, PAN from card, GST legal/trade    │
│    name, Udyam category, COI date, etc.)                                         │
│  • Return structured JSON + field-level confidence score                         │
│  • Attach raw snippet used as evidence                                           │
│  • Also read PDF metadata (producer, CreationDate, ModDate)                      │
│                                                                                  │
│  LLM output → extracted_fields dict (never a decision)                          │
└────────────────────────────┬────────────────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│  DETERMINISTIC VALIDATION & RISK SCORING                                         │
│                                                                                  │
│  Rule engine runs all checks in §3 sequentially.                                │
│  Each check produces a CheckResult:                                              │
│    name, status (pass/fail/warn/missing), severity (hard/fixable/soft),          │
│    evidence, score_contribution, explanation_template                            │
│                                                                                  │
│  External checks call mockable adapters (§8) — no live network in tests.        │
│                                                                                  │
│  Soft-signal risk score accumulated (0–100 cap).                                │
└────────────────────────────┬────────────────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│  DECISION ENGINE  (§4)  — purely deterministic                                   │
│                                                                                  │
│  Precedence order:                                                               │
│  1. Any hard-fail check → REJECTED                                               │
│  2. Any fixable / missing check → PENDING  (vendor notified with item list)     │
│  3. Soft-signal score ≥ threshold → HUMAN_REVIEW                                │
│  4. Otherwise → APPROVED                                                         │
│                                                                                  │
│  LLM writes the human-readable explanation for the decision (§4.3).             │
└────────────────────────────┬────────────────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│  VENDOR COMMUNICATION  (§5)                                                      │
│                                                                                  │
│  Pluggable notifier interface.  Default: write to outbox table + show in UI.    │
│  Real SMTP optional.                                                             │
│                                                                                  │
│  Templates: APPROVED, PENDING (with fixable item list), REJECTED (with reason), │
│             HUMAN_REVIEW (generic "under review" message)                        │
└────────────────────────────┬────────────────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│  AUDIT LOG  (§6)                                                                 │
│                                                                                  │
│  Every state transition appended to hash-chained audit log.                     │
│  SHA-256(prev_hash ‖ canonical JSON of payload).                                │
│  UI exposes "Verify chain" and a demo tamper button.                            │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Data Model

All tables are SQLite. Column types use SQLite affinities (TEXT, INTEGER, REAL, BLOB).

### 2.1 `vendor_submission`

| Column | Type | Notes |
|---|---|---|
| `id` | TEXT PK | UUID v4 |
| `created_at` | TEXT | ISO-8601 UTC |
| `status` | TEXT | `draft` / `submitted` / `processing` / `approved` / `pending` / `rejected` / `human_review` |
| `legal_name` | TEXT | From submission form |
| `trade_name` | TEXT | Optional |
| `entity_type` | TEXT | `proprietorship` / `partnership` / `llp` / `pvt_ltd` / `pub_ltd` / `section8` |
| `pan` | TEXT | Uppercase, 10 chars |
| `gstin` | TEXT | 15 chars |
| `cin` | TEXT | Optional; companies only |
| `llpin` | TEXT | Optional; LLPs only (format `AAA-1234`) |
| `ifsc` | TEXT | 11 chars |
| `bank_account_number` | TEXT | Stored as HMAC-SHA256 (keyed hash) for PII; raw only in memory |
| `bank_account_number_last4` | TEXT | For display |
| `udyam_number` | TEXT | Optional; format `UDYAM-XX-00-0000000` |
| `udyam_category` | TEXT | `micro` / `small` / `medium`; NULL if no Udyam |
| `udyam_activity_type` | TEXT | `manufacturing` / `services` / `trading`; NULL if no Udyam |
| `address_line` | TEXT | |
| `address_state_code` | TEXT | 2-digit GST state code |
| `email` | TEXT | For notifications |
| `raw_json` | TEXT | Full original submission JSON (stored encrypted at rest — future) |
| `soft_risk_score` | REAL | 0–100; computed |
| `payment_term_cap_days` | INTEGER | NULL unless vendor is micro/small MSME and NOT trading; then 15 or 45 |
| `agreed_payment_days` | INTEGER | Buyer-side input; NULL → 15-day MSMED default applies; overrides default when set |
| `attempt_no` | INTEGER | Starts at 1; incremented on each resubmission of a pending vendor |

### 2.2 `document`

| Column | Type | Notes |
|---|---|---|
| `id` | TEXT PK | UUID v4 |
| `submission_id` | TEXT FK | → `vendor_submission.id` |
| `doc_type` | TEXT | `pan_card` / `gst_certificate` / `cancelled_cheque` / `bank_letter` / `coi` / `llpin_cert` / `udyam_cert` / `address_proof` |
| `filename` | TEXT | |
| `storage_path` | TEXT | Relative path under `uploads/` |
| `sha256` | TEXT | File integrity |
| `pdf_producer` | TEXT | From metadata |
| `pdf_creation_date` | TEXT | ISO-8601 |
| `pdf_mod_date` | TEXT | ISO-8601 |
| `extracted_fields` | TEXT | JSON blob from LLM extraction |
| `extraction_confidence` | REAL | 0–1 |
| `uploaded_at` | TEXT | ISO-8601 UTC |

### 2.3 `check_result`

| Column | Type | Notes |
|---|---|---|
| `id` | TEXT PK | UUID v4 |
| `submission_id` | TEXT FK | → `vendor_submission.id` |
| `run_id` | TEXT | Groups all checks from one evaluation run |
| `check_name` | TEXT | Unique identifier from §3 (e.g., `pan_format`) |
| `status` | TEXT | `pass` / `fail` / `warn` / `missing` |
| `severity` | TEXT | `hard` / `fixable` / `soft` / `escalate` |
| `evidence` | TEXT | JSON — raw values used, regex match, adapter response excerpt |
| `score_contribution` | REAL | Positive = risk; 0 for hard/fixable rules |
| `explanation` | TEXT | LLM-written human-readable text (populated post-decision) |
| `evaluated_at` | TEXT | ISO-8601 UTC |

### 2.4 `decision`

| Column | Type | Notes |
|---|---|---|
| `id` | TEXT PK | UUID v4 |
| `submission_id` | TEXT FK | → `vendor_submission.id` |
| `outcome` | TEXT | `approved` / `pending` / `rejected` / `human_review` |
| `hard_fail_checks` | TEXT | JSON array of `check_name` strings that caused rejection |
| `fixable_checks` | TEXT | JSON array of `check_name` strings causing pending |
| `soft_risk_score` | REAL | Final accumulated score |
| `decided_at` | TEXT | ISO-8601 UTC |
| `decided_by` | TEXT | `system` or `<user_id>` for manual overrides |
| `override_reason` | TEXT | Required for manual overrides |
| `llm_explanation` | TEXT | Full human-readable summary from LLM |

### 2.5 `audit_entry`

| Column | Type | Notes |
|---|---|---|
| `id` | TEXT PK | UUID v4 |
| `seq` | INTEGER | Monotonically increasing global sequence |
| `submission_id` | TEXT | Included in payload |
| `event_type` | TEXT | `submission_created` / `extraction_complete` / `check_run_complete` / `decision_made` / `notification_sent` / `manual_override` / `chain_verified` |
| `payload` | TEXT | Canonical JSON (sorted keys, no whitespace) |
| `prev_hash` | TEXT | SHA-256 hex of previous entry's `entry_hash` |
| `entry_hash` | TEXT | SHA-256(`prev_hash` ‖ `payload`) |
| `created_at` | TEXT | ISO-8601 UTC |

> [!NOTE]
> The genesis entry (`seq = 0`) uses `prev_hash = "GENESIS"` and contains a fixed
> sentinel payload. This sentinel is defined in config and must never change.

### 2.6 `outbox` (communication)

| Column | Type | Notes |
|---|---|---|
| `id` | TEXT PK | UUID v4 |
| `submission_id` | TEXT FK | |
| `recipient_email` | TEXT | |
| `subject` | TEXT | |
| `body_text` | TEXT | Plain-text body |
| `body_html` | TEXT | HTML body |
| `template_name` | TEXT | `approved` / `pending` / `rejected` / `human_review` |
| `status` | TEXT | `queued` / `sent` / `failed` |
| `queued_at` | TEXT | ISO-8601 UTC |
| `sent_at` | TEXT | ISO-8601 UTC; NULL until sent |
| `error` | TEXT | Last error string if `failed` |

---

## 3. Rules Table

### Severity legend
| Severity | Meaning | Decision effect |
|---|---|---|
| **Escalate** | Signals that require human judgement regardless of other results | Forces `human_review` unconditionally (highest priority) |
| **Hard** | Fundamental integrity failure; not fixable by vendor | Forces `rejected` |
| **Fixable** | Missing or correctable data; vendor can resubmit | Forces `pending` |
| **Soft** | Anomaly signal; contributes to risk score only | May cause `human_review` |

### 3.1 PAN

| # | Check name | What is checked | Algorithm | Hard-fail / Fixable / Soft |
|---|---|---|---|---|
| P1 | `pan_format` | Format: `[A-Z]{3}[ABCFGHLJPTK][A-Z]\d{4}[A-Z]` | Regex | **Hard** — invalid format is not a valid PAN |
| P2 | `pan_entity_type_match` | 4th character encodes entity type; must match `entity_type` field | Lookup table (see below) | **Hard** |
| P3 | `pan_status` | Adapter returns `valid` / `invalid` / `missing` | Mock adapter call | **Hard** if `invalid`; **Fixable** if `missing` |

**PAN 4th-character → entity type decode:**

| Char | Entity |
|---|---|
| A | Association of persons |
| B | Body of individuals |
| C | Company (Pvt Ltd / Public Ltd / Section 8) |
| F | Firm (Partnership / LLP) |
| G | Government |
| H | HUF |
| J | Artificial juridical person |
| L | Local authority |
| P | Individual / Proprietor |
| T | Trust / AOP (BOI) |

Validation: `entity_type ∈ {pvt_ltd, pub_ltd, section8}` → 4th char must be `C`; `entity_type ∈ {llp, partnership}` → `F`; `entity_type = proprietorship` → `P`.

### 3.2 GSTIN

| # | Check name | What is checked | Algorithm | Severity |
|---|---|---|---|---|
| G1 | `gstin_format` | Format: `\d{2}[A-Z]{3}[ABCFGHLJPTK][A-Z]\d{4}[A-Z][1-9A-Z][Z][A-Z0-9]` (15 chars; 13th char `[1-9A-Z]` not `\d`) | Regex | **Hard** |
| G2 | `gstin_checksum` | Mod-36 checksum on chars 1–14; last char must equal computed check digit | Mod-36 algorithm (digit set `0-9A-Z`; factors alternate **2, 1**) | **Hard** |
| G3 | `gstin_embedded_pan_match` | Chars 3–12 of GSTIN must equal the submitted PAN | String slice comparison | **Hard** |
| G4 | `gstin_state_code_match` | First 2 digits of GSTIN (state code) must match the **principal place of business state** as extracted from the GST registration certificate (not the submission form's `address_state_code`) | LLM-extracted field; lookup (GST state code table); subject to confidence gate §3.10 | **Fixable** — vendor may have provided wrong form field; GST cert is authoritative |

**GST state codes (reference):** 01 J&K, 02 HP, 03 PB, 04 CH, 05 UT, 06 HR, 07 DL, 08 RJ, 09 UP, 10 BR, 11 SK, 12 AR, 13 MN, 14 ML, 15 MZ, 16 TR, 17 MG, 18 AS, 19 WB, 20 JH, 21 OD, 22 CG, 23 MP, 24 GJ, 26 DD, 27 MH, 28 AP, 29 KA, 30 GA, 31 LD, 32 KL, 33 TN, 34 PY, 35 AN, 36 TG, 37 AP (new), 38 LH.

**GSTIN mod-36 algorithm:**

```
value_map = {str(i): i for i in range(10)}
value_map.update({chr(65+i): 10+i for i in range(26)})  # A=10 … Z=35
factor = 2
total = 0
for char in reversed(gstin[:14]):
    v = value_map[char] * factor
    total += (v // 36) + (v % 36)
    factor = 1 if factor == 2 else 2
check = (36 - (total % 36)) % 36
expected = value_map_reverse[check]  # reverse lookup
assert gstin[14] == expected
```

### 3.3 CIN (Companies only)

CIN format: `[UL]\d{5}[A-Z]{2}\d{4}[A-Z]{3}\d{6}`

| # | Check name | What is checked | Algorithm | Severity |
|---|---|---|---|---|
| C1 | `cin_format` | Regex match of CIN format | Regex | **Hard** |
| C2 | `cin_listing_status` | Char 1: `U` = unlisted, `L` = listed; must match vendor's claimed listing status (if provided) | String slice | **Fixable** |
| C3 | `cin_state_match` | Chars 7–8 (state code, alpha) must match ROC state of registered address | Lookup table (MCA state codes) | **Soft** (+5 risk) — MCA records sometimes reflect historical ROC state; discrepancies are common and not definitively fraudulent |
| C4 | `cin_year_match` | Chars 9–12 (incorporation year) must match COI date year extracted from document | Numeric comparison | **Hard** if mismatch > 0 years |
| C5 | `cin_entity_type_match` | Chars 13–15 (company type code, e.g., `PTC`, `PLC`, `NPL`) must match `entity_type` | Lookup table | **Hard** |
| C6 | `mca_struck_off` | Adapter returns whether company is struck off or under liquidation | Mock adapter call | **Hard** if struck off |

**MCA company type codes (partial):**

| Code | Meaning | Allowed `entity_type` |
|---|---|---|
| PTC | Private company | `pvt_ltd` |
| PLC | Public company | `pub_ltd` |
| NPL | Section 8 / Not-for-profit | `section8` |
| OPC | One-person company | `pvt_ltd` |
| FTC | Foreign company | (out of scope v1) |

### 3.4 LLPIN (LLPs only)

LLPIN format: `[A-Z]{3}-\d{4}` (e.g., `AAA-1234`)

| # | Check name | What is checked | Algorithm | Severity |
|---|---|---|---|---|
| L1 | `llpin_format` | Regex `[A-Z]{3}-\d{4}` | Regex | **Hard** |
| L2 | `llpin_mca_status` | Adapter returns LLP status (active / struck-off) | Mock adapter call | **Hard** if struck-off |

### 3.5 IFSC & Bank Account

| # | Check name | What is checked | Algorithm | Severity |
|---|---|---|---|---|
| B1 | `ifsc_format` | Format: `[A-Z]{4}0[A-Z0-9]{6}` (11 chars; 5th char always `0`) | Regex | **Hard** |
| B2 | `ifsc_lookup` | IFSC resolves to a known bank / branch | Mock adapter call (wraps RBI IFSC database) | **Fixable** if not found |
| B3 | `bank_name_fuzzy_match` | Account holder name from cancelled cheque / bank letter vs `legal_name` and vs GST legal/trade name; use token-set ratio after normalisation | See §3.5.1 | Depends on score (see table below) |

#### 3.5.1 Name normalisation & matching

**Normalise:** lowercase → strip punctuation → remove stop tokens: `m/s`, `pvt`, `private`, `ltd`, `limited`, `llp`, `co`, `and`, `&` → strip extra whitespace.

**Score:** `max(token_set_ratio(bank_name, legal_name), token_set_ratio(bank_name, gst_legal_name), token_set_ratio(bank_name, gst_trade_name))` (use whichever documents are available).

| Score | Status | Severity |
|---|---|---|
| ≥ `config.bank_name_pass_threshold` (default 90) | `pass` | — |
| `config.bank_name_review_threshold` – `config.bank_name_pass_threshold - 1` (default 75–89) | `warn` | **Soft** (+10 risk) |
| < `config.bank_name_review_threshold` (default 75) | `fail` | **Hard** if B3 also failed in a **previous run** (prior `check_result` row for same `submission_id` with `check_name=bank_name_fuzzy_match` and `status=fail`, **and** that prior run's extracted confidence ≥ `min_confidence`); **Fixable** on first failure, or when prior failure had low confidence (use message: "Document unreadable, please re-upload a clearer copy") |

> [!TIP]
> All three threshold values live in `policy.yaml` under `bank_name_match`. Tune them on the eval set before go-live.

### 3.6 Udyam & MSME Payment Terms

UDYAM format: `UDYAM-[A-Z]{2}-\d{2}-\d{7}` (e.g., `UDYAM-MH-00-0012345`)

| # | Check name | What is checked | Algorithm | Severity |
|---|---|---|---|---|
| U1 | `udyam_format` | Regex match | Regex | **Fixable** (non-mandatory field, but if supplied must be valid) |
| U2 | `udyam_category` | LLM extracts category from Udyam certificate: `micro` / `small` / `medium` | LLM extraction + stored in submission | **Fixable** if certificate unreadable |
| U3 | `udyam_activity_type` | LLM extracts activity type: `manufacturing` / `services` / `trading` | LLM extraction + stored in submission | **Fixable** if certificate unreadable |
| U4 | `payment_term_cap` | If category is `micro` or `small` **and** `activity_type ≠ trading`: set `payment_term_cap_days`; `medium` and trading entities do NOT trigger the cap | Business rule (see §3.6.1) | **Soft** (+0 risk; informational flag on vendor master) |

#### 3.6.1 MSME Payment Term Cap Logic

Under MSMED Act 2006 Section 15, and IT Act 2025 Section 37(2)(g) (which re-enacts old Section 43B(h)):

| Condition | `payment_term_cap_days` |
|---|---|
| Written agreement exists, vendor is micro/small, activity ≠ trading | min(agreed days, 45) |
| No written agreement, vendor is micro/small, activity ≠ trading | **15** (MSMED Act 2006 §15 default; starts from day of acceptance) |
| Vendor is `medium` enterprise | NULL (cap does not apply) |
| Vendor `activity_type = trading` | NULL (trading enterprises excluded from §37(2)(g) obligation) |
| Udyam not provided | NULL |

> [!IMPORTANT]
> The 45-day cap and 15-day default **apply only to Micro and Small enterprises that are not trading entities.**
> Medium enterprises are explicitly excluded from Section 37(2)(g) / old 43B(h).
> The cap is a **buyer obligation** flag placed on the vendor master record —
> it has no effect on the vendor approval decision itself.

### 3.7 TDS Higher-Rate Exposure

| # | Check name | What is checked | Algorithm | Severity |
|---|---|---|---|---|
| T1 | `tds_higher_rate_flag` | `pan_status` is `invalid` or `missing` → buyer must deduct TDS at higher rate under IT Act 2025 §397(2) | Derived from check P3 | **Fixable** (vendor must supply valid PAN) |

> [!NOTE]
> Section 206AB of the IT Act 1961 (non-filer surcharge) was omitted by Finance Act 2025
> with effect from 1 April 2025. The Income Tax Act 2025 took effect 1 April 2026.
> Section 397(2) of that Act is the operative provision. Because numbering is contested
> in secondary sources, all UI text and code comments should refer to this by concept
> ("higher TDS for missing / invalid PAN") and cite the section only in a footnote.

### 3.8 External Status Checks (Adapter-backed)

| # | Check name | Adapter | What is returned | Severity |
|---|---|---|---|---|
| E1 | `gstin_status_check` | `GSTINStatusAdapter` | `active` / `cancelled` / `suspended` / `not_found` | **Hard** if cancelled/suspended/not_found |
| E2 | `mca_company_status` | `MCAStatusAdapter` | `active` / `struck_off` / `under_liquidation` / `not_found` | **Hard** if struck_off/under_liquidation |
| E3 | `cvc_gem_debarment` | `DebarmentAdapter` | `clear` / `debarred` / `suspended` with source label | **Hard** if debarred/suspended |
| E4 | `internal_blocklist` | `InternalBlocklistAdapter` | `clear` / `blocked` with reason | **Hard** if blocked |

> [!NOTE]
> All adapters implement a common `AdapterResult` interface (see §8).
> In test/dev, a `MockAdapter` reads from a YAML fixture file.
> Adapter unavailability returns `warn` status with **Soft** (+5 risk) unless the
> check is configured as `required: true`, in which case it escalates to `Fixable`
> (cannot proceed without the check result).

### 3.9 PDF Metadata Signals

(See §9 for full detail.)

| # | Check name | Signal | Max score | Severity |
|---|---|---|---|---|
| M1 | `pdf_editing_tool` | Producer software is Photoshop / Canva / GIMP / Illustrator / Word on a government-issued doc | +5 | **Soft** |
| M2 | `pdf_moddate_gap` | `ModDate − CreationDate > config.pdf_moddate_gap_days` (default 30) | +3 | **Soft** |
| M3 | `pdf_impossible_creation_date` | `CreationDate < claimed_issue_date` (impossible: PDF was supposedly created *before* the government issued the certificate) | +10 | **Soft** |

> [!CAUTION]
> These signals **never cause rejection on their own.**
> Combined maximum contribution to soft risk score is +10 (capped in config).

### 3.10 Extraction Confidence Gate

When a rule depends on a field extracted by the LLM, the confidence gate is applied before the check runs:

| Check type | Condition | Behaviour |
|---|---|---|
| **Hard** check | `confidence >= config.extraction.min_confidence` (default 0.80) | Run check normally |
| **Hard** check | `confidence < config.extraction.min_confidence` | Downgrade result to **Fixable**; ask vendor for clearer document |
| **Soft** check | `confidence >= config.extraction.min_confidence` | Run check; score contribution applies if fired |
| **Soft** check | `confidence < config.extraction.min_confidence` | **Skip entirely** — no score contribution, no `check_result` row written |
| **Fixable** check | Any confidence | Run check normally (fixable is already a "please fix" response; no downgrade needed) |

> [!NOTE]
> The confidence gate applies **per extracted field**, not per document.
> A document can have high confidence for the legal name but low confidence for a date in a table;
> only the specific check using the low-confidence field is affected.

**Checks subject to the confidence gate:**

| Check | Type gated | LLM-extracted field |
|---|---|---|
| G4 `gstin_state_code_match` | Hard → Fixable | Principal-place state from GST certificate |
| C4 `cin_year_match` | Hard → Fixable | Incorporation year from COI |
| M3 `pdf_impossible_creation_date` | Soft → Skip | `claimed_issue_date` from document |
| U2 `udyam_category` | Fixable → (unchanged) | Category from Udyam cert |
| U3 `udyam_activity_type` | Fixable → (unchanged) | Activity type from Udyam cert |
| B3 `bank_name_fuzzy_match` | Soft/Fixable → (unchanged) | Bank account holder name from cheque |
| CD1–CD6 (§3.13) | Per-check type | Various cross-document fields |

### 3.11 Required Documents

| # | Check name | What is checked | Algorithm | Severity |
|---|---|---|---|---|
| D1 | `required_docs_present` | All document types required for `entity_type` (from `policy.yaml:required_documents`) are uploaded and have `sha256` computed | Set difference between required and uploaded `doc_type` values | **Fixable** for each missing doc |

A missing document produces one `check_result` row per missing `doc_type`, each with `status=missing` and `severity=fixable`. The pending notification lists all missing document types in plain language (e.g., "Cancelled cheque or bank letter").

### 3.12 Duplicate Vendor Detection

| # | Check name | What is checked | Algorithm | Severity |
|---|---|---|---|---|
| DV1 | `duplicate_pan_gstin` | Same **GSTIN** already on an active vendor → Hard. Same **PAN** + different GSTIN + legal name matches existing vendor (token-set ≥ 90) → allowed additional GST site (flag only, `additional_site=true`). Same **PAN** + different GSTIN + name does **not** match → **Escalate** (requires human judgement). DV1 excludes the current `submission_id` from the duplicate search. | Exact GSTIN match; PAN match with fuzzy name | **Hard** (GSTIN collision) / **Escalate** (PAN collision + name mismatch) |
| DV2 | `duplicate_bank_account` | Same HMAC-SHA256 of bank account number already on a **different** vendor's approved/pending record | HMAC comparison (see §3.12.1) | **Escalate** (forces `human_review` unconditionally) |
| DV3 | `duplicate_name_fuzzy` | Near-identical `legal_name` on a different approved/pending vendor | Token-set ratio ≥ `config.duplicate_name_threshold` (default 92) after same normalisation as §3.5.1 | **Soft** (+15 risk) |

#### 3.12.1 Bank Account HMAC

```
HMAC-SHA256(key=config.hmac_secret, msg=account_number.strip())
```

- `config.hmac_secret` is a 32-byte random secret in `policy.yaml`; never committed to source control (use env-var override).
- The raw account number is **never** persisted. Only `bank_account_number_hmac` and `bank_account_number_last4` are stored.
- DV2 compares the stored HMAC of an existing approved/pending vendor against the HMAC of the incoming vendor; a match means the same bank account is being used by two distinct legal entities.

> [!CAUTION]
> DV2 (`duplicate_bank_account`) does **not** force `rejected`. It escalates the decision
> to `human_review` unconditionally even if no other soft signal fires. A reviewer must clear it manually.

### 3.13 Cross-Document Consistency Checks

These checks compare fields extracted from uploaded PDFs against each other and against the submission form. All LLM-extracted fields are subject to the confidence gate (§3.10).

| # | Check name | Documents involved | What is compared | Severity |
|---|---|---|---|---|
| CD1 | `pan_card_number_match` | PAN card → submission | First, search the PAN card PDF's raw embedded text for the submitted PAN string (exact match). Found → pass. If not found by raw search, use LLM extraction: extracted value within Levenshtein edit distance ≤ 2 of submitted PAN → **Fixable** (probable OCR error). Hard only when confidently different (confidence ≥ min_confidence AND edit distance > 2). | Raw text search + LLM extraction fallback | **Hard** (confidence-gated: low-confidence → Fixable) |
| CD2 | `pan_card_name_match` | PAN card → submission | Name on PAN card vs `legal_name`; uses normalised token-set ratio ≥ 85 | **Fixable** on first failure; **Hard** if CD2 also failed in a previous run with confidence ≥ min_confidence (low-confidence prior failure → message: "Document unreadable, please re-upload a clearer copy") |
| CD3 | `gst_cert_gstin_match` | GST certificate → submission | First, search the GST certificate PDF's raw embedded text for the submitted GSTIN string (exact match). Found → pass. If not found by raw search, use LLM extraction: extracted value within Levenshtein edit distance ≤ 2 of submitted GSTIN → **Fixable** (probable OCR error). Hard only when confidently different (confidence ≥ min_confidence AND edit distance > 2). | Raw text search + LLM extraction fallback | **Hard** (confidence-gated: low-confidence → Fixable) |
| CD4 | `gst_cert_name_match` | GST certificate → submission | Legal name on GST certificate vs `legal_name`; normalised token-set ratio ≥ 85 | **Fixable** on first failure; **Hard** if CD4 also failed in a previous run with confidence ≥ min_confidence (low-confidence prior failure → message: "Document unreadable, please re-upload a clearer copy") |
| CD5a | `coi_cin_match` | COI → submission | First, search the COI PDF's raw embedded text for the submitted CIN string (exact match). Found → pass. If not found by raw search, use LLM extraction: extracted value within Levenshtein edit distance ≤ 2 of submitted CIN → **Fixable** (probable OCR error). Hard only when confidently different (confidence ≥ min_confidence AND edit distance > 2). | Raw text search + LLM extraction fallback | **Hard** (confidence-gated: low-confidence → Fixable) |
| CD5b | `coi_name_match` | COI → submission | Company name on COI vs `legal_name`; normalised token-set ratio ≥ 85 | **Fixable** on first failure; **Hard** if CD5b also failed in a previous run with confidence ≥ min_confidence (low-confidence prior failure → message: "Document unreadable, please re-upload a clearer copy") |
| CD6 | `cheque_ifsc_account_match` | Cancelled cheque / bank letter → submission | First, search the cheque PDF's raw embedded text for the submitted IFSC and account number. Found → pass. If not found by raw search, use LLM extraction: extracted value within Levenshtein edit distance ≤ 2 of submitted value → **Fixable** (probable OCR error). Hard only when confidently different. | Raw text search + LLM extraction fallback | **Hard** (confidence-gated: low-confidence → Fixable) |
| CD7 | `gst_cert_address_vs_proof` | GST certificate ↔ address proof | State + city extracted from both; mismatch is a soft signal | **Soft** (+8 risk; confidence-gated: low-confidence → Skip) |

#### CD1–CD6 name-match threshold
The threshold for cross-document name matching (CD2, CD4, CD5b) is `config.cross_doc.name_match_threshold` (default 85), lower than B3's pass threshold because document OCR quality is variable.

#### First-failure vs repeat-failure logic (B3, CD2, CD4, CD5b)
"Failed in a previous run" means: a `check_result` row exists for the same `submission_id` with the same `check_name` and `status = fail`, with an earlier `evaluated_at` timestamp (i.e., from a prior pipeline run, not the current one). **Only prior failures where the LLM-extracted field confidence was ≥ `config.extraction.min_confidence` count toward repeat-failure escalation.** A prior failure caused by low confidence (downgraded to Fixable via the confidence gate) does NOT count as a qualifying prior failure — it uses the message "Document unreadable, please re-upload a clearer copy" rather than the standard mismatch message.

> [!NOTE]
> CD checks only run when the relevant document has been uploaded. If the document is absent,
> `required_docs_present` (D1, §3.11) already raises a Fixable. CD checks are skipped for absent docs.

---

## 4. Decision Logic

### 4.1 Precedence order (strict)

```
function decide(check_results, soft_risk_score) → Decision:

  # Confidence gate: downgrade hard checks on low-confidence LLM fields to fixable
  check_results = apply_confidence_gate(check_results)

  # Escalate tier: requires human review unconditionally (highest priority)
  escalate_checks = [r for r in check_results
                     if r.severity == "escalate" and r.status in ("fail", "warn")]
  if escalate_checks:
      return Decision(outcome="human_review", reason="escalate",
                      escalate_checks=escalate_checks)

  hard_fails = [r for r in check_results if r.severity == "hard" and r.status == "fail"]
  if hard_fails:
      return Decision(outcome="rejected", hard_fail_checks=hard_fails)

  fixable_issues = [r for r in check_results
                    if r.severity in ("fixable") and r.status in ("fail", "missing")]
  if fixable_issues:
      return Decision(outcome="pending", fixable_checks=fixable_issues)

  if soft_risk_score >= config.human_review_threshold:   # default: 20
      return Decision(outcome="human_review")

  return Decision(outcome="approved")
```

### 4.2 Soft risk score accumulation

- Each soft check that fires adds its `score_contribution` (defined in §3 and in config).
- Score is capped at 100.
- PDF metadata signals are individually capped before summing (see §9).
- Weights live in `policy.yaml` and are tunable.

### 4.3 LLM explanation role

After the decision is computed, the LLM is called **once** with:
- The decision outcome
- The list of triggered checks with their `evidence` fields
- A prompt template asking it to write a plain-language explanation for the vendor (and separately, a reviewer note)

The LLM output is stored in `decision.llm_explanation`. It does not alter the outcome.

### 4.4 Manual override

A human reviewer may override any decision. Required fields: `override_reason` (non-empty), `decided_by` (user ID). Override is recorded in `decision` and appended to the audit chain.

---

## 5. Vendor Communication

### 5.1 Interface

```
class Notifier(Protocol):
    def send(self, submission_id: str, template: str, context: dict) -> None: ...
```

### 5.2 Default implementation

Writes a row to `outbox` with rendered subject + body. The UI shows the outbox in a "Communications" tab. Status transitions: `queued → sent` (background worker) or `queued → failed`.

### 5.3 Templates

| Template | Trigger | Required context keys |
|---|---|---|
| `approved` | Decision = APPROVED | `legal_name`, `submission_id`, `decided_at` |
| `pending` | Decision = PENDING | `legal_name`, `fixable_items` (list of human-readable descriptions) |
| `rejected` | Decision = REJECTED | `legal_name`, `hard_fail_items` (non-sensitive descriptions only; do not expose raw regex results) |
| `human_review` | Decision = HUMAN_REVIEW | `legal_name`, `submission_id` (generic "under review" message; no detail) |

> [!WARNING]
> The `rejected` template uses a **deterministic mapping table** (`check_name → category`) —
> no LLM involvement. The mapping is defined in `app/check_categories.py`.
> Example mappings:
>
> | `check_name` | Category shown to vendor |
> |---|---|
> | `pan_format`, `pan_entity_type_match`, `pan_status` | "Identity number issue" |
> | `gstin_format`, `gstin_checksum`, `gstin_embedded_pan_match` | "Tax registration issue" |
> | `gstin_state_code_match`, `cin_state_match` | "Registration address mismatch" |
> | `gstin_status_check`, `mca_company_status` | "Registration status issue" |
> | `cvc_gem_debarment`, `internal_blocklist` | "Eligibility restriction" |
> | `bank_name_fuzzy_match`, `duplicate_bank_account` | "Bank account verification failed" |
> | `cin_format`, `cin_entity_type_match`, `cin_year_match` | "Company registration issue" |
> | `duplicate_pan_gstin` | "Duplicate registration detected" |
> | `pan_card_number_match`, `gst_cert_gstin_match`, `coi_cin_match` | "Document–record mismatch" |
>
> Multiple triggered checks in the same category deduplicate to one line.
> The vendor email never contains check names, regex details, or adapter response text.

### 5.4 Real SMTP (optional)

Implement `SmtpNotifier(Notifier)` using Python `smtplib`. Configured via `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD` environment variables. Toggle with `config.notifier = "smtp"` vs `"outbox"`.

---

## 6. Audit Log & Hash Chain

### 6.1 Algorithm

```
entry_hash = SHA-256(prev_hash ‖ canonical_json(payload))
```

Where:
- `canonical_json` = `json.dumps(payload, sort_keys=True, separators=(',', ':'))` — no whitespace, sorted keys
- `‖` = string concatenation
- `prev_hash` for `seq=0` (genesis) = `"GENESIS"`
- `payload` always includes `submission_id`, `seq`, `event_type`, `created_at`, and event-specific fields

> [!IMPORTANT]
> Reading the last row's `entry_hash` and writing the new row **must both occur inside the same `BEGIN IMMEDIATE` transaction** to prevent race conditions.
> ```sql
> BEGIN IMMEDIATE;
>   SELECT entry_hash FROM audit_entry ORDER BY seq DESC LIMIT 1;  -- read prev_hash
>   INSERT INTO audit_entry (id, seq, submission_id, event_type, payload, prev_hash, entry_hash, created_at)
>   VALUES (...);
> COMMIT;
> ```
> Never write `seq` and `entry_hash` in separate statements; a crash between them would corrupt the chain.

### 6.2 Chain verification

`GET /audit/verify` — walks every entry in `seq` order, recomputes each `entry_hash`, checks it equals stored value and that `prev_hash` equals the previous row's `entry_hash`. Returns `{valid: bool, first_tampered_seq: int | null}`.

### 6.3 Demo tamper mode

`POST /audit/demo-tamper?seq=N` — mutates `payload` of entry N in the database without updating the hash. Used in demos only. Protected by `config.demo_mode = true` guard. The verify endpoint should immediately detect and report the tamper.

> [!CAUTION]
> The chain is **tamper-evident, not tamper-proof.** An attacker with direct database
> access can recompute the entire chain. For production, ship the chain root hash to an
> external append-only store (blockchain, HSM, or a trusted third party). Mention this
> limitation in the UI.

### 6.4 Events logged

| Event | When |
|---|---|
| `submission_created` | Submission record inserted |
| `document_uploaded` | Each document upload |
| `extraction_complete` | LLM extraction finished for a document |
| `check_run_complete` | All rule checks finished for a submission |
| `decision_made` | Decision record written |
| `notification_sent` | Outbox row transitions to `sent` |
| `manual_override` | Human reviewer changes decision |
| `chain_verified` | Verify endpoint called (even if valid) |

---

## 7. Configuration

All tunable parameters live in `policy.yaml` (single buyer). Multi-tenant support is a future extension — no tenant key in v1.

```yaml
# policy.yaml (defaults shown)

decision:
  human_review_threshold: 20       # soft score ≥ this → human_review

bank_name_match:
  pass_threshold: 90               # token-set ratio ≥ 90 → pass
  review_threshold: 75             # 75–89 → warn (+10 risk); < 75 → fixable/hard (see §3.5)
  fail_score_contribution: 10      # soft score added for warn

extraction:
  min_confidence: 0.80             # below this → downgrade hard check to fixable (§3.10)

duplicate_detection:
  name_fuzzy_threshold: 92         # token-set ratio for DV3 near-identical name
  hmac_secret: ""                  # REQUIRED — set via HMAC_SECRET env var; never commit

pdf_metadata:
  editing_tool_score: 5
  moddate_gap_days: 30             # ModDate - CreationDate threshold
  moddate_gap_score: 3
  impossible_date_score: 10
  max_total_score: 10              # cap on combined PDF signals

risk_weights:                      # soft-signal score contributions
  adapter_unavailable: 5
  bank_name_warn: 10
  pdf_editing_tool: 5
  pdf_moddate_gap: 3
  pdf_impossible_date: 10
  cin_state_mismatch: 5
  duplicate_name_fuzzy: 15

adapters:
  gstin_status: mock               # mock | live
  mca_status: mock
  debarment: mock
  internal_blocklist: mock
  ifsc_lookup: mock
  pan_status: mock
  notifier: outbox                 # outbox | smtp

demo_mode: false                   # enables /audit/demo-tamper endpoint

buyer:
  name: "Acme Procurement Pvt Ltd"
  gstin: "27AABCA1234A1Z5"

required_documents:
  proprietorship: [pan_card, gst_certificate, cancelled_cheque, address_proof]
  partnership:    [pan_card, gst_certificate, cancelled_cheque, address_proof]
  llp:            [pan_card, gst_certificate, cancelled_cheque, llpin_cert]
  pvt_ltd:        [pan_card, gst_certificate, cancelled_cheque, coi]
  pub_ltd:        [pan_card, gst_certificate, cancelled_cheque, coi]
  section8:       [pan_card, gst_certificate, cancelled_cheque, coi]
```

---

## 8. External Adapter Contract

All external checks are behind a common interface. This makes them mockable in tests and replaceable in production without touching rule logic.

```python
@dataclass
class AdapterResult:
    status: str            # adapter-specific status string
    raw_response: dict     # full response for evidence storage
    source: str            # e.g. "mock", "gstn.gov.in", "mca21.gov.in"
    retrieved_at: str      # ISO-8601 UTC

class BaseAdapter(Protocol):
    def query(self, **kwargs) -> AdapterResult: ...
```

### Adapters in scope for v1

| Adapter class | Inputs | Key `status` values |
|---|---|---|
| `PANStatusAdapter` | `pan` | `valid` / `invalid` / `missing` |
| `GSTINStatusAdapter` | `gstin` | `active` / `cancelled` / `suspended` / `not_found` |
| `MCAStatusAdapter` | `cin` or `llpin` | `active` / `struck_off` / `under_liquidation` / `not_found` |
| `DebarmentAdapter` | `pan`, `gstin`, `legal_name` | `clear` / `debarred` / `suspended` (sources: CVC, GeM) |
| `InternalBlocklistAdapter` | `pan`, `gstin`, `legal_name` | `clear` / `blocked` with `reason` |
| `IFSCAdapter` | `ifsc` | `found` with bank/branch info / `not_found` |

### Mock adapter

`MockAdapter` reads from `tests/fixtures/adapter_responses.yaml`, keyed by `(adapter_name, primary_key)`. Fixture file is committed to the repo. Any key not in the fixture returns a configurable default (e.g., `not_found` for status adapters).

---

## 9. PDF Metadata Signals (Detail)

These are **soft signals only.** They contribute to the risk score but never trigger rejection.

| Signal | Check | Score | Rationale |
|---|---|---|---|
| Editing tool on gov doc | `pdf.producer` matches pattern for Photoshop, Canva, GIMP, Illustrator, Corel, LibreOffice Draw, MS Word on doc types: `gst_certificate`, `coi`, `llpin_cert`, `udyam_cert`, `pan_card` | +5 | Legitimate government PDFs are generated by government portal software, not design tools |
| Large ModDate gap | `ModDate − CreationDate > config.pdf_moddate_gap_days` | +3 | Suggests the PDF was opened and re-saved after original creation |
| Impossible creation date | `CreationDate < claimed_issue_date` where `claimed_issue_date` is extracted from the document text by the LLM | +10 | The PDF's creation timestamp predates the date on which the government issued the certificate — logically impossible for a genuine document |

**Cap:** Even if all three fire, total PDF score contribution is capped at `config.pdf_metadata.max_total_score` (default 10).

**Not checked:** A recent `CreationDate` on a scanned document is meaningless (the scanner creates the PDF today) and is not flagged.

**No signal for missing or epoch dates:** If `CreationDate` or `ModDate` is absent from the PDF metadata, or if the parsed date is at or before the Unix epoch (1970-01-01), treat it as missing — produce no M2 or M3 signal for that document. Do not let a missing date trigger a false positive.

---

## 10. Entity Type Matrix

| Entity type | PAN 4th char | CIN required | LLPIN required | Udyam applicable |
|---|---|---|---|---|
| `proprietorship` | `P` | No | No | Yes (micro/small/medium) |
| `partnership` | `F` | No | No | Yes |
| `llp` | `F` | No | **Yes** | Yes |
| `pvt_ltd` | `C` | **Yes** | No | Yes (if MSME registered) |
| `pub_ltd` | `C` | **Yes** | No | Rare; include |
| `section8` | `C` | **Yes** | No | Unlikely; include for completeness |

> [!NOTE]
> Trusts (`T`) are out of scope for v1. Add as a future extension.
> For LLPs, the check that companies use CIN (`C3–C6`) is replaced by LLPIN checks (`L1–L2`).

---

## 11. Out of Scope / Future Work

| Item | Notes |
|---|---|
| **Multi-tenancy** | Add `tenant_id` to all tables; move `policy.yaml` to a `tenant_policy` table |
| **Trusts** | PAN 4th char `T`; no CIN/LLPIN; different docs |
| **RBI defaulter list** | No clean public vendor-level API; revisit when available |
| **Non-filer TDS surcharge (206AB)** | Omitted by Finance Act 2025; do not implement |
| **Real SMTP** | `SmtpNotifier` stub is defined; wire if time permits |
| **Live adapter integrations** | GSTN sandbox, MCA21 API, RazorpayX IFSC, etc. |
| **Encryption at rest** | `raw_json` and document storage; use SQLCipher or field-level encryption |
| **Webhook notifications** | Add `WebhookNotifier` alongside email |
| **Document version history** | Track each resubmission of a document |
| **HSM / external root hash** | Publish chain root to an append-only store for true tamper-evidence |
| **Medium enterprise 43B(h) clarification** | Monitor MCA/CBDT circulars; medium enterprises are currently excluded |

### In v1 scope (moved from deferred)

**Resubmission loop:**
- `vendor_submission.attempt_no` starts at 1 and increments on each resubmission triggered by a `pending` decision.
- On update, re-run all checks (`run_id` increments; previous `check_result` rows are retained for audit).
- API: `PATCH /submissions/{id}/resubmit` — validates that status is `pending`, increments `attempt_no`, re-triggers the pipeline.

**Eval set & threshold tuning:**
- **Ground truth labels** are written from domain reasoning *before* running rules (to avoid anchoring on rule outputs). Labels reflect what a knowledgeable compliance officer would decide.
- **~38 total records** split into ~20 tune / ~18 holdout sets; **~15 of 38 records are legitimate vendors** (some with soft-signal near-misses). This is the reference population for the false-rejection rate.
- **30 rules-only records** (`tests/fixtures/eval_set_rules.yaml`): synthetic vendor JSON with no PDFs; ground truth = `{expected_outcome, expected_triggered_checks[]}`. Cover each entity type, each failure mode, each soft signal, edge cases (checksum off-by-one, near-identical name, trading MSME, additional GST site).
- **~8 end-to-end records** (`tests/fixtures/eval_set_e2e.yaml`): synthetic vendor JSON + programmatically generated PDFs (via `scripts/generate_synthetic_pdfs.py`). These exercise the LLM extraction layer and cross-document checks. Cover: clean approval, legit name that is a near-miss (e.g., "Acme Pvt Ltd" vs "Acme Private Limited"), low-confidence extraction, PDF metadata signals.
- **Metrics reported by `scripts/run_eval.py`:**
  - Per-check: TP, FP, TN, FN, precision, recall
  - Per-outcome: confusion matrix across {approved, pending, rejected, human_review}
  - **False-rejection rate** = FP / (FP + TN) where FP = legitimate vendor incorrectly rejected; shown with n (e.g. "2/15 legitimate vendors incorrectly rejected")
- **Confusion matrix page** in the UI (`/eval`) shows these metrics; can be re-run against the eval set via a button.


---

## 12. UI Specification

The UI is a single-page app (served by FastAPI with Jinja2 templates or a minimal JS framework). All pages are listed below. The backend is FastAPI; all data comes from the SQLite database via API endpoints.

### 12.1 Live Run View (`/submissions/{id}/run`)

**Purpose:** Show the pipeline executing in real time — one row per stage/check appearing as it completes.

**Technology:** Server-Sent Events (SSE) from `GET /submissions/{id}/run-stream`. Each event is a JSON object:
```json
{
  "stage": "extraction | validation | decision | notification",
  "check_name": "gstin_checksum",
  "status": "pass | fail | warn | missing",
  "severity": "hard | fixable | soft | escalate",
  "message": "GSTIN checksum is valid.",
  "score_contribution": 0,
  "elapsed_ms": 142
}
```

> [!NOTE]
> The pipeline runs as a **background task** that writes each event to the database (`check_result` rows and `audit_entry` rows) as it executes. The SSE endpoint replays from the database (ordered by `evaluated_at`), so a page refresh shows historical events correctly without re-running the pipeline.

> [!IMPORTANT]
> The external-facing status for `human_review` decisions is **"Pending (Under Review)"** when shown to vendors. The internal admin UI shows the real `human_review` label.

**UI layout:**
- Header: submission ID, vendor legal name, start timestamp.
- Growing table with one row per event: stage icon, check name (human-friendly label), status badge (colour-coded), severity badge, message.
- Live risk score meter updating after each soft-signal event.
- Final banner when decision is emitted: APPROVED (green) / PENDING (amber) / REJECTED (red) / HUMAN REVIEW (purple).
- "View full memo" button → navigates to Decision Memo page.

### 12.2 Dashboard (`/`)

**Purpose:** Overview of all submissions with filtering and sorting.

**Columns:** Submission ID (link), Legal Name, Entity Type, GSTIN (truncated), Status badge, Risk Score, Submitted At, Decided At, Actions.

**Filters:** Status multi-select, Entity Type multi-select, Date range (Submitted At), Risk Score range slider, free-text search on Legal Name.

**Sorting:** Any column, default: Submitted At descending.

**KPI strip at top:** Total submissions, counts by status (Approved / Pending / Rejected / Human Review), avg risk score, false-rejection rate (from most recent eval run).

**Actions per row:** View, Re-run checks, Manual override (opens modal).

### 12.3 Decision Memo (`/submissions/{id}/memo`)

**Purpose:** Full human-readable record of a single submission's decision.

**Sections:**
1. **Header:** Vendor name, entity type, submission ID, `attempt_no`, decision outcome badge, decided at, decided by.
2. **Summary box:** LLM-written `llm_explanation` (from `decision.llm_explanation`).
3. **Check results table:** All checks in run order — name, status, severity, evidence (collapsible JSON), score contribution, message.
4. **Risk score breakdown:** Bar chart of soft signals and their contributions summing to final score.
5. **Documents panel:** Thumbnails of uploaded docs with extraction confidence per doc and per field.
6. **Override panel** (if status = human_review): Text area for `override_reason`, Approve / Reject buttons. POST to `PATCH /submissions/{id}/decision`.
7. **Audit timeline:** Most recent 10 audit events for this submission (fetched from `audit_entry`).

### 12.4 Outbox Tab (`/outbox`)

**Purpose:** Show all outgoing vendor emails; allow manual resend.

**Columns:** Submission ID (link), Recipient, Template, Status badge (queued/sent/failed), Queued At, Sent At, Error.

**Filters:** Status, Template name, Date range.

**Row actions:** View rendered email body (modal), Resend (POST to `/outbox/{id}/resend`).

**Body modal:** Shows both plain-text and HTML body in tabs. No check names or technical details visible (confirmed by viewing the rendered template).

### 12.5 Audit Log (`/audit`)

**Purpose:** Tamper-evidence display and demo.

**Layout:**
- **Chain status banner:** "Chain intact ✓" (green) or "⚠ Tampered at seq N" (red), populated by calling `GET /audit/verify` on page load.
- **Verify button:** Re-runs `GET /audit/verify`; shows result inline.
- **Tamper demo button** (only visible when `config.demo_mode = true`): POST to `/audit/demo-tamper?seq=N` with a randomly chosen seq; reloads banner. Used in live demos to show detection.
- **Entries table:** seq, submission ID (link), event type, created at, entry hash (first 12 chars). Clicking a row expands the full canonical payload JSON.
- **Disclaimer:** "This chain is tamper-evident, not tamper-proof. An attacker with direct database access can recompute the chain. For production, publish the root hash to an external append-only store."

### 12.6 Eval Page (`/eval`)

**Purpose:** Run the evaluation suite and display accuracy metrics.

**Layout:**
- **Run Eval button:** POST to `/eval/run`; triggers `scripts/run_eval.py` subprocess; response streams results via SSE.
- **Summary metrics:**
  - False-rejection rate (highlighted — most important)
  - Per-outcome confusion matrix: 4×4 grid for {approved, pending, rejected, human_review}
- **Per-check accordion:** Expandable row per check showing TP / FP / TN / FN / precision / recall. Colour-coded: precision < 0.9 → amber, < 0.7 → red.
- **Eval record table:** One row per eval record; shows vendor name (synthetic), expected outcome, actual outcome, match (✓/✗), triggered checks. Filter by: outcome match / mismatch, entity type, end-to-end vs rules-only.
- **Last run timestamp** shown in footer.

### 12.7 Submit Page (`/submit`)

**Purpose:** Vendor submission entry point; also the primary demo interface.

**Layout:**
- **Demo scenario buttons** (top): one-click buttons that pre-fill the form with canonical demo scenarios: "Clean Approval", "PAN Mismatch", "GSTIN Checksum Fail", "MSME Manufacturer (micro)", "Trading MSME (cap exempt)", "Duplicate GSTIN", "Bank Name Mismatch", "Cancelled GSTIN". Each button fills all fields deterministically so demos are reproducible.
- **"Type your own vendor" toggle:** Collapses demo buttons and shows all form fields blank for manual entry.
- **Form fields:** All `vendor_submission` fields (legal_name, trade_name, entity_type, pan, gstin, cin/llpin, ifsc, bank_account_number, udyam_number, address_line, address_state_code, email, agreed_payment_days) plus a file upload area per document type.
- **Submit button:** POST to `/submissions`; on success, redirect to Live Run View for that submission ID.

### 12.8 Vendor Resubmission View (`/submissions/{id}/resubmit`)

**Purpose:** Allow a vendor (or admin acting on behalf of vendor) to upload corrected documents / fix fields after a `pending` decision.

**Layout:**
- **Status banner:** Shows current pending reason — the list of fixable checks with their human-readable descriptions. No check names or technical details.
- **Pre-filled form:** All form fields pre-filled with current submission values; vendor can edit any field.
- **Document re-upload panel:** Shows which documents are missing or caused failures; file upload input per slot.
- **Submit correction button:** PATCH to `/submissions/{id}/resubmit`; increments `attempt_no`; re-triggers pipeline; redirects to Live Run View.
- **Attempt history:** Read-only timeline showing each attempt, its outcome, and the fixable items that caused it.
