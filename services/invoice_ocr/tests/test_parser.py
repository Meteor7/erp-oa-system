from decimal import Decimal

import pytest

from invoice_ocr.models import OCRLine
from invoice_ocr.parser import classify_invoice_text, parse_invoice


def lines(*values: str) -> list[OCRLine]:
    return [OCRLine(text=value, score=0.96, box=(0, i * 20, 500, i * 20 + 18)) for i, value in enumerate(values)]


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("\u7535\u5b50\u53d1\u7968\uff08\u589e\u503c\u7a0e\u4e13\u7528\u53d1\u7968\uff09", "\u589e\u503c\u7a0e\u4e13\u7528\u53d1\u7968"),
        ("\u7535\u5b50\u53d1\u7968\uff08\u666e\u901a\u53d1\u7968\uff09", "\u6570\u7535\u666e\u901a\u53d1\u7968"),
        ("\u94c1\u8def\u7535\u5b50\u5ba2\u7968", "\u94c1\u8def\u7535\u5b50\u5ba2\u7968"),
        ("\u822a\u7a7a\u8fd0\u8f93\u7535\u5b50\u5ba2\u7968\u884c\u7a0b\u5355", "\u822a\u7a7a\u8fd0\u8f93\u7535\u5b50\u5ba2\u7968\u884c\u7a0b\u5355"),
        ("\u5317\u4eac\u5e02\u51fa\u79df\u6c7d\u8f66\u53d1\u7968", "\u51fa\u79df\u6c7d\u8f66\u53d1\u7968"),
        ("\u4e2d\u592e\u975e\u7a0e\u6536\u5165\u7edf\u4e00\u7968\u636e", "\u4e2d\u592e\u975e\u7a0e\u6536\u5165\u7edf\u4e00\u7968\u636e"),
    ],
)
def test_classifies_supported_invoice_titles(title: str, expected: str):
    assert classify_invoice_text(title) == expected


def test_parses_six_fields_from_vat_invoice():
    outcome = parse_invoice(lines(
        "\u7535\u5b50\u53d1\u7968\uff08\u666e\u901a\u53d1\u7968\uff09",
        "\u5f00\u7968\u65e5\u671f\uff1a2026\u5e7407\u670814\u65e5",
        "\u53d1\u7968\u53f7\u7801\uff1a00123456789012345678",
        "\u5408\u8ba1\uff08\u4e0d\u542b\u7a0e\uff09 \uffe5100.00",
        "\u5408\u8ba1\u7a0e\u989d \uffe56.00",
        "\u4ef7\u7a0e\u5408\u8ba1\uff08\u5c0f\u5199\uff09 \uffe5106.00",
    ))

    assert outcome.fields.invoice_category == "电子发票（普通发票）"
    assert outcome.fields.invoice_category_normalized == "数电普通发票"
    assert outcome.fields.issue_date.isoformat() == "2026-07-14"
    assert outcome.fields.invoice_number == "00123456789012345678"
    assert outcome.fields.amount_before_tax == Decimal("100.00")
    assert outcome.fields.tax_amount == Decimal("6.00")
    assert outcome.fields.total_amount == Decimal("106.00")
    assert "amount_arithmetic_mismatch" not in outcome.warnings


def test_applies_confirmable_zero_tax_rule_only_to_clear_non_tax_category():
    outcome = parse_invoice(lines(
        "\u5317\u4eac\u5e02\u51fa\u79df\u6c7d\u8f66\u53d1\u7968",
        "\u53d1\u7968\u53f7\u7801 00123456",
        "\u65e5\u671f 2026-07-14",
        "\u91d1\u989d \uffe538.50",
    ))

    assert outcome.fields.amount_before_tax == Decimal("38.50")
    assert outcome.fields.tax_amount == Decimal("0.00")
    assert outcome.fields.total_amount == Decimal("38.50")
    assert "zero_tax_rule_applied" in outcome.warnings


