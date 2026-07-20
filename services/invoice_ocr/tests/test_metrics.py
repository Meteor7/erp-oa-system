import json
from pathlib import Path

from invoice_ocr.metrics import evaluate_files


def test_metrics_reports_per_field_and_aggregate_accuracy(tmp_path: Path):
    fields = {
        "invoice_category": "vat ordinary",
        "project_name": "*service*consulting",
        "issue_date": "2026-07-14",
        "invoice_number": "00123456",
        "amount_before_tax": "100.00",
        "tax_amount": "6.00",
        "total_amount": "106.00",
    }
    results = [{"source_filename": "a.pdf", "fields": fields, "status": "needs_confirmation", "processing_ms": 100}]
    truth = {"a.pdf": {"include_in_accuracy": True, "fields": fields}}
    results_path = tmp_path / "results.json"
    truth_path = tmp_path / "truth.json"
    results_path.write_text(json.dumps(results), encoding="utf-8")
    truth_path.write_text(json.dumps(truth), encoding="utf-8")

    report = evaluate_files(results_path, truth_path, tmp_path)

    assert report["aggregate"]["accuracy"] == 1.0
    assert report["fields"]["invoice_number"]["correct"] == 1
    assert report["fields"]["project_name"]["correct"] == 1
    assert report["timing_ms"]["max"] == 100
    assert (tmp_path / "metrics.json").exists()
    assert (tmp_path / "report.md").exists()


def test_metrics_penalizes_values_that_should_be_blank(tmp_path: Path):
    results = [{
        "source_filename": "blank.pdf",
        "fields": {"invoice_category": "增值税专用发票", "tax_amount": "0.00"},
        "status": "needs_confirmation",
        "processing_ms": 10,
    }]
    truth = {
        "blank.pdf": {
            "include_in_accuracy": True,
            "fields": {"invoice_category": "增值税专用发票", "tax_amount": None},
        }
    }
    results_path = tmp_path / "results.json"
    truth_path = tmp_path / "truth.json"
    results_path.write_text(json.dumps(results), encoding="utf-8")
    truth_path.write_text(json.dumps(truth), encoding="utf-8")

    report = evaluate_files(results_path, truth_path, tmp_path)

    assert report["aggregate"]["accuracy"] == 0.5
    assert report["fields"]["tax_amount"]["expected_blank"] == 1
    assert report["fields"]["tax_amount"]["false_positive"] == 1


def test_metrics_penalizes_invented_project_name_that_should_be_blank(tmp_path: Path):
    results = [{
        "source_filename": "blank.pdf",
        "fields": {"project_name": "*虚构*项目"},
        "status": "needs_confirmation",
        "processing_ms": 10,
    }]
    truth = {
        "blank.pdf": {
            "include_in_accuracy": True,
            "fields": {"project_name": None},
        }
    }
    results_path = tmp_path / "results.json"
    truth_path = tmp_path / "truth.json"
    results_path.write_text(json.dumps(results, ensure_ascii=False), encoding="utf-8")
    truth_path.write_text(json.dumps(truth, ensure_ascii=False), encoding="utf-8")

    report = evaluate_files(results_path, truth_path, tmp_path)

    assert report["aggregate"]["accuracy"] == 0.0
    assert report["fields"]["project_name"]["expected_blank"] == 1
    assert report["fields"]["project_name"]["false_positive"] == 1
