from datetime import date
from decimal import Decimal

from invoice_ocr.models import InvoiceFields, OCRLine, RecognitionResult


def test_result_contract_serializes_dates_money_and_confidence():
    line = OCRLine(text="invoice number: 12345678", score=0.97, box=(10, 20, 200, 42))
    fields = InvoiceFields(
        invoice_category="vat ordinary",
        issue_date=date(2026, 7, 14),
        invoice_number="00123456",
        amount_before_tax=Decimal("100.00"),
        tax_amount=Decimal("6.00"),
        total_amount=Decimal("106.00"),
    )
    result = RecognitionResult(
        source_filename="sample.pdf",
        file_sha256="a" * 64,
        fields=fields,
        field_confidence={"invoice_number": 0.97},
        status="needs_confirmation",
        processing_ms=123,
        ocr_lines=[line],
    )

    payload = result.model_dump(mode="json")
    assert payload["fields"]["issue_date"] == "2026-07-14"
    assert payload["fields"]["invoice_number"] == "00123456"
    assert payload["fields"]["total_amount"] == "106.00"
    assert payload["ocr_lines"][0]["box"] == [10, 20, 200, 42]


def test_confidence_must_be_between_zero_and_one():
    try:
        OCRLine(text="x", score=1.2, box=(0, 0, 1, 1))
    except ValueError:
        return
    raise AssertionError("score above one must be rejected")


def test_fields_preserve_raw_title_and_serialize_all_project_names():
    fields = InvoiceFields(
        invoice_category="电子发票（普通发票）",
        invoice_category_normalized="数电普通发票",
        project_names=["*文具*印章", "*办公用品*纸张"],
    )

    payload = fields.model_dump(mode="json")

    assert payload["invoice_category"] == "电子发票（普通发票）"
    assert payload["invoice_category_normalized"] == "数电普通发票"
    assert payload["project_names"] == ["*文具*印章", "*办公用品*纸张"]
    assert payload["project_name"] == "*文具*印章；*办公用品*纸张"