def test_taxable_invoice_with_missing_tax_is_left_blank():
    outcome = parse_invoice(lines(
        "\u589e\u503c\u7a0e\u666e\u901a\u53d1\u7968",
        "\u53d1\u7968\u53f7\u7801 12345678",
        "\u5f00\u7968\u65e5\u671f 2026-07-14",
        "\u4ef7\u7a0e\u5408\u8ba1 \uffe5100.00",
    ))

    assert outcome.fields.tax_amount is None
    assert outcome.fields.amount_before_tax is None
    assert "tax_amount_missing_for_taxable_invoice" in outcome.warnings


def test_flags_arithmetic_mismatch():
    outcome = parse_invoice(lines(
        "\u589e\u503c\u7a0e\u4e13\u7528\u53d1\u7968",
        "\u53d1\u7968\u53f7\u7801 12345678",
        "\u5f00\u7968\u65e5\u671f 2026-07-14",
        "\u5408\u8ba1\uff08\u4e0d\u542b\u7a0e\uff09 \uffe5100.00",
        "\u7a0e\u989d \uffe56.00",
        "\u4ef7\u7a0e\u5408\u8ba1 \uffe5107.00",
    ))

    assert "amount_arithmetic_mismatch" in outcome.warnings


def test_uses_layout_columns_and_small_total_for_vat_amounts():
    sample = [
        OCRLine(text="\u7535\u5b50\u53d1\u7968\uff08\u666e\u901a\u53d1\u7968\uff09", score=0.99, box=(100, 20, 500, 50)),
        OCRLine(text="\u5f00\u7968\u65e5\u671f\uff1a2026\u5e7407\u670814\u65e5", score=0.99, box=(800, 100, 1100, 130)),
        OCRLine(text="\u53d1\u7968\u53f7\u7801\uff1a26322000005753891281", score=0.99, box=(800, 60, 1200, 90)),
        OCRLine(text="\u91d1\u989d", score=0.99, box=(811, 300, 870, 322)),
        OCRLine(text="\u7a0e\u989d", score=0.99, box=(1097, 298, 1161, 323)),
        OCRLine(text="\uffe535.62", score=0.99, box=(809, 518, 872, 540)),
        OCRLine(text="\uffe50.36", score=0.99, box=(1111, 515, 1166, 540)),
        OCRLine(text="(\u5c0f\u5199)\uffe535.98", score=0.99, box=(818, 551, 952, 581)),
    ]
    outcome = parse_invoice(sample)
    assert outcome.fields.amount_before_tax == Decimal("35.62")
    assert outcome.fields.tax_amount == Decimal("0.36")
    assert outcome.fields.total_amount == Decimal("35.98")


def test_invoice_number_does_not_swallow_digits_from_next_ocr_line():
    outcome = parse_invoice(lines(
        "\u4e0a\u6d77\u901a\u7528\u5b9a\u989d\u53d1\u7968",
        "\u53d1\u7968\u53f7\u780107476982",
        "747",
        "\u53d1\u7968\u4ee3\u7801131002127766",
    ))
    assert outcome.fields.invoice_number == "07476982"


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("深圳增值税电子普通发票\n*经营租赁*通行费", "增值税普通发票"),
        ("湖北增值电普通发票", "增值税普通发票"),
        ("示例企业004有限公司\n车费发票", "出租汽车发票"),
        ("示例企业033有限公司机打发票", "通行费发票"),
        ("票据代码00010125\n票据号码0024783449\n金额合计（小写）2100.00", "中央非税收入统一票据"),
    ],
)
def test_classifies_real_sample_title_variants(title: str, expected: str):
    assert classify_invoice_text(title) == expected


def test_parses_non_tax_ticket_number_and_standalone_short_date():
    outcome = parse_invoice(lines(
        "中央非税收入统一票据（电子）",
        "票据号码：0024783449",
        "25-12-25",
        "金额合计（小写）：109.00",
    ))
    assert outcome.fields.invoice_number == "0024783449"
    assert outcome.fields.issue_date is None


