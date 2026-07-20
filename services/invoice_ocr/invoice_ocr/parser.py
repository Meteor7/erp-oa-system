from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
import re

from invoice_ocr.models import InvoiceFields, OCRLine, ParseOutcome

CATEGORY_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("航空运输电子客票行程单", ("航空运输电子客票行程单", "航空运输电子客票")),
    ("铁路电子客票", ("铁路电子客票", "铁路电子发票")),
    ("出租汽车发票", ("出租汽车发票", "出租车发票", "车费发票")),
    ("中央非税收入统一票据", ("中央非税收入统一票据", "非税收入统一票据")),
    ("定额发票", ("定额发票",)),
    ("增值税专用发票", ("增值税专用发票", "增值税专票", "专用发票")),
    ("数电普通发票", ("电子发票（普通发票）", "数电普通发票")),
    (
        "增值税普通发票",
        (
            "增值税电子普通发票",
            "增值税普通发票",
            "增值电普通发票",
            "电子普通发票",
        ),
    ),
    ("通行费发票", ("通行费", "收费公路通行费", "车辆通行费", "高速公路")),
)

NON_TAX_CATEGORIES = {
    "出租汽车发票",
    "定额发票",
    "中央非税收入统一票据",
}
TAXABLE_CATEGORIES = {
    "增值税专用发票",
    "数电普通发票",
    "增值税普通发票",
    "通行费发票",
    "铁路电子客票",
    "航空运输电子客票行程单",
}
MONEY = r"[-+]?\d[\d,]*(?:\.\d{1,2})?"
CURRENCY = r"(?:[￥¥]|CNY|RMB)?"


TITLE_WORDS = ("发票", "票据", "客票", "行程单")
PROJECT_HEADERS = (
    "项目名称",
    "货物或应税劳务、服务名称",
    "货物或应税劳务名称",
)
PROJECT_STOP_MARKERS = ("合计", "价税合计", "金额合计")
PROJECT_LEFT_HEADERS = ("项目编码",)
PROJECT_ADJACENT_HEADERS = ("规格型号", "单位", "数量", "单价", "金额", "税率/征收率", "税额")


def _compact(text: str) -> str:
    compact_lines = [re.sub(r"[ \t\r\f\v]+", "", line) for line in text.splitlines()]
    return "\n".join(compact_lines)


def classify_invoice_text(text: str) -> str | None:
    compact = _compact(text)
    for category, markers in CATEGORY_RULES:
        if any(marker in compact for marker in markers):
            return category
    if all(marker in compact for marker in ("票据代码", "票据号码", "金额合计")):
        return "中央非税收入统一票据"
    return None


def _match(patterns: tuple[str, ...], text: str) -> str | None:
    for pattern in patterns:
        found = re.search(pattern, text, flags=re.IGNORECASE)
        if found:
            return found.group(1)
    return None


def _parse_date(text: str, category: str | None) -> date | None:
    labeled = re.search(
        r"(?:开票日期|填开日期)[:：]?"
        r"(20\d{2})[年./-]?(\d{1,2})[月./-]?(\d{1,2})日?",
        text,
    )
    if labeled:
        try:
            return date(int(labeled.group(1)), int(labeled.group(2)), int(labeled.group(3)))
        except ValueError:
            return None
    if category not in {"出租汽车发票", "通行费发票"}:
        return None
    for raw_line in text.splitlines():
        line = _compact(raw_line)
        standalone = re.fullmatch(
            r"(?:日期(?:/时间)?[:：]?)?(20\d{2}|\d{2})[-/.](\d{1,2})[-/.](\d{1,2})"
            r"(?:\s+\d{1,2}:\d{2}(?::\d{2})?)?",
            line,
        )
        if not standalone:
            continue
        year = int(standalone.group(1))
        if year < 100:
            year += 2000
        try:
            return date(year, int(standalone.group(2)), int(standalone.group(3)))
        except ValueError:
            continue
    return None


def _parse_decimal(value: str | None) -> Decimal | None:
    if not value:
        return None
    try:
        return Decimal(value.replace(",", "")).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None


def _money(patterns: tuple[str, ...], text: str) -> Decimal | None:
    return _parse_decimal(_match(patterns, text))


