from pathlib import Path

from PIL import Image

import invoice_ocr.pipeline as pipeline
from invoice_ocr.models import OCRLine


class FakeEngine:
    def recognize(self, image_path: Path) -> list[OCRLine]:
        values = [
            "电子发票（普通发票）",
            "开票日期 2026-07-14",
            "发票号码 00123456789012345678",
            "合计（不含税） ￥100.00",
            "合计税额 ￥6.00",
            "价税合计 ￥106.00",
            "项目名称：文具印章",
        ]
        return [OCRLine(text=value, score=0.98, box=(0, i * 20, 500, i * 20 + 18)) for i, value in enumerate(values)]


def test_recognize_document_returns_fields_without_duplicate_index(tmp_path: Path):
    source = tmp_path / "invoice.jpg"
    Image.new("RGB", (800, 400), "white").save(source)

    result = pipeline.recognize_document(source, tmp_path / "work", FakeEngine(), record_id="INV-1")

    assert result.record_id == "INV-1"
    assert result.source_filename == "invoice.jpg"
    assert result.fields.invoice_category == "电子发票（普通发票）"
    assert result.fields.project_names == ["文具印章"]
    assert result.fields.project_name == "文具印章"
    assert result.duplicate.is_duplicate is False
    assert len(result.file_sha256) == 64
    assert result.ocr_lines
    assert result.processing_ms >= 0


def test_filename_is_not_parser_input(tmp_path: Path):
    source = tmp_path / "电子发票_错误号码999999_10000元.png"
    Image.new("RGB", (800, 400), "white").save(source)

    result = pipeline.recognize_document(source, tmp_path / "work", FakeEngine())

    assert result.record_id is None
    assert result.fields.invoice_number == "00123456789012345678"
    assert result.fields.invoice_number != "999999"


def test_recognize_document_prefers_page_ocr_even_when_pdf_has_embedded_text(tmp_path: Path):
    import fitz

    source = tmp_path / "invoice.pdf"
    pdf = fitz.open()
    page = pdf.new_page(width=595, height=842)
    page.insert_text((72, 100), "Embedded text is readable but has no invoice fields at all")
    pdf.save(source)
    pdf.close()

    result = pipeline.recognize_document(source, tmp_path / "work", FakeEngine())

    assert result.fields.invoice_number == "00123456789012345678"
    assert result.fields.total_amount is not None


def test_reconcile_clears_conflicting_ocr_and_embedded_fields():
    from invoice_ocr.models import InvoiceFields, ParseOutcome
    from invoice_ocr.pipeline import reconcile_outcomes

    ocr = ParseOutcome(fields=InvoiceFields(invoice_number="00123456"))
    embedded = ParseOutcome(fields=InvoiceFields(invoice_number="87654321"))
    merged = reconcile_outcomes(ocr, embedded)

    assert merged.fields.invoice_number is None
    assert "field_conflict:invoice_number" in merged.warnings
    assert merged.field_confidence == {}


def test_reconcile_drops_stale_missing_tax_warning_when_other_source_has_tax():
    from decimal import Decimal
    from invoice_ocr.models import InvoiceFields, ParseOutcome
    from invoice_ocr.pipeline import reconcile_outcomes

    complete = ParseOutcome(fields=InvoiceFields(
        invoice_category="增值税普通发票",
        tax_amount=Decimal("6.00"),
    ))
    partial = ParseOutcome(
        fields=InvoiceFields(invoice_category="增值税普通发票"),
        warnings=["tax_amount_missing_for_taxable_invoice", "required_fields_missing"],
    )
    merged = reconcile_outcomes(complete, partial)

    assert merged.fields.tax_amount == Decimal("6.00")
    assert "tax_amount_missing_for_taxable_invoice" not in merged.warnings