def test_layout_stops_tax_column_before_small_total_row():
    sample = [
        OCRLine(text="深圳增值税电子普通发票", score=0.99, box=(100, 20, 500, 50)),
        OCRLine(text="开票日期：2026年04月26日", score=0.99, box=(800, 100, 1100, 130)),
        OCRLine(text="发票号码：09182569", score=0.99, box=(800, 60, 1200, 90)),
        OCRLine(text="金额", score=0.99, box=(860, 308, 920, 330)),
        OCRLine(text="税额", score=0.99, box=(1074, 307, 1134, 330)),
        OCRLine(text="¥1.94", score=0.99, box=(897, 526, 958, 548)),
        OCRLine(text="¥0.06", score=0.99, box=(1119, 525, 1180, 548)),
        OCRLine(text="（小写）", score=0.99, box=(885, 561, 960, 584)),
        OCRLine(text="¥2.00", score=0.99, box=(1114, 571, 1180, 594)),
    ]
    outcome = parse_invoice(sample)
    assert outcome.fields.invoice_category == "深圳增值税电子普通发票"
    assert outcome.fields.invoice_category_normalized == "增值税普通发票"
    assert outcome.fields.amount_before_tax == Decimal("1.94")
    assert outcome.fields.tax_amount == Decimal("0.06")
    assert outcome.fields.total_amount == Decimal("2.00")


def test_taxi_layout_amount_and_zero_tax_rule():
    sample = [
        OCRLine(text="示例企业004有限公司", score=0.96, box=(400, 100, 1000, 150)),
        OCRLine(text="车费发票", score=0.96, box=(500, 200, 850, 250)),
        OCRLine(text="发票号码：00089918", score=0.96, box=(500, 400, 900, 450)),
        OCRLine(text="25-12-25", score=0.96, box=(700, 1500, 900, 1550)),
        OCRLine(text="金额", score=0.96, box=(521, 1906, 611, 1955)),
        OCRLine(text="109.00元", score=0.96, box=(763, 1888, 979, 1938)),
        OCRLine(text="0.00元", score=0.96, box=(763, 1800, 950, 1850)),
    ]
    outcome = parse_invoice(sample)
    assert outcome.fields.invoice_category == "车费发票"
    assert outcome.fields.invoice_category_normalized == "出租汽车发票"
    assert outcome.fields.issue_date.isoformat() == "2025-12-25"
    assert outcome.fields.total_amount == Decimal("109.00")
    assert outcome.fields.amount_before_tax == Decimal("109.00")
    assert outcome.fields.tax_amount == Decimal("0.00")


def test_fixed_invoice_uppercase_denomination():
    outcome = parse_invoice(lines(
        "上海通用定额发票",
        "发票号码07476982",
        "伍拾元",
    ))
    assert outcome.fields.total_amount == Decimal("50.00")
    assert outcome.fields.amount_before_tax == Decimal("50.00")
    assert outcome.fields.tax_amount == Decimal("0.00")


def test_airline_columns_and_derived_before_tax_amount():
    sample = [
        OCRLine(text="航空运输电子客票行程单", score=0.99, box=(200, 20, 800, 60)),
        OCRLine(text="开票日期：2026-07-01", score=0.99, box=(850, 80, 1150, 110)),
        OCRLine(text="电子客票号：26448784211047907041", score=0.99, box=(800, 120, 1250, 150)),
        OCRLine(text="票价", score=0.99, box=(329, 471, 400, 500)),
        OCRLine(text="增值税税额", score=0.99, box=(671, 471, 800, 500)),
        OCRLine(text="合计", score=0.99, box=(1043, 471, 1084, 500)),
        OCRLine(text="CNY431.19", score=0.99, box=(350, 496, 456, 516)),
        OCRLine(text="CNY51.20", score=0.99, box=(700, 496, 795, 516)),
        OCRLine(text="CNY670.00", score=0.99, box=(1103, 495, 1207, 516)),
    ]
    outcome = parse_invoice(sample)
    assert outcome.fields.tax_amount == Decimal("51.20")
    assert outcome.fields.total_amount == Decimal("670.00")
    assert outcome.fields.amount_before_tax == Decimal("618.80")
    assert "amount_before_tax_derived_from_total_minus_tax" in outcome.warnings


