"""Deterministic financial logic. The LLM never does arithmetic: every number
shown to the worker comes from the functions in this file."""
from __future__ import annotations

import math
import re
from decimal import Decimal, ROUND_HALF_UP


def D(x) -> Decimal:
    if isinstance(x, Decimal):
        return x
    if isinstance(x, bool) or x is None:
        raise ValueError("number expected")
    return Decimal(str(x))


def _out(d: Decimal):
    d = d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return int(d) if d == d.to_integral_value() else float(d)


def fmt_rs(x) -> str:
    if x is None:
        return "-"
    v = float(x)
    s = f"{v:,.0f}" if abs(v - round(v)) < 1e-9 else f"{v:,.2f}"
    return f"Rs {s}"


def expected_total(quantity, rate):
    q, r = D(quantity), D(rate)
    if q <= 0 or r <= 0:
        raise ValueError("quantity and rate must be greater than zero")
    return _out(q * r)


def calculate_deal(quantity, rate, expenses=None, hours=None) -> dict:
    """Expected payment, estimated earnings after direct expenses, hourly rate."""
    total = D(expected_total(quantity, rate))
    out = {
        "quantity": int(D(quantity)),
        "rate_per_piece": _out(D(rate)),
        "expected_total": _out(total),
        "material_expenses": None,
        "net_after_expenses": None,
        "estimated_hours": None,
        "hourly_net": None,
        "hourly_gross": None,
        "net_per_piece": None,
        "expense_share_pct": None,
    }
    if hours is not None:
        h = D(hours)
        if h <= 0:
            raise ValueError("hours must be greater than zero")
        out["estimated_hours"] = _out(h)
        out["hourly_gross"] = _out(total / h)
    if expenses is not None:
        e = D(expenses)
        if e < 0:
            raise ValueError("expenses cannot be negative")
        net = total - e
        out["material_expenses"] = _out(e)
        out["net_after_expenses"] = _out(net)
        out["net_per_piece"] = _out(net / D(quantity))
        out["expense_share_pct"] = _out(e / total * 100)
        if hours is not None:
            out["hourly_net"] = _out(net / D(hours))
    return out


def required_rate_for_target(quantity, expenses, hours, target_hourly, current_rate) -> dict:
    """Rate per piece needed so that (total - expenses) / hours reaches her own target."""
    q, h, t = D(quantity), D(hours), D(target_hourly)
    e = D(expenses or 0)
    if q <= 0 or h <= 0 or t <= 0:
        raise ValueError("quantity, hours and target must be greater than zero")
    needed = (t * h + e) / q
    rate = D(math.ceil(needed))
    cur = D(current_rate)
    new_total = rate * q
    return {
        "target_hourly": _out(t),
        "current_rate": _out(cur),
        "suggested_rate": _out(rate),
        "new_total": _out(new_total),
        "new_net": _out(new_total - e),
        "new_hourly_net": _out((new_total - e) / h),
        "increase_pct": _out((rate - cur) / cur * 100) if cur > 0 else None,
        "already_meets_target": cur >= rate,
    }


def compare_payment(expected, received, advance_paid=0, agreed_deductions=0, is_partial=False) -> dict:
    """advance_paid = money already paid to her earlier (not part of `received`).
    agreed_deductions = deductions both sides agreed to in advance."""
    ex, rc = D(expected), D(received)
    ad, dd = D(advance_paid or 0), D(agreed_deductions or 0)
    if ex <= 0:
        raise ValueError("expected amount must be greater than zero")
    if rc < 0 or ad < 0 or dd < 0:
        raise ValueError("amounts cannot be negative")
    difference = ex - rc
    explained = ad + dd
    unexplained = difference - explained
    total_in_hand = rc + ad
    if difference == 0:
        status = "match"
    elif unexplained == 0:
        status = "explained"
    elif unexplained < 0:
        status = "over"
    elif is_partial:
        status = "partial_pending"
    else:
        status = "short"
    return {
        "expected": _out(ex),
        "received": _out(rc),
        "advance_paid": _out(ad),
        "agreed_deductions": _out(dd),
        "difference": _out(difference),
        "explained": _out(explained),
        "unexplained": _out(unexplained),
        "total_received_incl_advance": _out(total_in_hand),
        "is_partial": bool(is_partial),
        "status": status,
    }


