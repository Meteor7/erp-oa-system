from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import median
from typing import Any

FIELDS = ("invoice_category", "project_name", "issue_date", "invoice_number", "amount_before_tax", "tax_amount", "total_amount")


def _normalize(field: str, value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if field in {"amount_before_tax", "tax_amount", "total_amount"} and text:
        try:
            return f"{float(text):.2f}"
        except ValueError:
            return text
    return "".join(text.split()).upper()


def evaluate_files(results_path: Path, truth_path: Path, output_root: Path) -> dict:
    results = json.loads(results_path.read_text(encoding="utf-8"))
    truth = json.loads(truth_path.read_text(encoding="utf-8"))
    by_name = {item["source_filename"]: item for item in results}
    field_metrics = {
        field: {"correct": 0, "expected": 0, "expected_blank": 0, "false_positive": 0, "missing": 0, "incorrect": 0, "accuracy": None}
        for field in FIELDS
    }
    included_files = 0
    for filename, expected_record in truth.items():
        if not expected_record.get("include_in_accuracy", True):
            continue
        included_files += 1
        actual_fields = by_name.get(filename, {}).get("fields", {})
        expected_fields = expected_record.get("fields", {})
        for field in FIELDS:
            if field not in expected_fields:
                continue
            expected_value = _normalize(field, expected_fields[field])
            actual_value = _normalize(field, actual_fields.get(field))
            metric = field_metrics[field]
            metric["expected"] += 1
            if not expected_value:
                metric["expected_blank"] += 1
            if actual_value == expected_value:
                metric["correct"] += 1
            elif not expected_value and actual_value:
                metric["false_positive"] += 1
            elif expected_value and not actual_value:
                metric["missing"] += 1
            else:
                metric["incorrect"] += 1
    total_correct = total_expected = 0
    for metric in field_metrics.values():
        total_correct += metric["correct"]
        total_expected += metric["expected"]
        if metric["expected"]:
            metric["accuracy"] = round(metric["correct"] / metric["expected"], 4)
    timings = sorted(int(item.get("processing_ms", 0)) for item in results)
    report = {
        "files": {"recognized": len(results), "included_in_accuracy": included_files},
        "aggregate": {
            "correct": total_correct,
            "expected": total_expected,
            "accuracy": round(total_correct / total_expected, 4) if total_expected else None,
            "false_positive": sum(metric["false_positive"] for metric in field_metrics.values()),
            "missing": sum(metric["missing"] for metric in field_metrics.values()),
            "incorrect": sum(metric["incorrect"] for metric in field_metrics.values()),
        },
        "fields": field_metrics,
        "timing_ms": {"median": int(median(timings)) if timings else 0, "max": max(timings, default=0)},
        "status_counts": {status: sum(item.get("status") == status for item in results) for status in ("needs_confirmation", "duplicate", "failed")},
    }
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "metrics.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    rows = [
        "# Invoice OCR POC Metrics", "", f"- Included files: {included_files}",
        f"- Aggregate accuracy: {report['aggregate']['accuracy']}",
        f"- False positives: {report['aggregate']['false_positive']}",
        f"- Missing: {report['aggregate']['missing']}",
        f"- Median processing ms: {report['timing_ms']['median']}",
        f"- Max processing ms: {report['timing_ms']['max']}", "",
        "| Field | Correct | Expected | Blank expected | False positive | Missing | Accuracy |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for field in FIELDS:
        metric = field_metrics[field]
        rows.append(f"| {field} | {metric['correct']} | {metric['expected']} | {metric['expected_blank']} | {metric['false_positive']} | {metric['missing']} | {metric['accuracy']} |")
    (output_root / "report.md").write_text("\n".join(rows) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate invoice OCR results")
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--truth", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--min-accuracy", type=float, default=0.95)
    args = parser.parse_args()
    if not 0.0 <= args.min_accuracy <= 1.0:
        parser.error("--min-accuracy must be between 0 and 1")
    report = evaluate_files(args.results, args.truth, args.output)
    print(json.dumps(report, ensure_ascii=False))
    accuracy = report["aggregate"]["accuracy"]
    return 1 if accuracy is None or accuracy < args.min_accuracy else 0


if __name__ == "__main__":
    raise SystemExit(main())