def test_rail_ticket_price_is_total_but_tax_stays_blank():
    outcome = parse_invoice(lines(
        "铁路电子客票",
        "乘车日期：2026-01-04",
        "电子客票号：26449165860000056191",
        "票价：￥874.00",
    ))
    assert outcome.fields.issue_date is None
    assert outcome.fields.total_amount == Decimal("874.00")
    assert outcome.fields.tax_amount is None
    assert outcome.fields.amount_before_tax is None


def test_rail_ticket_with_single_amount_column_uses_total_only():
    sample = [
        OCRLine(text="铁路电子客票", score=0.99, box=(200, 20, 800, 60)),
        OCRLine(text="电子客票号：26449165860000056191", score=0.99, box=(700, 120, 1180, 150)),
        OCRLine(text="金额", score=0.99, box=(860, 300, 930, 330)),
        OCRLine(text="￥874.00", score=0.99, box=(860, 360, 960, 390)),
    ]

    outcome = parse_invoice(sample)

    assert outcome.fields.total_amount == Decimal("874.00")
    assert outcome.fields.amount_before_tax is None
    assert outcome.fields.tax_amount is None


def test_layout_ignores_zero_width_embedded_text_boxes():
    sample = [
        OCRLine(text="深圳增值税电子普通发票", score=0.99, box=(100, 20, 500, 50)),
        OCRLine(text="金额", score=0.99, box=(860, 308, 923, 334)),
        OCRLine(text="税额", score=0.99, box=(1074, 307, 1137, 333)),
        OCRLine(text="价税合计(大写)", score=0.99, box=(0, 360, 0, 378)),
        OCRLine(text="¥1.94", score=0.99, box=(897, 526, 943, 544)),
        OCRLine(text="¥0.06", score=0.99, box=(1119, 525, 1165, 544)),
        OCRLine(text="(小写)", score=0.99, box=(885, 561, 953, 590)),
        OCRLine(text="¥2.00", score=0.99, box=(1114, 571, 1161, 590)),
    ]
    outcome = parse_invoice(sample)
    assert outcome.fields.amount_before_tax == Decimal("1.94")
    assert outcome.fields.tax_amount == Decimal("0.06")


def test_does_not_coerce_letter_o_into_invoice_number():
    outcome = parse_invoice(lines("增值税普通发票", "发票号码：12O45678"))
    assert outcome.fields.invoice_number is None


def test_paper_toll_row_amount_uses_confirmable_zero_tax_rule():
    sample = [
        OCRLine(text="湖南省车辆通行费发票", score=0.99, box=(213, 210, 834, 287)),
        OCRLine(text="01117014", score=0.99, box=(214, 427, 431, 482)),
        OCRLine(text="10", score=0.99, box=(668, 683, 718, 727)),
        OCRLine(text="金额：", score=0.99, box=(530, 724, 677, 785)),
    ]
    outcome = parse_invoice(sample)
    assert outcome.fields.total_amount == Decimal("10.00")
    assert outcome.fields.amount_before_tax == Decimal("10.00")
    assert outcome.fields.tax_amount == Decimal("0.00")


def test_paper_toll_inline_zero_amount_is_not_treated_as_missing():
    outcome = parse_invoice(lines(
        "示例企业033有限公司机打发票",
        "发票号码08227885",
        "金额：00",
    ))
    assert outcome.fields.total_amount == Decimal("0.00")
    assert outcome.fields.amount_before_tax == Decimal("0.00")
    assert outcome.fields.tax_amount == Decimal("0.00")


def test_parse_preserves_complete_invoice_title_and_internal_category():
    outcome = parse_invoice(lines(
        "电子发票（普通发票）",
        "开票日期：2026年07月14日",
        "发票号码：26322000005753891281",
    ))
    assert outcome.fields.invoice_category == "电子发票（普通发票）"
    assert outcome.fields.invoice_category_normalized == "数电普通发票"


def test_content_without_invoice_title_does_not_invent_category():
    outcome = parse_invoice(lines(
        "开票日期：2026年07月14日",
        "发票号码：12345678",
        "*文具*印章",
    ))
    assert outcome.fields.invoice_category is None
    assert outcome.fields.invoice_category_normalized is None