def _line_money(text: str) -> Decimal | None:
    compact = _compact(text)
    match = re.fullmatch(rf"{CURRENCY}({MONEY})(?:元)?", compact, flags=re.IGNORECASE)
    return _parse_decimal(match.group(1)) if match else None


def _label_matches(text: str, marker: str) -> bool:
    if marker == "税额":
        return text == marker or text.endswith(marker)
    return text == marker


def _column_money(lines: list[OCRLine], marker: str) -> Decimal | None:
    labels = [line for line in lines if _label_matches(_compact(line.text), marker)]
    if not labels:
        return None
    label = labels[0]
    label_center = (label.box[0] + label.box[2]) / 2
    cutoff_rows = [
        line.box[1]
        for line in lines
        if line.box[2] > line.box[0] and line.box[1] > label.box[3] and any(word in _compact(line.text) for word in ("小写", "价税合计"))
    ]
    cutoff = min(cutoff_rows) if cutoff_rows else float("inf")
    candidates: list[tuple[int, Decimal]] = []
    for line in lines:
        value = _line_money(line.text)
        if value is None or line.box[2] <= line.box[0] or (line.box[1] + line.box[3]) / 2 <= (label.box[1] + label.box[3]) / 2 or line.box[1] >= cutoff:
            continue
        center = (line.box[0] + line.box[2]) / 2
        tolerance = max(140.0, (label.box[2] - label.box[0]) * 2.0)
        if abs(center - label_center) <= tolerance:
            candidates.append((line.box[1], value))
    return max(candidates, key=lambda item: item[0])[1] if candidates else None


def _row_money(lines: list[OCRLine], marker: str) -> Decimal | None:
    labels = [line for line in lines if _compact(line.text).rstrip(":：") == marker]
    candidates: list[tuple[float, Decimal]] = []
    for label in labels:
        label_y = (label.box[1] + label.box[3]) / 2
        for line in lines:
            value = _line_money(line.text)
            if value is None or line.box[0] < label.box[0]:
                continue
            line_y = (line.box[1] + line.box[3]) / 2
            distance = abs(line_y - label_y)
            if distance <= 70:
                candidates.append((distance, value))
    return min(candidates, key=lambda item: (item[0], -item[1]))[1] if candidates else None


def _small_total(lines: list[OCRLine]) -> Decimal | None:
    for label in lines:
        compact = _compact(label.text)
        if not any(marker in compact for marker in ("小写", "价税合计")):
            continue
        inline = re.search(rf"{CURRENCY}({MONEY})(?:元)?$", compact, flags=re.IGNORECASE)
        if inline:
            return _parse_decimal(inline.group(1))
        label_y = (label.box[1] + label.box[3]) / 2
        candidates: list[tuple[float, Decimal]] = []
        for line in lines:
            value = _line_money(line.text)
            if value is None or line.box[0] < label.box[0]:
                continue
            line_y = (line.box[1] + line.box[3]) / 2
            distance = abs(line_y - label_y)
            if distance <= 70:
                candidates.append((distance, value))
        if candidates:
            return min(candidates, key=lambda item: item[0])[1]
    return None


def _chinese_amount(text: str) -> Decimal | None:
    match = re.search(r"([零壹贰叁肆伍陆柒捌玖拾佰仟万]+)元", text)
    if not match:
        return None
    digits = {"零": 0, "壹": 1, "贰": 2, "叁": 3, "肆": 4, "伍": 5, "陆": 6, "柒": 7, "捌": 8, "玖": 9}
    units = {"拾": 10, "佰": 100, "仟": 1000}
    total = section = current = 0
    for char in match.group(1):
        if char in digits:
            current = digits[char]
        elif char in units:
            section += (current or 1) * units[char]
            current = 0
        elif char == "万":
            total += (section + current) * 10000
            section = current = 0
    return Decimal(total + section + current).quantize(Decimal("0.00"))


def _standalone_digits(lines: list[OCRLine], length: int) -> str | None:
    for line in lines:
        compact = _compact(line.text)
        if re.fullmatch(rf"\d{{{length}}}", compact):
            return compact
    return None


