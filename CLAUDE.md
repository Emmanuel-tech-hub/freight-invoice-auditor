# Freight Invoice Auditor

V1 of a "money-finding engine" for logistics companies — upload a carrier
contract, a carrier invoice, and shipment records; it matches every billed
invoice line against the contracted rate, flags discrepancies (rate charged
above contract, fuel surcharge above cap, phantom/over-capped accessorial
fees) with cited evidence, totals the potential overcharge, and exports a
dispute report (PDF/CSV).

**Status:** Complete and working. FastAPI backend + vanilla JS/HTML
frontend, sample data, and a passing pytest suite. Verified end-to-end via
browser automation (upload → audit → export all confirmed working).

**To run it:**
```bash
cd backend
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt   # Windows: .venv\Scripts\pip install -r requirements.txt
./.venv/bin/uvicorn app.main:app --reload     # Windows: .venv\Scripts\uvicorn app.main:app --reload
```
Then open http://127.0.0.1:8000 and upload the sample files in
`backend/sample_data/` (or your own — see `README.md` for the expected
document format).

**Full details:** see `README.md` — architecture, document format spec, API
reference, project layout, and what V2 would add (OCR/LLM extraction for
arbitrary PDF layouts, auth/database, QuickBooks/Xero/NetSuite/SAP
integrations).

**Not yet done:** not deployed anywhere live (runs locally only).
