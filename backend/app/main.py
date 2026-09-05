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
from app.parsers.invoice_parser import parse_invoice_pdf_detailed
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


def _diagnostic_preview(raw_text: str) -> str:
    """Temporary diagnostic: surfaces what was actually extracted from the
    PDF right in the error message, so a failed upload is self-explanatory
    instead of requiring back-and-forth to reproduce.
    """
    text = raw_text.strip()
    if not text:
        return "[Diagnostic: no text was extracted from this PDF at all.]"
    preview = text[:400].replace("\n", " \\n ")
    return f"[Diagnostic - extracted text starts with: {preview!r}]"


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
        preview = _diagnostic_preview(contract.raw_text)
        if contract.ocr_unavailable:
            raise HTTPException(
                422,
                "This looks like a scanned/image-based PDF, and OCR isn't available in this "
                "environment, so no text could be extracted from it. Please upload a "
                f"text-based PDF instead. {preview}",
            )
        if contract.document_classification == "not_a_contract":
            raise HTTPException(
                422,
                "This PDF doesn't appear to be a carrier contract or rate card - no freight "
                f"rate terminology was found in it. {preview}",
            )
        raise HTTPException(
            422,
            "This looks like it could be a contract or rate card, but no rates could be "
            "confidently extracted from it. A clearer copy, or one with rates in a table, "
            f"will usually parse better. {preview}",
        )

    state.contract = contract
    state.last_audit = None

    review_count = len(contract.review_items)
    message = (
        f"Rate information detected, but {review_count} item(s) need review."
        if review_count
        else "Contract parsed successfully."
    )

    return {
        "rate_cards_found": len(contract.rate_cards),
        "accessorial_caps_found": len(contract.accessorial_caps),
        "needs_review_count": review_count,
        "message": message,
        "review_items": [
            {
                "lane": rc.lane,
                "rate_value": rc.rate_value,
                "confidence": rc.confidence,
                "source_page": rc.source_page,
                "source_text": rc.source_text,
            }
            for rc in contract.review_items
        ],
    }


@app.post("/api/upload/invoice")
async def upload_invoice(file: UploadFile):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Invoice must be a PDF file.")
    tmp_path = await _save_upload_to_temp(file, ".pdf")
    try:
        result = parse_invoice_pdf_detailed(tmp_path)
    except Exception as exc:  # pragma: no cover - defensive
        raise HTTPException(400, f"Could not parse invoice PDF: {exc}") from exc
    finally:
        tmp_path.unlink(missing_ok=True)

    if not result.line_items:
        preview = _diagnostic_preview(getattr(result, "raw_text", "") or "")
        if result.ocr_unavailable:
            raise HTTPException(
                422,
                "This looks like a scanned/image-based PDF, and OCR isn't available in this "
                "environment, so no text could be extracted from it. Please upload a "
                f"text-based PDF instead. {preview}",
            )
        if result.document_classification == "not_an_invoice":
            raise HTTPException(
                422,
                "This PDF doesn't appear to be a carrier invoice - no billing line items "
                f"were found in it. {preview}",
            )
        raise HTTPException(
            422,
            "This looks like it could be an invoice, but no billed line items could be "
            f"confidently extracted from it. {preview}",
        )

    line_items = result.line_items
    state.invoice_lines = line_items
    state.last_audit = None
    state.carrier_name = line_items[0].invoice_number.split("-")[0] or "Carrier"

    review_count = sum(1 for li in line_items if li.needs_review)
    message = (
        f"Invoice parsed, but {review_count} item(s) need review."
        if review_count
        else "Invoice parsed successfully."
    )

    return {
        "line_items_found": len(line_items),
        "needs_review_count": review_count,
        "message": message,
    }


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
        "contract_needs_review": len(state.contract.review_items) if state.contract else 0,
        "invoice_line_items": len(state.invoice_lines),
        "invoice_needs_review": sum(1 for li in state.invoice_lines if li.needs_review),
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
