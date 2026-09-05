# Freight Invoice Auditor — V1 (Money-Finding Engine)

Upload a carrier **contract**, a carrier **invoice**, and your **shipment
records**. The engine compares every billed line item against the
contracted rate, flags every discrepancy with evidence, and totals the
potential overcharge — then exports a dispute report you can send back to
the carrier.

This is deliberately scoped as **V1**: the audit engine plus the minimum UI
to drive it, not the full platform (auth, database, OCR, LLM extraction,
QuickBooks/Xero/SAP integrations, etc. described in the wider product
vision). The goal is to prove the core value — "here's exactly how much
you're being overcharged, and here's the proof" — before investing in
everything around it.

## How it works

```
contract.pdf ──┐
invoice.pdf ────┼──▶ parse ──▶ match invoice line → shipment → contracted rate ──▶ discrepancies ──▶ dispute report
shipments.csv ──┘
```

1. **Parse** the contract into rate cards (lane + service level → rate,
   minimum charge, fuel surcharge %) and accessorial fee caps.
2. **Parse** the invoice into billed line items (base freight, fuel
   surcharge, accessorial charges, total billed) keyed by shipment ID.
3. **Parse** the shipment CSV into shipment records (lane, weight/miles,
   which accessorial services were actually performed).
4. **Match** each invoice line to its shipment record, then to the
   contracted rate for that lane + service level.
5. **Compare**: recompute what should have been billed and flag every
   difference — rate charged above the contracted rate, fuel surcharge
   above the contracted cap, an accessorial fee billed but never performed,
   or an accessorial billed above its contracted cap.
6. **Report**: a savings dashboard (total billed vs. expected vs.
   overcharge) and a discrepancy table, each row citing the exact contract
   clause and invoice line it's based on. Export as a PDF dispute letter or
   CSV.

## Document extraction: three tiers, not one template

Real-world carrier contracts and invoices come in wildly inconsistent PDF
layouts and terminology. Rather than require one hardcoded format, each
parser tries progressively more general strategies until one produces a
result:

1. **Exact templates** (below) — two structured/semi-structured formats
   the parser recognizes outright, at full confidence.
2. **Heuristic extraction** (`app/parsers/contract_heuristics.py` and
   `invoice_heuristics.py`) — for anything else. Three independent
   strategies run over the document (table columns matched by header
   synonym, single-line lane/rate scanning, and multi-line label:value
   block scanning), driven by a terminology dictionary
   (`app/parsers/synonyms.py`) that maps varied wording — "linehaul",
   "freight rate", "flat rate", "FSC", "detention", "liftgate", "inside
   delivery", etc. — to canonical concepts. Every extracted rate carries a
   **confidence score**, a **source page**, and the **exact source text**
   it came from. Items below the confidence threshold are still used (a
   partial audit beats none) but are flagged everywhere they appear — the
   upload response, the dashboard, and each affected discrepancy row — as
   needing human review before anyone disputes an invoice on their basis.
3. **OCR fallback** for scanned/image-only PDFs, attempted automatically
   when a page has effectively no extractable text. Best-effort: it
   activates if the deploy environment has `tesseract` installed, and
   reports clearly ("scanned PDF, OCR unavailable") rather than silently
   returning nothing if not. See **Limitations** below — it does not work
   on the current Render deployment.

A document is also classified as **not a contract/invoice at all** (no
freight terminology anywhere in it) versus **freight-related but couldn't
be confidently parsed** ("unclear"), so the two failure modes get different,
useful error messages instead of one generic "not found".

Shipment CSVs go through the same philosophy without needing a heuristic
tier: `app/parsers/shipment_parser.py` maps a wide range of header name
variants ("Wt (lbs)", "weight_lb", "weight_lbs" → the same field) via a
synonym table, rather than requiring one exact column-name set.

**Contract PDF** — one line per lane/service rate, plus accessorial caps:

```
LANE: CHICAGO IL -> DALLAS TX | SERVICE: LTL | RATE_TYPE: PER_CWT | RATE: 18.50 | MIN_CHARGE: 150.00 | FUEL_SURCHARGE_PCT: 16.0
CODE: LIFTGATE | DESCRIPTION: Liftgate Service | MAX_AMOUNT: 75.00
```

`RATE_TYPE` is one of `PER_CWT` (per hundredweight), `PER_MILE`, or `FLAT`.

**Invoice PDF** — one line per shipment billed:

```
INVOICE: ACME-INV-88231
SHIPMENT: SHP-1003 | DESCRIPTION: LTL Chicago to Dallas | BASE_FREIGHT: 861.00 | FUEL_SURCHARGE: 137.76 | ACCESSORIALS: LIFTGATE:95.00 | TOTAL_BILLED: 1093.76
```

**Shipment CSV** — one row per shipment:

```
shipment_id,origin,destination,service_level,weight_lbs,miles,ship_date,accessorials
SHP-1003,CHICAGO IL,DALLAS TX,LTL,4100,,2026-02-14,LIFTGATE
```

### A second supported format ("natural" style)

Each parser also recognizes a plain-English style, tried automatically if
the structured template above doesn't match — no mode switch needed, just
upload either kind. Rate cards are treated as `FLAT` per-lane rates, and
detention-style accessorials can carry a free-hours allowance:

```
Chicago, IL -> Dallas, TX: Base $1,200 | Fuel 8% | Residential $75 | Liftgate $60
Detention: $50/hour after first 2 free hours, only when documented.
```

```
Invoice FL-88421
SHP-1001 | Chicago -> Dallas | Base $1,200 | Fuel $96 | Accessorials $135 | Total $1,431
```