def test_category_conflict_clears_zero_tax_derived_fields():
    from decimal import Decimal
    from invoice_ocr.models import InvoiceFields, ParseOutcome
    from invoice_ocr.pipeline import reconcile_outcomes

    non_tax = ParseOutcome(
        fields=InvoiceFields(
            invoice_category="北京市出租汽车发票",
            invoice_category_normalized="出租汽车发票",
            amount_before_tax=Decimal("100.00"),
            tax_amount=Decimal("0.00"),
            total_amount=Decimal("100.00"),
        ),
        warnings=["zero_tax_rule_applied"],
    )
    taxable = ParseOutcome(
        fields=InvoiceFields(
            invoice_category="增值税普通发票",
            invoice_category_normalized="增值税普通发票",
            total_amount=Decimal("100.00"),
        ),
        warnings=["tax_amount_missing_for_taxable_invoice"],
    )
    merged = reconcile_outcomes(non_tax, taxable)

    assert merged.fields.invoice_category is None
    assert merged.fields.amount_before_tax is None
    assert merged.fields.tax_amount is None
    assert merged.fields.total_amount == Decimal("100.00")
    assert "dependent_fields_cleared_due_to_conflict" in merged.warnings


def test_reconcile_uses_nonempty_project_list_when_other_source_has_none():
    from invoice_ocr.models import InvoiceFields, ParseOutcome
    from invoice_ocr.pipeline import reconcile_outcomes

    ocr = ParseOutcome(fields=InvoiceFields(project_names=["*文具*印章"]))
    embedded = ParseOutcome(fields=InvoiceFields(project_names=[]))
    merged = reconcile_outcomes(ocr, embedded)

    assert merged.fields.project_names == ["*文具*印章"]
    assert "field_conflict:project_names" not in merged.warnings


def test_reconcile_clears_conflicting_project_lists():
    from invoice_ocr.models import InvoiceFields, ParseOutcome
    from invoice_ocr.pipeline import reconcile_outcomes

    ocr = ParseOutcome(fields=InvoiceFields(project_names=["*文具*印章"]))
    embedded = ParseOutcome(fields=InvoiceFields(project_names=["*服务*咨询费"]))
    merged = reconcile_outcomes(ocr, embedded)

    assert merged.fields.project_names == []
    assert "field_conflict:project_names" in merged.warnings


def test_raw_title_conflict_does_not_clear_tax_when_normalized_category_agrees():
    from decimal import Decimal
    from invoice_ocr.models import InvoiceFields, ParseOutcome
    from invoice_ocr.pipeline import reconcile_outcomes

    ocr = ParseOutcome(
        fields=InvoiceFields(
            invoice_category="电子发票（普通发票）",
            invoice_category_normalized="数电普通发票",
            amount_before_tax=Decimal("100.00"),
            tax_amount=Decimal("0.00"),
            total_amount=Decimal("100.00"),
        ),
        warnings=["zero_tax_rule_applied"],
    )
    embedded = ParseOutcome(
        fields=InvoiceFields(
            invoice_category="江苏电子发票（普通发票）",
            invoice_category_normalized="数电普通发票",
            amount_before_tax=Decimal("100.00"),
            tax_amount=Decimal("0.00"),
            total_amount=Decimal("100.00"),
        ),
        warnings=["zero_tax_rule_applied"],
    )
    merged = reconcile_outcomes(ocr, embedded)

    assert merged.fields.invoice_category is None
    assert merged.fields.invoice_category_normalized == "数电普通发票"
    assert merged.fields.amount_before_tax == Decimal("100.00")
    assert merged.fields.tax_amount == Decimal("0.00")
    assert "dependent_fields_cleared_due_to_conflict" not in merged.warnings


def test_reconcile_drops_stale_raw_title_missing_warning_when_other_source_has_title():
    from invoice_ocr.models import InvoiceFields, ParseOutcome
    from invoice_ocr.pipeline import reconcile_outcomes

    complete = ParseOutcome(fields=InvoiceFields(
        invoice_category="江苏省车辆通行费通用（电子）发票",
        invoice_category_normalized="通行费发票",
    ))
    partial = ParseOutcome(
        fields=InvoiceFields(invoice_category_normalized="通行费发票"),
        warnings=["invoice_category_raw_missing", "required_fields_missing"],
    )

    merged = reconcile_outcomes(complete, partial)

    assert merged.fields.invoice_category == "江苏省车辆通行费通用（电子）发票"
    assert "invoice_category_raw_missing" not in merged.warnings