def test_extracts_project_name_with_stars_from_its_table_column():
    sample = [
        OCRLine(text="电子发票（普通发票）", score=0.99, box=(480, 60, 850, 100)),
        OCRLine(text="项目名称", score=0.99, box=(210, 310, 315, 340)),
        OCRLine(text="规格型号", score=0.99, box=(365, 310, 455, 340)),
        OCRLine(text="*文具*印章", score=0.99, box=(210, 350, 330, 380)),
        OCRLine(text="合计", score=0.99, box=(260, 530, 330, 560)),
    ]
    outcome = parse_invoice(sample)
    assert outcome.fields.project_names == ["*文具*印章"]
    assert outcome.fields.project_name == "*文具*印章"


def test_preserves_multiple_projects_in_reading_order_and_deduplicates_ocr_repeat():
    sample = [
        OCRLine(text="增值税普通发票", score=0.99, box=(300, 20, 600, 60)),
        OCRLine(text="项目名称", score=0.99, box=(100, 200, 230, 230)),
        OCRLine(text="规格型号", score=0.99, box=(400, 200, 500, 230)),
        OCRLine(text="*办公用品*纸张", score=0.99, box=(100, 250, 300, 280)),
        OCRLine(text="*文具*印章", score=0.99, box=(100, 300, 260, 330)),
        OCRLine(text="*文具*印章", score=0.95, box=(101, 301, 261, 331)),
        OCRLine(text="价税合计", score=0.99, box=(100, 400, 230, 430)),
    ]
    outcome = parse_invoice(sample)
    assert outcome.fields.project_names == ["*办公用品*纸张", "*文具*印章"]
    assert outcome.fields.project_name == "*办公用品*纸张；*文具*印章"


def test_project_extraction_stops_before_total_and_ignores_adjacent_columns():
    sample = [
        OCRLine(text="增值税普通发票", score=0.99, box=(300, 20, 600, 60)),
        OCRLine(text="项目名称", score=0.99, box=(100, 200, 230, 230)),
        OCRLine(text="规格型号", score=0.99, box=(400, 200, 500, 230)),
        OCRLine(text="金额", score=0.99, box=(800, 200, 860, 230)),
        OCRLine(text="*服务*咨询费", score=0.99, box=(100, 250, 300, 280)),
        OCRLine(text="标准版", score=0.99, box=(410, 250, 500, 280)),
        OCRLine(text="¥100.00", score=0.99, box=(800, 250, 900, 280)),
        OCRLine(text="合计", score=0.99, box=(100, 350, 200, 380)),
        OCRLine(text="不应读取", score=0.99, box=(100, 390, 250, 420)),
    ]
    outcome = parse_invoice(sample)
    assert outcome.fields.project_names == ["*服务*咨询费"]


def test_extracts_inline_project_value_and_leaves_absent_project_blank():
    inline = parse_invoice(lines(
        "电子发票（普通发票）",
        "项目名称：*服务*咨询费",
    ))
    absent = parse_invoice(lines(
        "铁路电子客票",
        "票价：¥874.00",
    ))
    assert inline.fields.project_names == ["*服务*咨询费"]
    assert absent.fields.project_names == []
    assert absent.fields.project_name is None


def test_internal_category_does_not_fill_missing_raw_title():
    outcome = parse_invoice(lines(
        "*经营租赁*通行费",
        "发票号码：12345678",
    ))
    assert outcome.fields.invoice_category is None
    assert outcome.fields.invoice_category_normalized == "通行费发票"
    assert "invoice_category_raw_missing" in outcome.warnings


def test_project_extraction_stops_at_split_total_characters():
    sample = [
        OCRLine(text="电子发票（普通发票）", score=0.99, box=(300, 20, 600, 60)),
        OCRLine(text="项目名称", score=0.99, box=(89, 300, 164, 322)),
        OCRLine(text="规格型号", score=0.99, box=(235, 300, 311, 322)),
        OCRLine(text="*文具*印章", score=0.99, box=(23, 317, 117, 340)),
        OCRLine(text="合", score=0.99, box=(113, 521, 137, 544)),
        OCRLine(text="计", score=0.99, box=(203, 520, 227, 543)),
        OCRLine(text="价税合计（大写）", score=0.99, box=(95, 558, 230, 578)),
    ]

    outcome = parse_invoice(sample)

    assert outcome.fields.project_names == ["*文具*印章"]


