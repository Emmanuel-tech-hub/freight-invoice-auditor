from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles

from app.engine.discrepancy import run_audit
from app.models import AuditResult, InvoiceLineItem, RateCard, Shipment
from app.parsers.contract_parser import ContractData, parse_contract_pdf
from app.parsers.invoice_parser import parse_invoice_pdf
from app.parsers.shipment_parser import parse_shipment_csv
from app.reports.dispute_report import build_dispute_report_csv, build_dispute_report_pdf

app = FastAPI(title="Freight Invoice Auditor")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class AppState:
    """Single-tenant in-memory state for the V1 prototype.

    V1 is the audit engine, not a multi-user platform: no auth/DB yet, so a
    fresh upload of any document type resets that document (not the others),
    and the audit re-runs against whatever's currently loaded.
    """

    def __init__(self) -> None:
        self.contract: ContractData | None = None
        self.invoice_lines: list[InvoiceLineItem] = []
        self.shipments: list[Shipment] = []
        self.last_audit: AuditResult | None = None
        self.carrier_name: str = "Carrier"


state = AppState()


async def _save_upload_to_temp(file: UploadFile, suffix: str) -> Path:
    contents = await file.read()
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(contents)
        return Path(tmp.name)


@app.post("/api/upload/contract")
async def upload_contract(file: UploadFile):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Contract must be a PDF file.")
    tmp_path = await _save_upload_to_temp(file, ".pdf")
    try:
        contract = parse_contract_pdf(tmp_path)
    except Exception as exc:  # pragma: no cover - defensive
        raise HTTPException(400, f"Could not parse contract PDF: {exc}") from exc
    finally:
        tmp_path.unlink(missing_ok=True)

    if not contract.rate_cards:
        raise HTTPException(
            422,
            "No rate cards found in this PDF. See README for the expected contract format.",
        )

    state.contract = contract
    state.last_audit = None
    return {
        "rate_cards_found": len(contract.rate_cards),
        "accessorial_caps_found": len(contract.accessorial_caps),
    }


@app.post("/api/upload/invoice")
async def upload_invoice(file: UploadFile):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Invoice must be a PDF file.")
    tmp_path = await _save_upload_to_temp(file, ".pdf")
    try:
        line_items = parse_invoice_pdf(tmp_path)
    except Exception as exc:  # pragma: no cover - defensive
        raise HTTPException(400, f"Could not parse invoice PDF: {exc}") from exc
    finally:
        tmp_path.unlink(missing_ok=True)

    if not line_items:
        raise HTTPException(
            422,
            "No invoice line items found in this PDF. See README for the expected invoice format.",
        )

    state.invoice_lines = line_items
    state.last_audit = None
    if line_items:
        state.carrier_name = line_items[0].invoice_number.split("-")[0] or "Carrier"
    return {"line_items_found": len(line_items)}


@app.post("/api/upload/shipments")
async def upload_shipments(file: UploadFile):
    if not file.filename.lower().endswith(".csv"):
        raise HTTPException(400, "Shipments file must be a CSV file.")
    tmp_path = await _save_upload_to_temp(file, ".csv")
    try:
        shipments = parse_shipment_csv(tmp_path)
    except Exception as exc:
        raise HTTPException(400, f"Could not parse shipments CSV: {exc}") from exc
    finally:
        tmp_path.unlink(missing_ok=True)

    if not shipments:
        raise HTTPException(422, "No shipment rows found in this CSV.")

    state.shipments = shipments
    state.last_audit = None
    return {"shipments_found": len(shipments)}


@app.get("/api/state")
def get_state():
    return {
        "contract_loaded": state.contract is not None,
        "rate_cards": len(state.contract.rate_cards) if state.contract else 0,
        "invoice_line_items": len(state.invoice_lines),
        "shipments": len(state.shipments),
        "audit_available": state.last_audit is not None,
    }


@app.post("/api/audit", response_model=AuditResult)
def audit():
    if state.contract is None:
        raise HTTPException(400, "Upload a contract PDF first.")
    if not state.invoice_lines:
        raise HTTPException(400, "Upload an invoice PDF first.")
    if not state.shipments:
        raise HTTPException(400, "Upload a shipments CSV first.")

    result = run_audit(
        invoice_lines=state.invoice_lines,
        shipments=state.shipments,
        rate_cards=state.contract.rate_cards,
        accessorial_caps=state.contract.accessorial_caps,
        hourly_rules=state.contract.hourly_rules,
    )
    state.last_audit = result
    return result


@app.get("/api/audit", response_model=AuditResult)
def get_audit():
    if state.last_audit is None:
        raise HTTPException(404, "No audit has been run yet. POST /api/audit first.")
    return state.last_audit


@app.get("/api/export/dispute-report.pdf")
def export_pdf():
    if state.last_audit is None:
        raise HTTPException(404, "No audit has been run yet.")
    pdf_bytes = build_dispute_report_pdf(state.last_audit, carrier_name=state.carrier_name)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=dispute-report.pdf"},
    )


@app.get("/api/export/dispute-report.csv")
def export_csv():
    if state.last_audit is None:
        raise HTTPException(404, "No audit has been run yet.")
    csv_bytes = build_dispute_report_csv(state.last_audit)
    return Response(
        content=csv_bytes,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=dispute-report.csv"},
    )


@app.post("/api/reset")
def reset():
    state.contract = None
    state.invoice_lines = []
    state.shipments = []
    state.last_audit = None
    return {"ok": True}


_frontend_dir = Path(__file__).resolve().parent.parent.parent / "frontend"
if _frontend_dir.exists():
    app.mount("/", StaticFiles(directory=str(_frontend_dir), html=True), name="frontend")
