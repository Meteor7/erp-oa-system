from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, computed_field, field_serializer

RecognitionStatus = Literal["queued", "processing", "needs_confirmation", "duplicate", "failed"]


class OCRLine(BaseModel):
    text: str
    score: float = Field(ge=0.0, le=1.0)
    box: tuple[int, int, int, int]


class InvoiceFields(BaseModel):
    invoice_category: str | None = None
    invoice_category_normalized: str | None = None
    project_names: list[str] = Field(default_factory=list)
    issue_date: date | None = None
    invoice_number: str | None = None
    invoice_code: str | None = None
    amount_before_tax: Decimal | None = None
    tax_amount: Decimal | None = None
    total_amount: Decimal | None = None

    @computed_field
    @property
    def project_name(self) -> str | None:
        return "；".join(self.project_names) or None

    @field_serializer("amount_before_tax", "tax_amount", "total_amount", when_used="json")
    def serialize_money(self, value: Decimal | None) -> str | None:
        return format(value, ".2f") if value is not None else None


class ParseOutcome(BaseModel):
    fields: InvoiceFields = Field(default_factory=InvoiceFields)
    field_confidence: dict[str, float] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class DuplicateMatch(BaseModel):
    is_duplicate: bool = False
    reason: Literal["exact_file", "business_key", "possible_business_key"] | None = None
    matched_record_id: str | None = None


class RecognitionResult(BaseModel):
    record_id: str | None = None
    source_filename: str
    file_sha256: str
    fields: InvoiceFields = Field(default_factory=InvoiceFields)
    field_confidence: dict[str, float] = Field(default_factory=dict)
    status: RecognitionStatus
    duplicate: DuplicateMatch = Field(default_factory=DuplicateMatch)
    warnings: list[str] = Field(default_factory=list)
    processing_ms: int = Field(ge=0)
    error_code: str | None = None
    error_message: str | None = None
    ocr_lines: list[OCRLine] = Field(default_factory=list)
