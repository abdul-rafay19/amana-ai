"""Tools the agents can call. They are plain, testable Python. The LLM decides
WHEN to call them; the numbers inside always come from calc.py / records.py."""
from __future__ import annotations

import time

import calc
import records
from schemas import FIELDS, merge_fields, missing_required, next_question

_FIELD_DOC = {
    "item": "kind of product, e.g. dress, frock, suit",
    "quantity": "number of pieces in the order (integer)",
    "rate_per_piece": "payment in Rs for ONE piece",
    "deadline_days": "days allowed to finish the order",
    "material_expenses": "total Rs she will spend on thread, cloth, etc. Use 0 if she says nothing",
    "estimated_hours": "total hours she expects the whole order to take",
    "payment_terms": "when/how she will be paid, e.g. 'on delivery'",
    "contractor_name": "name of the contractor, if given",
    "other_terms": "any other condition, e.g. deductions mentioned",
    "advance_received": "advance already paid to her in Rs",
}
_TYPES = {"item": "string", "payment_terms": "string", "contractor_name": "string", "other_terms": "string",
          "quantity": "integer", "deadline_days": "integer"}

CHAT_TOOLS = [
    {"type": "function", "function": {
        "name": "record_order_details",
        "description": "Save order details the worker just mentioned. Call it every time she gives any new detail. "
                      "Only include fields she actually stated. Never guess.",
        "parameters": {"type": "object", "properties": {
            f: {"type": _TYPES.get(f, "number"), "description": _FIELD_DOC[f]} for f in FIELDS}}}},
    {"type": "function", "function": {
        "name": "calculate_deal",
        "description": "Run the deterministic calculation (expected payment, earnings after expenses, hourly rate, "
                      "risk flags). Call it only when quantity and rate are known.",
        "parameters": {"type": "object", "properties": {}}}},
]

PAYMENT_TOOLS = [
    {"type": "function", "function": {
        "name": "get_record",
        "description": "Fetch the saved agreement for an order, including its integrity check.",
        "parameters": {"type": "object", "properties": {"order_no": {"type": "string"}}, "required": ["order_no"]}}},
    {"type": "function", "function": {
        "name": "compare_payment",
        "description": "Compare the agreed expected payment with what she received. advance_paid is money paid to her "
                      "earlier (not part of received). agreed_deductions are deductions both sides agreed in advance.",
        "parameters": {"type": "object", "properties": {
            "order_no": {"type": "string"}, "received": {"type": "number"},
            "advance_paid": {"type": "number"}, "agreed_deductions": {"type": "number"},
            "is_partial": {"type": "boolean"}}, "required": ["order_no", "received"]}}},
]


def public_draft(d: dict) -> dict:
    return {k: d.get(k) for k in FIELDS if d.get(k) is not None}


class ToolBox:
    def __init__(self, owner: str, state: dict, emit):
        self.owner, self.state, self.emit = owner, state, emit

    # ---- dispatcher: times each call and writes it to the agent trace ----
    def run(self, agent: str, name: str, args: dict) -> dict:
        t0 = time.time()
        try:
            res = getattr(self, name)(**(args or {}))
            ok = "error" not in res
        except TypeError as e:
            res, ok = {"error": f"bad arguments: {e}"}, False
        except Exception as e:
            res, ok = {"error": str(e)}, False
        self.emit(agent, name, "code", args, res, ok, int((time.time() - t0) * 1000))
        return res

    # ---- Deal Intelligence ----
    def record_order_details(self, **fields) -> dict:
        draft = self.state.setdefault("draft", {})
        _, updated, errors = merge_fields(draft, fields)
        return {"updated": updated, "errors": errors, "draft": public_draft(draft),
                "missing_required": missing_required(draft), "next_question": next_question(draft)}

    def calculate_deal(self) -> dict:
        d = self.state.get("draft", {})
        miss = missing_required(d)
        if miss:
            return {"error": f"missing required fields: {miss}"}
        c = calc.calculate_deal(d["quantity"], d["rate_per_piece"], d.get("material_expenses"), d.get("estimated_hours"))
        flags = calc.analyze_risks(d, c, self.state.get("min_hourly"))
        self.state["calc"], self.state["flags"] = c, flags
        return {"calc": c, "flags": [{"level": f["level"], "code": f["code"]} for f in flags]}

    # ---- Work Record / Payment ----
    def get_record(self, order_no: str) -> dict:
        r = records.latest_record(self.owner, order_no)
        if not r:
            return {"error": f"no record for {order_no}"}
        v = records.verify_record(r)
        self.state["agreement"] = r
        return {"order_no": order_no, "version": r["version"], "hash": r["hash"][:16],
                "integrity_ok": v["ok"], "changed_fields": v["changed_fields"],
                "agreement": {k: r["data"].get(k) for k in
                              ("item", "quantity", "rate_per_piece", "expected_total", "deadline_days", "payment_terms")}}

    def compare_payment(self, order_no: str, received: float, advance_paid: float = 0,
                        agreed_deductions: float = 0, is_partial: bool = False) -> dict:
        r = self.state.get("agreement") or records.latest_record(self.owner, order_no)
        if not r:
            return {"error": f"no record for {order_no}"}
        res = calc.compare_payment(r["data"]["expected_total"], received, advance_paid, agreed_deductions, is_partial)
        self.state["last_compare"] = res
        return res