def extract_invoice_title(lines: list[OCRLine]) -> str | None:
    excluded_markers = (
        "发票号码",
        "发票代码",
        "票据号码",
        "票据代码",
        "开票日期",
        "发票专用章",
        "发票监",
        "发票联",
        "发票查询",
        "发票开具",
    )
    label_prefix = re.compile(
        r"(?:发票|票据)(?:抬头|状态|备注|类型|种类|名称|信息|查验|查询|代码|号码|日期|开具|监制)(?:[:：]|\s)*"
    )
    candidates: list[str] = []
    ordered = sorted(lines, key=lambda line: (line.box[1], line.box[0]))
    for line in ordered:
        candidate = line.text.strip()
        compact = _compact(candidate)
        if not candidate or not any(word in candidate for word in TITLE_WORDS):
            continue
        if compact in TITLE_WORDS or any(marker in compact for marker in excluded_markers):
            continue
        if label_prefix.search(compact):
            continue
        if compact.startswith(("（", "(")) and classify_invoice_text(candidate) is None:
            continue
        candidates.append(candidate)
    for candidate in candidates:
        if classify_invoice_text(candidate) is not None:
            return candidate
    return candidates[0] if candidates else None

def _valid_project_value(value: str) -> bool:
    compact = _compact(value).rstrip("：:")
    excluded = (
        set(PROJECT_HEADERS)
        | set(PROJECT_STOP_MARKERS)
        | set(PROJECT_LEFT_HEADERS)
        | set(PROJECT_ADJACENT_HEADERS)
        | {"合", "计"}
    )
    if not compact or compact in excluded:
        return False
    return re.fullmatch(
        r"(?:[¥￥]|CNY|RMB)?[-+]?\d[\d,]*(?:\.\d{1,2})?(?:元|%)?",
        compact,
        flags=re.IGNORECASE,
    ) is None


def _same_ocr_box(first: OCRLine, second: OCRLine) -> bool:
    first_width = max(1, first.box[2] - first.box[0])
    second_width = max(1, second.box[2] - second.box[0])
    first_height = max(1, first.box[3] - first.box[1])
    second_height = max(1, second.box[3] - second.box[1])
    scale_dimension = min(max(first_width, second_width), max(first_height, second_height))
    tolerance = max(5, int(round(scale_dimension * 0.25)))
    return max(abs(a - b) for a, b in zip(first.box, second.box)) <= tolerance


def _dedupe_project_entries(entries: list[tuple[int, int, str, OCRLine]]) -> list[str]:
    accepted: list[tuple[int, int, str, OCRLine]] = []
    for candidate in sorted(entries, key=lambda item: (item[0], item[1])):
        if any(
            candidate[2] == previous[2] and _same_ocr_box(candidate[3], previous[3])
            for previous in accepted
        ):
            continue
        accepted.append(candidate)
    return [entry[2] for entry in accepted]


