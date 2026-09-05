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

## Document format (V1)

Real-world carrier contracts and invoices come in wildly inconsistent PDF
layouts. Rather than guess at arbitrary formats, V1 defines a normalized,
line-based intermediate schema and expects documents in (or pre-processed
into) that format — see `backend/scripts/generate_sample_data.py` for a
full worked example. A future version plugs OCR + an LLM extraction step in
front of the parsers to translate arbitrary carrier PDFs into this same
schema without touching the matching engine at all.

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
| `POST` | `/api/upload/contract` | Upload contract PDF |
| `POST` | `/api/upload/invoice` | Upload invoice PDF |
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
      models.py                 # shared domain models (RateCard, Shipment, InvoiceLineItem, Discrepancy, AuditResult)
      parsers/                  # contract / invoice / shipment parsers
      engine/                   # matching + discrepancy detection (the "money-finding" logic)
      reports/                  # PDF/CSV dispute report generation
      main.py                   # FastAPI app
    sample_data/                # demo contract.pdf, invoice.pdf, shipments.csv
    scripts/generate_sample_data.py
    tests/
  frontend/
    index.html, styles.css, app.js   # upload UI, savings dashboard, discrepancy table
```

## What's next (beyond V1)

Once the engine proves out on real invoices, the natural next steps are the
ones in the original product vision: OCR + LLM extraction to handle
arbitrary (non-templated) carrier PDFs, persistent storage and auth for
multiple users/companies, an audit trail, and integrations (QuickBooks,
Xero, NetSuite, SAP, email/cloud storage ingestion) so invoices flow in and
disputes flow out automatically.