def test_recognize_document_uses_unique_call_directory_and_cleans_success(tmp_path: Path):
    source = tmp_path / "invoice.png"
    Image.new("RGB", (20, 20), "white").save(source)
    seen_paths: list[Path] = []

    class RecordingEngine(FakeEngine):
        def recognize(self, image_path: Path) -> list[OCRLine]:
            seen_paths.append(image_path)
            return super().recognize(image_path)

    work_root = tmp_path / "work"
    pipeline.recognize_document(source, work_root, RecordingEngine())
    pipeline.recognize_document(source, work_root, RecordingEngine())

    assert len(seen_paths) == 2
    assert seen_paths[0].parent.parent != seen_paths[1].parent.parent
    assert all(not path.exists() for path in seen_paths)
    assert list(work_root.iterdir()) == []


def test_recognize_document_wraps_ocr_error_and_cleans_call_directory(tmp_path: Path):
    import pytest
    from invoice_ocr.documents import DocumentError

    source = tmp_path / "invoice.png"
    Image.new("RGB", (20, 20), "white").save(source)

    class BrokenEngine:
        def recognize(self, _image_path: Path) -> list[OCRLine]:
            raise RuntimeError("ocr exploded")

    work_root = tmp_path / "work"
    with pytest.raises(DocumentError, match="OCR failed for page 1") as error:
        pipeline.recognize_document(source, work_root, BrokenEngine())

    assert isinstance(error.value.__cause__, RuntimeError)
    assert list(work_root.iterdir()) == []


def test_cleanup_retry_recovers_without_warning(tmp_path: Path, monkeypatch):
    source = tmp_path / "invoice.png"
    Image.new("RGB", (20, 20), "white").save(source)
    real_rmtree = pipeline.shutil.rmtree
    calls = 0

    def flaky_rmtree(path: Path):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("transient cleanup failure")
        real_rmtree(path)

    monkeypatch.setattr(pipeline.shutil, "rmtree", flaky_rmtree)

    result = pipeline.recognize_document(source, tmp_path / "work", FakeEngine())

    assert calls == 2
    assert not any(warning.startswith("temporary_files_cleanup_failed") for warning in result.warnings)
    assert list((tmp_path / "work").iterdir()) == []


def test_cleanup_failure_keeps_success_result_and_adds_residual_risk_warning(tmp_path: Path, monkeypatch):
    source = tmp_path / "invoice.png"
    Image.new("RGB", (20, 20), "white").save(source)
    calls = 0

    def failed_rmtree(_path: Path):
        nonlocal calls
        calls += 1
        raise OSError("cleanup is unavailable")

    monkeypatch.setattr(pipeline.shutil, "rmtree", failed_rmtree)

    result = pipeline.recognize_document(source, tmp_path / "work", FakeEngine())

    assert result.fields.invoice_number == "00123456789012345678"
    assert "temporary_files_cleanup_failed:sensitive_invoice_files_may_remain" in result.warnings
    assert calls == 2


def test_cleanup_failure_does_not_mask_processing_error(tmp_path: Path, monkeypatch):
    import pytest
    from invoice_ocr.documents import DocumentError

    source = tmp_path / "invoice.png"
    Image.new("RGB", (20, 20), "white").save(source)
    calls = 0

    class BrokenEngine:
        def recognize(self, _image_path: Path) -> list[OCRLine]:
            raise RuntimeError("ocr exploded")

    def failed_rmtree(_path: Path):
        nonlocal calls
        calls += 1
        raise OSError("cleanup is unavailable")

    monkeypatch.setattr(pipeline.shutil, "rmtree", failed_rmtree)

    with pytest.raises(DocumentError, match="OCR failed for page 1") as error:
        pipeline.recognize_document(source, tmp_path / "work", BrokenEngine())

    assert isinstance(error.value.__cause__, RuntimeError)
    assert any("sensitive invoice files may remain" in note for note in error.value.__notes__)
    assert calls == 2
