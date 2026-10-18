"""Pydantic schemas: every LLM output is validated here before it is used."""
from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field, ValidationError, field_validator


class OrderDraft(BaseModel):
    item: Optional[str] = Field(None, max_length=60)
    quantity: Optional[int] = Field(None, gt=0, le=1_000_000)
    rate_per_piece: Optional[float] = Field(None, gt=0, le=10_000_000)
    deadline_days: Optional[int] = Field(None, ge=1, le=365)
    material_expenses: Optional[float] = Field(None, ge=0, le=100_000_000)
    estimated_hours: Optional[float] = Field(None, gt=0, le=10_000)
    payment_terms: Optional[str] = Field(None, max_length=200)
    contractor_name: Optional[str] = Field(None, max_length=80)
    other_terms: Optional[str] = Field(None, max_length=300)
    advance_received: Optional[float] = Field(None, ge=0, le=100_000_000)

    @field_validator("item", "payment_terms", "contractor_name", "other_terms")
    @classmethod
    def _strip(cls, v):
        if v is None:
            return v
        v = " ".join(str(v).split())
        return v or None


FIELDS = list(OrderDraft.model_fields.keys())
REQUIRED = ("quantity", "rate_per_piece")
ASK_ORDER = ["quantity", "rate_per_piece", "material_expenses", "estimated_hours",
             "deadline_days", "payment_terms"]


def merge_fields(draft: dict, new: dict) -> tuple[dict, list[str], dict]:
    """Validate each new field on its own and merge the good ones into draft.
    Returns (draft, updated_fields, errors)."""
    updated, errors = [], {}
    for k, v in (new or {}).items():
        if k not in FIELDS or v is None or v == "":
            continue
        try:
            clean = OrderDraft.model_validate({k: v}).model_dump()[k]
        except ValidationError as e:
            errors[k] = e.errors()[0]["msg"]
            continue
        if clean is not None:
            if draft.get(k) != clean:
                updated.append(k)
            draft[k] = clean
            if k in draft.get("_skipped", []):
                draft["_skipped"].remove(k)
    return draft, updated, errors


def missing_required(draft: dict) -> list[str]:
    return [f for f in REQUIRED if draft.get(f) is None]


def next_question(draft: dict) -> str | None:
    skipped = draft.get("_skipped", [])
    for f in ASK_ORDER:
        if draft.get(f) is None and f not in skipped:
            return f
    return None


def clean_order(draft: dict) -> dict:
    return {k: draft.get(k) for k in FIELDS}
