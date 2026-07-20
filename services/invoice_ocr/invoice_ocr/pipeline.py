from __future__ import annotations

from pathlib import Path
from time import perf_counter

from invoice_ocr.documents import prepare_document
from invoice_ocr.engine import OCREngine, text_to_lines
from invoice_ocr.models import InvoiceFields, ParseOutcome, RecognitionResult
from invoice_ocr.parser import parse_invoice

REQUIRED_FIELDS = ("invoice_category", "issue_date", "invoice_number", "amount_before_tax", "tax_amount", "total_amount")


def _elapsed_ms(started: float) -> int:
    return max(0, int((perf_counter() - started) * 1000))


def _is_missing(field_name: str, value: object) -> bool:
    return value is None or (field_name == "project_names" and value == [])


def reconcile_outcomes(ocr: ParseOutcome, embedded: ParseOutcome) -> ParseOutcome:
    values: dict[str, object] = {}
    combined_warnings = list(dict.fromkeys([*ocr.warnings, *embedded.warnings]))
    warnings = [
        warning
        for warning in combined_warnings
        if warning not in {"required_fields_missing", "tax_amount_missing_for_taxable_invoice"}
    ]
    for field_name in InvoiceFields.model_fields:
        primary = getattr(ocr.fields, field_name)
        secondary = getattr(embedded.fields, field_name)
        primary_missing = _is_missing(field_name, primary)
        secondary_missing = _is_missing(field_name, secondary)
        if not primary_missing and not secondary_missing and primary != secondary:
            values[field_name] = [] if field_name == "project_names" else None
            warnings.append(f"field_conflict:{field_name}")
        else:
            values[field_name] = secondary if primary_missing else primary
    fields = InvoiceFields(**values)
    if fields.invoice_category is not None:
        warnings = [warning for warning in warnings if warning != "invoice_category_raw_missing"]
    conflicts = {warning.split(":", 1)[1] for warning in warnings if warning.startswith("field_conflict:")}
    dependency_cleared = False
    if "invoice_category_normalized" in conflicts and "zero_tax_rule_applied" in combined_warnings:
        fields.amount_before_tax = None
        fields.tax_amount = None
        dependency_cleared = True
    if "amount_before_tax_derived_from_total_minus_tax" in combined_warnings:
        if conflicts.intersection({"invoice_category_normalized", "tax_amount", "total_amount"}):
            fields.amount_before_tax = None
            dependency_cleared = True
    if dependency_cleared:
        warnings.append("dependent_fields_cleared_due_to_conflict")
    if fields.tax_amount is None and "tax_amount_missing_for_taxable_invoice" in combined_warnings:
        warnings.append("tax_amount_missing_for_taxable_invoice")
    if any(getattr(fields, field_name) is None for field_name in REQUIRED_FIELDS):
        warnings.append("required_fields_missing")
    return ParseOutcome(fields=fields, field_confidence={}, warnings=list(dict.fromkeys(warnings)))


def recognize_document(
    source: Path,
    work_root: Path,
    engine: OCREngine,
    record_id: str | None = None,
) -> RecognitionResult:
    """Prepare, OCR, parse and reconcile one file; never perform business deduplication."""
    started = perf_counter()
    prepared = prepare_document(source, work_root / "rendered")
    ocr_lines = [line for image in prepared.page_images for line in engine.recognize(image)]
    ocr_outcome = parse_invoice(ocr_lines)
    embedded_lines = text_to_lines(prepared.embedded_text) if prepared.use_embedded_text else []
    embedded_outcome = parse_invoice(embedded_lines) if embedded_lines else ParseOutcome()
    outcome = reconcile_outcomes(ocr_outcome, embedded_outcome)
    return RecognitionResult(
        record_id=record_id,
        source_filename=source.name,
        file_sha256=prepared.source_sha256,
        fields=outcome.fields,
        field_confidence=outcome.field_confidence,
        warnings=outcome.warnings,
        processing_ms=_elapsed_ms(started),
        ocr_lines=[*ocr_lines, *embedded_lines],
        status="needs_confirmation",
    )