_VAGUE_DEDUCTION = re.compile(r"(deduct|katt?|cutting|penalt|fine|کٹوتی|جرمانہ)", re.I)


def analyze_risks(order: dict, calc: dict | None, min_hourly=None) -> list[dict]:
    """Rule-based flags. Each has level (red/amber/green), en and ur text."""
    flags = []

    def add(level, code, en, ur):
        flags.append({"level": level, "code": code, "en": en, "ur": ur})

    if not order.get("payment_terms"):
        add("amber", "no_payment_terms",
            "No payment date or method was agreed. Ask when and how you will be paid.",
            "ادائیگی کی تاریخ یا طریقہ طے نہیں ہوا۔ پوچھ لیں کہ پیسے کب اور کیسے ملیں گے۔")
    if order.get("material_expenses") is None:
        add("amber", "no_expenses",
            "Material and other costs are not entered, so your real earning may be lower than shown.",
            "مٹیریل اور دوسرے خرچے درج نہیں ہوئے، اس لیے اصل کمائی دکھائی گئی رقم سے کم ہو سکتی ہے۔")
    if order.get("estimated_hours") is None:
        add("amber", "no_hours",
            "Working hours are missing, so the hourly earning cannot be shown.",
            "کام کے گھنٹے معلوم نہیں، اس لیے فی گھنٹہ کمائی نہیں دکھائی جا سکتی۔")
    if order.get("deadline_days") is None:
        add("amber", "no_deadline", "No deadline was agreed.", "ڈیڈ لائن طے نہیں ہوئی۔")

    pct = calc.get("expense_share_pct") if calc else None
    if pct is not None and pct >= 30:
        lvl = "red" if pct >= 50 else "amber"
        add(lvl, "high_expense",
            f"Costs take {pct:g}% of the total payment.",
            f"خرچے کل ادائیگی کا {pct:g}% کھا جاتے ہیں۔")

    hrs, days = order.get("estimated_hours"), order.get("deadline_days")
    if hrs and days:
        per_day = round(float(hrs) / float(days), 1)
        if per_day > 8:
            add("red" if per_day > 12 else "amber", "tight_deadline",
                f"This needs about {per_day:g} hours of work every day to finish on time.",
                f"وقت پر مکمل کرنے کے لیے روزانہ تقریباً {per_day:g} گھنٹے کام کرنا ہوگا۔")

    hourly = calc.get("hourly_net") if calc else None
    if min_hourly and hourly is not None and hourly < float(min_hourly):
        add("amber", "below_target",
            f"Estimated earning is {fmt_rs(hourly)}/hour, below your own target of {fmt_rs(min_hourly)}/hour.",
            f"اندازاً کمائی {fmt_rs(hourly)} فی گھنٹہ ہے، جو آپ کے اپنے ہدف {fmt_rs(min_hourly)} سے کم ہے۔")

    terms = " ".join(str(order.get(k) or "") for k in ("other_terms", "payment_terms"))
    if _VAGUE_DEDUCTION.search(terms) and not re.search(r"\d", terms):
        add("amber", "vague_deductions",
            "Deductions are mentioned but no amount or reason is written down.",
            "کٹوتی کا ذکر ہے لیکن رقم یا وجہ طے نہیں ہوئی۔")

    if not flags:
        add("green", "all_clear",
            "Nothing unclear found in the details you gave.",
            "آپ کی بتائی ہوئی تفصیلات میں کوئی مبہم بات نہیں ملی۔")
    return flags