```
shipment_id,origin,destination,pieces,weight_lb,delivery_type,liftgate,detention_hours
SHP-1001,"Chicago, IL","Dallas, TX",12,4200,Residential,Liftgate,0
```

Here, accessorials are billed as one lump sum rather than itemized by code,
so the engine derives what should have been charged from the shipment's own
`delivery_type`/`liftgate`/`detention_hours` flags and compares totals,
rather than flagging a specific accessorial line.

Beyond the exact templates above, the heuristic tier has been tested against
8 additional contract layouts and 2 invoice layouts with distinct
terminology, table structures, number formats, and multi-page spread — see
`backend/tests/test_extraction.py` and
`backend/scripts/generate_extraction_fixtures.py`. It's still not unlimited:
see **Limitations** below for what it doesn't handle yet.

## Limitations

The heuristic tier is pattern/synonym-driven, not true language
understanding, so it has real edges:

- **Free-form legal prose without a clear lane-and-number pattern on one
  line, one table row, or one label:value block** (e.g. rates described
  only in a narrative paragraph spanning many sentences) won't be picked
  up. This is the honest ceiling of a rule-based approach; genuinely
  unbounded format understanding is an LLM-extraction problem, not a
  regex/heuristics one.
- **A single contract-wide detention/free-hours rule** — if different
  lanes have different free-hour allowances, only one rule is captured
  (per-lane flat accessorial caps *are* supported correctly; per-lane
  hourly rules are not, yet).
- **OCR does not currently work in production.** It's implemented and
  covered by a test (`test_scanned_pdf_reports_ocr_status_honestly`), but
  requires the `tesseract` binary, which isn't installable on Render's
  native Python runtime (no apt access). It needs either a Docker-based
  Render service with `tesseract-ocr` added via an aptfile, or a cloud OCR
  API swapped in. Until then, a scanned/image-only PDF gets a clear
  "OCR isn't available in this environment" message rather than a silent
  failure or a wrong answer.
- **Confidence scoring is heuristic, not calibrated** — it reflects how
  strong a signal each strategy found (an arrow between two places is a
  stronger lane signal than the word "to"; a specific label like
  "linehaul" is stronger than the generic word "rate"), not a statistically
  validated probability.

## Running it

```bash
cd backend
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
./.venv/bin/uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000 and upload the three sample files in
`backend/sample_data/` (or your own, in the format above), then click
**Run Audit**.

Regenerate the sample data with:

```bash
./.venv/bin/python -m scripts.generate_sample_data
```

Run the test suite:

```bash
./.venv/bin/python -m pytest tests/
```

## API

| Method | Path | Description |
| --- | --- | --- |
| `POST` | `/api/upload/contract` | Upload contract PDF — returns `rate_cards_found`, `needs_review_count`, a human-readable `message`, and `review_items` (low-confidence rates with their evidence) |
| `POST` | `/api/upload/invoice` | Upload invoice PDF — returns `line_items_found`, `needs_review_count`, `message` |
| `POST` | `/api/upload/shipments` | Upload shipments CSV |
| `GET` | `/api/state` | What's currently loaded |
| `POST` | `/api/audit` | Run the audit, return discrepancies + totals |
| `GET` | `/api/audit` | Fetch the last audit result |
| `GET` | `/api/export/dispute-report.pdf` | Download the dispute report as PDF |
| `GET` | `/api/export/dispute-report.csv` | Download the dispute report as CSV |
| `POST` | `/api/reset` | Clear all uploaded data |

V1 is single-tenant and in-memory by design (no auth, no database) — it's
the audit engine, not the platform.

## Project layout

```
freight-invoice-auditor/
  backend/
    app/
      models.py                       # shared domain models (RateCard, Shipment, InvoiceLineItem, Discrepancy, AuditResult)
      parsers/
        contract_parser.py            # tier 1 (exact templates) + dispatches to tier 2/3
        invoice_parser.py             # same, for invoices
        contract_heuristics.py        # tier 2/3: table / line-scan / block-scan strategies + confidence
        invoice_heuristics.py         # same, for invoices
        synonyms.py                   # freight terminology -> canonical concept dictionary
        numbers.py                    # currency/percent parsing tolerant of real-world formatting
        pdf_source.py                 # page-aware text+table extraction, OCR fallback
        shipment_parser.py            # CSV parsing via column-name synonym mapping
      engine/                         # matching + discrepancy detection (the "money-finding" logic)
      reports/                        # PDF/CSV dispute report generation
      main.py                         # FastAPI app
    sample_data/                      # demo contract.pdf, invoice.pdf, shipments.csv
    scripts/
      generate_sample_data.py
      generate_extraction_fixtures.py # builds the 8 varied contract test PDFs
      generate_invoice_fixtures.py    # builds the 2 varied invoice test PDFs
    tests/
      test_engine.py                  # matching/discrepancy engine + the two exact templates
      test_extraction.py              # the varied-format heuristic extraction tests
      fixtures/                       # generated test PDFs/CSVs (see scripts above)
  frontend/
    index.html, styles.css, app.js   # upload UI, savings dashboard, discrepancy table
```

## What's next (beyond V1)

Extraction now handles a genuinely wide range of contract/invoice layouts
via the heuristic tier (see above and **Limitations**). The remaining items
from the original product vision: working OCR in production (a Docker-based
deploy with `tesseract-ocr` installed), an LLM-extraction tier for the
free-form prose the heuristics can't confidently parse, persistent storage
and auth for multiple users/companies, an audit trail, and integrations
(QuickBooks, Xero, NetSuite, SAP, email/cloud storage ingestion) so invoices
flow in and disputes flow out automatically.