def test_project_extraction_rejects_text_that_crosses_into_adjacent_column():
    sample = [
        OCRLine(text="湖北增值税电子普通发票", score=0.99, box=(300, 20, 650, 60)),
        OCRLine(text="货物或应税劳务、服务名称", score=0.99, box=(82, 295, 298, 314)),
        OCRLine(text="规格型号", score=0.99, box=(375, 294, 450, 315)),
        OCRLine(text="*经营租赁*通行费", score=0.99, box=(47, 317, 189, 340)),
        OCRLine(text="客车", score=0.99, box=(340, 316, 385, 343)),
        OCRLine(text="合计", score=0.99, box=(138, 509, 240, 537)),
    ]

    outcome = parse_invoice(sample)

    assert outcome.fields.project_names == ["*经营租赁*通行费"]


def test_project_extraction_ignores_vertical_text_starting_above_header():
    sample = [
        OCRLine(text="北京增值税专用发票", score=0.99, box=(330, 24, 545, 52)),
        OCRLine(text="税总函[2014]××号××××公司", score=0.99, box=(54, 172, 71, 397)),
        OCRLine(text="货物或应税劳务、服务名称", score=0.99, box=(97, 196, 246, 210)),
        OCRLine(text="规格型号", score=0.99, box=(281, 192, 341, 212)),
        OCRLine(text="合", score=0.99, box=(125, 335, 144, 353)),
        OCRLine(text="计", score=0.99, box=(196, 336, 215, 354)),
    ]

    outcome = parse_invoice(sample)

    assert outcome.fields.project_names == []


def test_project_extraction_uses_previous_header_boundary_and_amount_total_cutoff():
    sample = [
        OCRLine(text="项目编码", score=0.99, box=(175, 264, 290, 296)),
        OCRLine(text="项目名称", score=0.99, box=(432, 262, 547, 294)),
        OCRLine(text="单位", score=0.99, box=(714, 260, 778, 299)),
        OCRLine(text="检索费", score=0.99, box=(290, 301, 354, 327)),
        OCRLine(text="金额合计（大写）贰仟壹佰元整", score=0.99, box=(188, 630, 554, 661)),
        OCRLine(text="收款务用家知识产权局专利局", score=0.99, box=(170, 923, 664, 974)),
    ]

    outcome = parse_invoice(sample)

    assert outcome.fields.project_names == ["检索费"]


def test_raw_title_is_preserved_even_when_normalized_category_is_unknown():
    outcome = parse_invoice(lines(
        "财政电子票据",
        "开票日期：2026年07月20日",
    ))

    assert outcome.fields.invoice_category == "财政电子票据"
    assert outcome.fields.invoice_category_normalized is None


def test_project_extraction_stops_at_vertically_split_total_characters():
    sample = [
        OCRLine(text="电子发票（普通发票）", score=0.99, box=(300, 20, 600, 60)),
        OCRLine(text="项目名称", score=0.99, box=(100, 200, 230, 230)),
        OCRLine(text="规格型号", score=0.99, box=(400, 200, 500, 230)),
        OCRLine(text="*文具*印章", score=0.99, box=(100, 250, 260, 280)),
        OCRLine(text="合", score=0.99, box=(140, 400, 165, 425)),
        OCRLine(text="计", score=0.99, box=(140, 435, 165, 460)),
        OCRLine(text="不应读取", score=0.99, box=(100, 500, 250, 530)),
    ]

    outcome = parse_invoice(sample)

    assert outcome.fields.project_names == ["*文具*印章"]


def test_project_extraction_ignores_tall_vertical_text_below_header():
    sample = [
        OCRLine(text="项目名称", score=0.99, box=(100, 200, 230, 230)),
        OCRLine(text="规格型号", score=0.99, box=(400, 200, 500, 230)),
        OCRLine(text="竖排印章批注", score=0.99, box=(110, 250, 135, 390)),
        OCRLine(text="合计", score=0.99, box=(100, 450, 230, 480)),
    ]

    outcome = parse_invoice(sample)

    assert outcome.fields.project_names == []


