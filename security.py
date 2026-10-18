"""Shared-Phone Safe Mode helpers. A PIN alone cannot guarantee privacy on a
shared device; this module covers PIN storage, lockout and notification masking."""
from __future__ import annotations

import re
import time

import bcrypt

import db

MAX_ATTEMPTS = 5
LOCKOUT_SECONDS = 30
PIN_RE = re.compile(r"^\d{4}$")


def valid_pin(pin: str) -> bool:
    return bool(PIN_RE.match(pin or ""))


def set_pin(owner: str, pin: str):
    if not valid_pin(pin):
        raise ValueError("PIN must be exactly 4 digits")
    h = bcrypt.hashpw(pin.encode(), bcrypt.gensalt(rounds=10)).decode()
    db.set_owner_field(owner, "pin_hash", h)


def clear_pin(owner: str):
    db.set_owner_field(owner, "pin_hash", None)


def has_pin(owner: str) -> bool:
    r = db.get_owner(owner)
    return bool(r and r["pin_hash"])


def check_pin(owner: str, pin: str) -> bool:
    r = db.get_owner(owner)
    if not r or not r["pin_hash"] or not valid_pin(pin):
        return False
    try:
        return bcrypt.checkpw(pin.encode(), r["pin_hash"].encode())
    except ValueError:
        return False


def lock_seconds(owner: str) -> int:
    r = db.get_owner(owner)
    return int(r["lock_seconds"] or 60) if r else 60


def is_idle(last_active: float, seconds: int, now: float | None = None) -> bool:
    return ((now or time.time()) - last_active) >= seconds


def register_failure(attempts: int, now: float | None = None) -> tuple[int, float]:
    """Returns (new_attempts, locked_until_epoch or 0)."""
    attempts += 1
    if attempts >= MAX_ATTEMPTS:
        return 0, (now or time.time()) + LOCKOUT_SECONDS
    return attempts, 0.0


def safe_notification(kind: str = "update", lang: str = "en") -> dict:
    """Notification text never contains order numbers, amounts or names."""
    text = {"en": ("Amana", "You have a new update. Open with your PIN."),
            "ur": ("امانہ", "آپ کے لیے نیا پیغام ہے۔ اپنے PIN سے کھولیں۔")}[lang if lang in ("en", "ur") else "en"]
    return {"title": text[0], "body": text[1]}


def unsafe_notification_example(order_no="AM-2610-001", short=1500) -> dict:
    return {"title": "Amana", "body": f"Order {order_no}: payment short by Rs {short:,}"}