def extract_project_names(lines: list[OCRLine]) -> list[str]:
    inline_entries: list[tuple[int, int, str, OCRLine]] = []
    inline_header_lines: list[OCRLine] = []
    for line in lines:
        raw = line.text.strip()
        for header_name in PROJECT_HEADERS:
            match = re.match(rf"^{re.escape(header_name)}(?:[：:]|\s)+(.*\S)\s*$", raw)
            if not match:
                continue
            inline_header_lines.append(line)
            value = match.group(1).strip()
            if _valid_project_value(value):
                inline_entries.append((line.box[1], line.box[0], value, line))
            break

    header_lines = [
        line for line in lines
        if line.box[2] > line.box[0]
        and (
            _compact(line.text).rstrip("：:") in PROJECT_HEADERS
            or line in inline_header_lines
        )
    ]
    if not header_lines:
        return _dedupe_project_entries(inline_entries)

    header = min(header_lines, key=lambda line: (line.box[1], line.box[0]))
    compact_header = _compact(header.text).rstrip("：:")
    header_text = next(
        (name for name in PROJECT_HEADERS if compact_header.startswith(name)),
        compact_header,
    )
    header_center_y = (header.box[1] + header.box[3]) / 2
    header_height = max(1, header.box[3] - header.box[1])
    same_row_headers = [
        line for line in lines
        if line.box[0] > header.box[2]
        and line.box[2] > line.box[0]
        and abs(((line.box[1] + line.box[3]) / 2) - header_center_y) <= max(40, header_height)
        and _compact(line.text).rstrip("：:") in PROJECT_ADJACENT_HEADERS
    ]
    right_boundary = (
        min(line.box[0] for line in same_row_headers)
        if same_row_headers
        else header.box[2] + max(250, (header.box[2] - header.box[0]) * 3)
    )
    same_row_left_headers = [
        line for line in lines
        if line.box[2] <= header.box[0]
        and line.box[2] > line.box[0]
        and abs(((line.box[1] + line.box[3]) / 2) - header_center_y) <= max(40, header_height)
        and _compact(line.text).rstrip("：:") in PROJECT_LEFT_HEADERS
    ]
    left_boundary = (
        max(line.box[2] for line in same_row_left_headers)
        if same_row_left_headers
        else max(0, header.box[0] - max(20, (header.box[2] - header.box[0]) // 4))
    )
    cutoff_rows = [
        line.box[1]
        for line in lines
        if line.box[1] > header.box[3]
        and any(
            compact == marker or compact.startswith(marker)
            for compact in (_compact(line.text).rstrip("：:"),)
            for marker in PROJECT_STOP_MARKERS
        )
    ]
    total_first = [line for line in lines if _compact(line.text) == "合"]
    total_second = [line for line in lines if _compact(line.text) == "计"]
    for first in total_first:
        for second in total_second:
            first_center_x = (first.box[0] + first.box[2]) / 2
            first_center_y = (first.box[1] + first.box[3]) / 2
            second_center_x = (second.box[0] + second.box[2]) / 2
            second_center_y = (second.box[1] + second.box[3]) / 2
            row_tolerance = max(40, first.box[3] - first.box[1], second.box[3] - second.box[1])
            column_tolerance = max(40, first.box[2] - first.box[0], second.box[2] - second.box[0])
            horizontal = (
                second.box[0] >= first.box[2]
                and second.box[0] - first.box[2] <= 200
                and abs(first_center_y - second_center_y) <= row_tolerance
            )
            vertical = (
                second.box[1] >= first.box[3]
                and second.box[1] - first.box[3] <= 80
                and abs(first_center_x - second_center_x) <= column_tolerance
            )
            if first.box[1] > header.box[3] and (horizontal or vertical):
                cutoff_rows.append(min(first.box[1], second.box[1]))
    cutoff = min(cutoff_rows) if cutoff_rows else float("inf")

    candidates = [
        entry for entry in inline_entries
        if entry[3].box[1] >= header.box[1] and entry[3].box[1] < cutoff
    ]
    if header in inline_header_lines and not same_row_headers and cutoff == float("inf"):
        return _dedupe_project_entries(candidates)

    for line in lines:
        if line is header or line in inline_header_lines or line.box[2] <= line.box[0]:
            continue
        center_y = (line.box[1] + line.box[3]) / 2
        center_x = (line.box[0] + line.box[2]) / 2
        line_width = max(1, line.box[2] - line.box[0])
        line_height = line.box[3] - line.box[1]
        if center_y <= header_center_y or line.box[1] < header.box[1] or line.box[1] >= cutoff:
            continue
        if not same_row_headers and abs(line.box[0] - header.box[0]) > max(80, header_height * 4):
            continue
        if line_height > line_width * 1.5:
            continue
        if center_x < left_boundary or center_x >= right_boundary or line.box[2] > right_boundary:
            continue
        raw = line.text.strip()
        if _compact(raw).rstrip("：:") == header_text or not _valid_project_value(raw):
            continue
        candidates.append((line.box[1], line.box[0], raw, line))

    return _dedupe_project_entries(candidates)

def parse_invoice(lines: list[OCRLine]) -> ParseOutcome:
    raw_text = "\n".join(line.text for line in lines)
    text = _compact(raw_text)
    category = classify_invoice_text(text)
    invoice_category = extract_invoice_title(lines)
    project_names = extract_project_names(lines)
    issue_date = _parse_date(text, category)
    invoice_number = _match(
        (
            r"(?:发票号码|电子客票号|票据号码|票号|车票号码)[:：]?(\d{8,20})",
        ),
        text,
    )
    invoice_code = _match((r"(?:发票代码|票据代码)[:：]?(\d{8,12})",), text)
    if invoice_number is None and category in {"出租汽车发票", "定额发票", "通行费发票"}:
        invoice_number = _standalone_digits(lines, 8)
    if invoice_code is None and category in {"出租汽车发票", "定额发票", "通行费发票"}:
        invoice_code = _standalone_digits(lines, 12)

    amount_before_tax = _money(
        (
            rf"(?:合计[（(]不含税[）)]|不含税金额|税前金额|金额小计)[:：]?{CURRENCY}({MONEY})",
        ),
        text,
    )
    if amount_before_tax is None:
        amount_before_tax = _column_money(lines, "金额")

    tax_amount = _money(
        (rf"(?:合计税额|税额)[:：]?{CURRENCY}({MONEY})",),
        text,
    )
    if tax_amount is None:
        tax_amount = _column_money(lines, "税额")

    total_amount = _money(
        (
            rf"(?:价税合计(?:[（(]小写[）)])?|[（(]小写[）)]|合计金额|金额合计|实付金额)[:：]?{CURRENCY}({MONEY})",
        ),
        text,
    )
    if total_amount is None:
        total_amount = _small_total(lines)

    warnings: list[str] = []
    if category is not None and invoice_category is None:
        warnings.append("invoice_category_raw_missing")

    if category == "航空运输电子客票行程单":
        if tax_amount is None:
            tax_amount = _column_money(lines, "税额")
        if total_amount is None:
            total_amount = _column_money(lines, "合计")
        if total_amount is not None and tax_amount is not None:
            amount_before_tax = (total_amount - tax_amount).quantize(Decimal("0.01"))
            warnings.append("amount_before_tax_derived_from_total_minus_tax")
    elif category == "铁路电子客票" and total_amount is None:
        total_amount = _money((rf"票价[:：]?{CURRENCY}({MONEY})",), text)

    if category in NON_TAX_CATEGORIES:
        if total_amount is None:
            total_amount = _money(
                (rf"(?:金额|票价|实收金额)[:：]?{CURRENCY}({MONEY})",),
                text,
            )
        if total_amount is None:
            total_amount = _row_money(lines, "金额")
        if total_amount is None and category == "定额发票":
            total_amount = _chinese_amount(text)
        if total_amount is not None and tax_amount is None:
            tax_amount = Decimal("0.00")
            amount_before_tax = total_amount
            warnings.append("zero_tax_rule_applied")
    elif category == "通行费发票":
        if total_amount is None:
            total_amount = _money((rf"金额[:：]?{CURRENCY}({MONEY})",), text)
        if total_amount is None:
            total_amount = _row_money(lines, "金额")
        if total_amount is not None and tax_amount is None and "税额" not in text:
            tax_amount = Decimal("0.00")
            amount_before_tax = total_amount
            warnings.append("zero_tax_rule_applied")
        elif tax_amount is None:
            warnings.append("tax_amount_missing_for_taxable_invoice")
    elif category in TAXABLE_CATEGORIES and "不征税" in text and total_amount is not None and tax_amount is None:
        tax_amount = Decimal("0.00")
        if amount_before_tax is None:
            amount_before_tax = total_amount
        warnings.append("zero_tax_rule_applied")
    elif category in TAXABLE_CATEGORIES and tax_amount is None:
        warnings.append("tax_amount_missing_for_taxable_invoice")

    if amount_before_tax is not None and tax_amount is not None and total_amount is not None:
        if abs((amount_before_tax + tax_amount) - total_amount) > Decimal("0.02"):
            warnings.append("amount_arithmetic_mismatch")

    fields = InvoiceFields(
        invoice_category=invoice_category,
        invoice_category_normalized=category,
        project_names=project_names,
        issue_date=issue_date,
        invoice_number=invoice_number,
        invoice_code=invoice_code,
        amount_before_tax=amount_before_tax,
        tax_amount=tax_amount,
        total_amount=total_amount,
    )
    required_values = (
        fields.invoice_category,
        fields.issue_date,
        fields.invoice_number,
        fields.amount_before_tax,
        fields.tax_amount,
        fields.total_amount,
    )
    if any(value is None for value in required_values):
        warnings.append("required_fields_missing")

    field_confidence: dict[str, float] = {}
    return ParseOutcome(fields=fields, field_confidence=field_confidence, warnings=warnings)