def test_inline_first_project_does_not_hide_following_project_rows():
    sample = [
        OCRLine(text="项目名称：*服务*第一项", score=0.99, box=(100, 200, 330, 230)),
        OCRLine(text="规格型号", score=0.99, box=(400, 200, 500, 230)),
        OCRLine(text="*服务*第二项", score=0.99, box=(100, 250, 300, 280)),
        OCRLine(text="合计", score=0.99, box=(100, 400, 230, 430)),
    ]

    outcome = parse_invoice(sample)

    assert outcome.fields.project_names == ["*服务*第一项", "*服务*第二项"]


def test_inline_numeric_value_is_not_accepted_as_project_name():
    outcome = parse_invoice(lines(
        "电子发票（普通发票）",
        "项目名称：100.00",
    ))

    assert outcome.fields.project_names == []


def test_legitimate_repeated_project_rows_are_preserved():
    sample = [
        OCRLine(text="项目名称", score=0.99, box=(100, 200, 230, 230)),
        OCRLine(text="规格型号", score=0.99, box=(400, 200, 500, 230)),
        OCRLine(text="*服务*咨询费", score=0.99, box=(100, 250, 300, 280)),
        OCRLine(text="*服务*咨询费", score=0.99, box=(100, 310, 300, 340)),
        OCRLine(text="合计", score=0.99, box=(100, 400, 230, 430)),
    ]

    outcome = parse_invoice(sample)

    assert outcome.fields.project_names == ["*服务*咨询费", "*服务*咨询费"]


def test_invoice_title_ignores_business_labels_before_literal_title():
    outcome = parse_invoice(lines(
        "发票抬头：示例企业025有限公司",
        "发票状态：正常",
        "发票备注：测试",
        "财政电子票据",
    ))

    assert outcome.fields.invoice_category == "财政电子票据"


def test_inline_header_without_adjacent_columns_keeps_rows_before_total():
    sample = [
        OCRLine(text="项目名称：*服务*第一项", score=0.99, box=(100, 200, 330, 230)),
        OCRLine(text="*服务*第二项", score=0.99, box=(100, 250, 300, 280)),
        OCRLine(text="合计", score=0.99, box=(100, 400, 230, 430)),
    ]

    outcome = parse_invoice(sample)

    assert outcome.fields.project_names == ["*服务*第一项", "*服务*第二项"]


def test_inline_project_after_total_is_not_included():
    sample = [
        OCRLine(text="项目名称：*服务*第一项", score=0.99, box=(100, 200, 330, 230)),
        OCRLine(text="合计", score=0.99, box=(100, 300, 230, 330)),
        OCRLine(text="项目名称：*服务*不应读取", score=0.99, box=(100, 350, 350, 380)),
    ]

    outcome = parse_invoice(sample)

    assert outcome.fields.project_names == ["*服务*第一项"]


def test_inline_ocr_repeat_is_deduplicated():
    sample = [
        OCRLine(text="项目名称：*服务*第一项", score=0.99, box=(100, 200, 330, 230)),
        OCRLine(text="项目名称：*服务*第一项", score=0.95, box=(103, 203, 333, 233)),
    ]

    outcome = parse_invoice(sample)

    assert outcome.fields.project_names == ["*服务*第一项"]


def test_project_extraction_rejects_moderately_tall_narrow_vertical_text():
    sample = [
        OCRLine(text="项目名称", score=0.99, box=(100, 200, 230, 230)),
        OCRLine(text="规格型号", score=0.99, box=(400, 200, 500, 230)),
        OCRLine(text="竖排批注", score=0.99, box=(110, 250, 130, 335)),
        OCRLine(text="合计", score=0.99, box=(100, 400, 230, 430)),
    ]

    outcome = parse_invoice(sample)

    assert outcome.fields.project_names == []


def test_large_scale_near_duplicate_project_boxes_are_deduplicated():
    sample = [
        OCRLine(text="项目名称", score=0.99, box=(100, 200, 330, 240)),
        OCRLine(text="规格型号", score=0.99, box=(500, 200, 650, 240)),
        OCRLine(text="*服务*咨询费", score=0.99, box=(100, 300, 400, 340)),
        OCRLine(text="*服务*咨询费", score=0.95, box=(108, 308, 408, 348)),
        OCRLine(text="合计", score=0.99, box=(100, 500, 330, 540)),
    ]

    outcome = parse_invoice(sample)

    assert outcome.fields.project_names == ["*服务*咨询费"]

def test_invoice_title_ignores_business_labels_when_ocr_loses_colon():
    outcome = parse_invoice(lines(
        "发票状态 正常",
        "发票抬头 示例企业025有限公司",
        "财政电子票据",
    ))

    assert outcome.fields.invoice_category == "财政电子票据"


def test_inline_header_without_adjacent_columns_rejects_right_side_spec_text():
    sample = [
        OCRLine(text="项目名称：*服务*第一项", score=0.99, box=(100, 200, 330, 230)),
        OCRLine(text="*服务*第二项", score=0.99, box=(100, 250, 300, 280)),
        OCRLine(text="标准版", score=0.99, box=(410, 250, 500, 280)),
        OCRLine(text="合计", score=0.99, box=(100, 400, 230, 430)),
    ]

    outcome = parse_invoice(sample)

    assert outcome.fields.project_names == ["*服务*第一项", "*服务*第二项"]


def test_project_extraction_rejects_vertical_text_just_below_old_height_threshold():
    sample = [
        OCRLine(text="项目名称", score=0.99, box=(100, 200, 230, 230)),
        OCRLine(text="规格型号", score=0.99, box=(400, 200, 500, 230)),
        OCRLine(text="竖排批注", score=0.99, box=(110, 250, 130, 315)),
        OCRLine(text="合计", score=0.99, box=(100, 400, 230, 430)),
    ]

    outcome = parse_invoice(sample)

    assert outcome.fields.project_names == []

def test_invoice_title_ignores_prefixed_business_status_label():
    outcome = parse_invoice(lines(
        "电子发票状态 正常",
        "增值税发票备注 已验收",
        "财政电子票据",
    ))

    assert outcome.fields.invoice_category == "财政电子票据"


def test_inline_alignment_does_not_expand_with_long_header_value_box():
    sample = [
        OCRLine(text="项目名称：*服务*第一项", score=0.99, box=(100, 200, 430, 230)),
        OCRLine(text="*服务*第二项", score=0.99, box=(100, 250, 300, 280)),
        OCRLine(text="标准版", score=0.99, box=(340, 250, 420, 280)),
        OCRLine(text="合计", score=0.99, box=(100, 400, 230, 430)),
    ]

    outcome = parse_invoice(sample)

    assert outcome.fields.project_names == ["*服务*第一项", "*服务*第二项"]


@pytest.mark.parametrize("header_height", [30, 40, 60])
def test_vertical_project_filter_is_independent_of_header_height(header_height: int):
    sample = [
        OCRLine(text="项目名称", score=0.99, box=(100, 200, 230, 200 + header_height)),
        OCRLine(text="规格型号", score=0.99, box=(400, 200, 500, 200 + header_height)),
        OCRLine(text="竖排批注", score=0.99, box=(110, 280, 130, 345)),
        OCRLine(text="合计", score=0.99, box=(100, 450, 230, 480)),
    ]

    outcome = parse_invoice(sample)

    assert outcome.fields.project_names == []

def test_invoice_title_prefers_complete_classifiable_title_over_top_fragment():
    sample = [
        OCRLine(text="打发票", score=0.996, box=(608, 159, 827, 211)),
        OCRLine(text="湖南省车辆通行费发票", score=0.975, box=(213, 210, 834, 287)),
        OCRLine(text="发票专用章", score=0.999, box=(718, 893, 821, 936)),
    ]

    outcome = parse_invoice(sample)

    assert outcome.fields.invoice_category == "湖南省车辆通行费发票"
    assert outcome.fields.invoice_category_normalized == "通行费发票"