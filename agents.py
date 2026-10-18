"""Orchestrator + the three agents. The LLM understands language, chooses which
tool to call and writes plain-language explanations. Code does the maths and
the record keeping. If no LLM is reachable, a rule-based path keeps the demo alive."""
from __future__ import annotations

import json
import re
import time

import calc
import llm
import offline
import records
from calc import fmt_rs
from pydantic import BaseModel, Field, ValidationError
from schemas import clean_order, missing_required, next_question
from tools import CHAT_TOOLS, PAYMENT_TOOLS, ToolBox, public_draft

BAD_WORDS = ("چور", "دھوکہ", "دھوکا", "فراڈ", "جھوٹ", "بے ایمان", "cheat", "fraud", "thief", "liar", "scam", "steal",
             "dhoka", "chor", "jhoot")
_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def _nums(s: str) -> set:
    return {float(x) for x in re.findall(r"\d+(?:\.\d+)?", str(s).translate(_DIGITS).replace(",", ""))}


def safe_text(text: str, facts) -> bool:
    """AI-written text is used only if every number in it appears in the facts and it has no accusing word."""
    low = text.lower()
    return _nums(text) <= _nums(json.dumps(facts, ensure_ascii=False, default=str)) and not any(w in low for w in BAD_WORDS)


def _guard(trace, agent: str, text, facts):
    """Return the text if it passes safe_text, else None (caller falls back to its fixed template)."""
    if not text:
        return None
    if safe_text(text, facts):
        return text
    trace.add(agent, "safety_check", "check", {"text": text[:80]}, "rejected (unknown number or accusing word): fixed template used", False, 0)
    return None


LANG_NAME = {"en": "English", "roman": "Roman Urdu (Urdu written in English letters)", "ur": "Urdu (Urdu script)"}


class Trace:
    """Every model call and tool call lands here and is shown live in the UI."""

    def __init__(self, store: list, callback=None):
        self.store, self.callback = store, callback

    def add(self, agent, tool, kind, args=None, result=None, ok=True, ms=0):
        self.store.append({"n": len(self.store) + 1, "agent": agent, "tool": tool, "kind": kind,
                           "args": args or {}, "result": result, "ok": ok, "ms": ms})
        if self.callback:
            self.callback(self.store)


def _llm_call(trace: Trace, agent: str, messages, **kw):
    t0 = time.time()
    resp = llm.chat(messages, **kw)
    trace.add(agent, "model_call", "ai", {"provider": resp["provider"], "model": resp["model"],
              "tool_calls": [c["name"] for c in resp["tool_calls"]]}, None, True, resp["ms"] or int((time.time() - t0) * 1000))
    return resp


# ------------------------------------------------------------------ Orchestrator
class Orchestrator:
    def __init__(self, owner: str, state: dict, trace: Trace):
        self.owner, self.state, self.trace = owner, state, trace
        self.tools = ToolBox(owner, state, trace.add)

    def _system(self, lang: str) -> str:
        d = self.state.get("draft", {})
        return (
            "You are Amana, a warm, calm assistant for a woman who does piecework from home in Pakistan "
            "(stitching, embroidery, handicrafts). She talks about an order a contractor offered her.\n"
            f"Reply in {LANG_NAME[lang]}, matching how she writes. Use very simple words and 1-3 short sentences.\n"
            "Rules:\n"
            "- Whenever she gives order details, call record_order_details with ONLY what she stated.\n"
            "- NEVER do arithmetic or state totals, profit or hourly rates yourself. Numbers come from tools.\n"
            "- After recording, ask exactly ONE question: the tool's next_question (one short sentence). "
            "If next_question is null and quantity and rate are known, tell her she can press the 'Show me the numbers' button.\n"
            "- If a tool returns errors for a field, politely ask her to confirm that number.\n"
            "- Never promise profit, never accuse the contractor, never give legal advice.\n"
            f"Current saved details: {json.dumps(public_draft(d), ensure_ascii=False)}\n"
            f"Question she is answering now: {self.state.get('asked_field')}"
        )

    def handle(self, text: str, asked_field: str | None = None) -> str:
        text = offline.normalize(text)
        lang = offline.detect_lang(text)
        self.state["chat_lang"] = lang
        self.state["asked_field"] = asked_field
        if llm.available():
            try:
                return self._handle_llm(text, lang, asked_field)
            except llm.LLMUnavailable as e:
                self.trace.add("Orchestrator", "fallback", "code", {"reason": str(e)}, "using rule-based parser", False, 0)
        return self._handle_offline(text, lang, asked_field)

    # -- offline path
    def _handle_offline(self, text, lang, asked_field):
        fields = offline.extract_offline(text, asked_field)
        res = self.tools.run("Deal Intelligence", "record_order_details", fields)
        d = self.state["draft"]
        return offline.reply_offline(d, res["updated"], res["errors"], res["next_question"], lang,
                                     not missing_required(d))

    # -- LLM tool loop
    def _handle_llm(self, text, lang, asked_field):
        hist = [{"role": "user" if m["role"] == "user" else "assistant", "content": m["text"]}
                for m in self.state.get("chat", [])[-8:]]
        messages = [{"role": "system", "content": self._system(lang)}] + hist + [{"role": "user", "content": text}]
        called_record = False
        for _ in range(5):
            resp = _llm_call(self.trace, "Orchestrator", messages, tools=CHAT_TOOLS)
            if not resp["tool_calls"]:
                if not called_record:  # safety net: the model skipped the tool
                    fields = offline.extract_offline(text, asked_field)
                    if fields:
                        self.tools.run("Deal Intelligence", "record_order_details", fields)
                        return resp["content"] or self._handle_offline(text, lang, None)
                return resp["content"] or self._handle_offline(text, lang, asked_field)
            messages.append(llm.assistant_message(resp))
            for c in resp["tool_calls"]:
                if c["name"] == "record_order_details":
                    called_record = True
                    res = self.tools.run("Deal Intelligence", c["name"], c["arguments"])
                elif c["name"] == "calculate_deal":
                    res = self.tools.run("Deal Intelligence", c["name"], {})
                else:
                    res = {"error": "unknown tool"}
                messages.append({"role": "tool", "tool_call_id": c["id"], "content": json.dumps(res, ensure_ascii=False)})
        return self._handle_offline(text, lang, asked_field)


# ------------------------------------------------------------------ Deal Intelligence
def _simple_llm(trace, agent, system, user, max_tokens=400):
    try:
        r = _llm_call(trace, agent, [{"role": "system", "content": system}, {"role": "user", "content": user}],
                      temperature=0.3, max_tokens=max_tokens)
        return r["content"] or None
    except llm.LLMUnavailable:
        return None


class DealAgent:
    def __init__(self, owner, state, trace):
        self.owner, self.state, self.trace = owner, state, trace
        self.tools = ToolBox(owner, state, trace.add)

    def evaluate(self) -> dict:
        res = self.tools.run("Deal Intelligence", "calculate_deal", {})
        return res

    def explain(self, lang: str) -> str:
        c, flags = self.state["calc"], self.state["flags"]
        facts = {"expected_total": c["expected_total"], "net_after_expenses": c["net_after_expenses"],
                 "hourly_net": c["hourly_net"], "flags": [f["en"] for f in flags if f["level"] != "green"]}
        txt = _simple_llm(self.trace, "Deal Intelligence",
                          f"You explain a piecework offer to a home-based woman worker in {LANG_NAME[lang]}. "
                          "Use ONLY the numbers given, never add or change numbers. 2-3 very short sentences. "
                          "Say these are estimates from her own figures, not guaranteed profit. Mention the most important flag if any.",
                          json.dumps(facts, ensure_ascii=False))
        txt = _guard(self.trace, "Deal Intelligence", txt,
                     {"calc": c, "draft": public_draft(self.state["draft"]), "flags": facts["flags"]})
        return txt or self._template(c, flags, lang)

    @staticmethod
    def _template(c, flags, lang):
        n = len([f for f in flags if f["level"] != "green"])
        hr = c["hourly_net"]
        if lang == "ur":
            s = f"کل ادائیگی {fmt_rs(c['expected_total'])} بنتی ہے۔"
            if c["net_after_expenses"] is not None:
                s += f" خرچے کے بعد {fmt_rs(c['net_after_expenses'])} بچتے ہیں۔"
            if hr is not None:
                s += f" یعنی تقریباً {fmt_rs(hr)} فی گھنٹہ۔"
            return s + f" یہ آپ کے بتائے ہوئے اعداد پر اندازہ ہے، پکی کمائی نہیں۔ دیکھنے والی باتیں: {n}۔"
        if lang == "roman":
            s = f"Kul payment {fmt_rs(c['expected_total'])} banti hai."
            if c["net_after_expenses"] is not None:
                s += f" Kharche ke baad {fmt_rs(c['net_after_expenses'])} bachte hain."
            if hr is not None:
                s += f" Yaani taqreeban {fmt_rs(hr)} per ghanta."
            return s + f" Yeh aap ke bataye hue figures par andaza hai, pakki kamai nahi. Dekhne wali baatein: {n}."
        s = f"The total payment is {fmt_rs(c['expected_total'])}."
        if c["net_after_expenses"] is not None:
            s += f" After costs, about {fmt_rs(c['net_after_expenses'])} is left."
        if hr is not None:
            s += f" That is roughly {fmt_rs(hr)} per hour."
        return s + f" These are estimates from your own figures, not guaranteed profit. Things to check: {n}."

    def counteroffer(self, target_hourly: float, lang: str) -> dict:
        d = self.state["draft"]
        if not d.get("estimated_hours"):
            return {"error": "hours missing"}
        t0 = time.time()
        res = calc.required_rate_for_target(d["quantity"], d.get("material_expenses") or 0,
                                            d["estimated_hours"], target_hourly, d["rate_per_piece"])
        self.trace.add("Deal Intelligence", "required_rate_for_target", "code",
                       {"target_hourly": target_hourly}, res, True, int((time.time() - t0) * 1000))
        facts = {"item": d.get("item") or "pieces", "quantity": d["quantity"], "current_rate": res["current_rate"],
                 "suggested_rate": res["suggested_rate"], "hours": d["estimated_hours"],
                 "expenses": d.get("material_expenses") or 0}
        msg = _simple_llm(self.trace, "Deal Intelligence",
                          f"Write a short, polite WhatsApp message in {LANG_NAME[lang]} from a woman home-worker to her contractor "
                          "asking to do the order at the suggested rate. Use ONLY the given numbers. Also ask to confirm the deadline and "
                          "payment date. No threats, no accusations. Max 70 words. Output only the message.",
                          json.dumps(facts, ensure_ascii=False))
        msg = _guard(self.trace, "Deal Intelligence", msg, {"facts": facts, "result": res})
        res["message"] = msg or self._counter_template(facts, lang)
        return res

    @staticmethod
    def _counter_template(f, lang):
        it = f["item"]
        if lang == "ur":
            return (f"السلام علیکم۔ {f['quantity']} {it} کے آرڈر کے لیے میں Rs {f['suggested_rate']:g} فی پیس پر کام کر سکتی ہوں "
                    f"(ابھی Rs {f['current_rate']:g} ہے)، کیونکہ مٹیریل اور تقریباً {f['hours']:g} گھنٹے کا کام ہے۔ "
                    "براہِ مہربانی ڈیڈ لائن اور ادائیگی کی تاریخ بھی طے کر لیں۔ شکریہ۔")
        if lang == "roman":
            return (f"Assalam o Alaikum. {f['quantity']} {it} ke order ke liye main Rs {f['suggested_rate']:g} per piece par kaam kar sakti hoon "
                    f"(abhi Rs {f['current_rate']:g} hai), kyunke material aur taqreeban {f['hours']:g} ghante ka kaam hai. "
                    "Meherbani karke deadline aur payment ki tareekh bhi tay kar lein. Shukriya.")
        return (f"Assalam o Alaikum. For the order of {f['quantity']} {it}, I can do the work at Rs {f['suggested_rate']:g} per piece "
                f"(currently Rs {f['current_rate']:g}), because of the material costs and about {f['hours']:g} hours of work. "
                "Could we also confirm the deadline and the payment date? Thank you.")


# ------------------------------------------------------------------ Work Record
class WorkRecordAgent:
    def __init__(self, owner, state, trace):
        self.owner, self.state, self.trace = owner, state, trace

    def save_confirmed(self, is_sample=False) -> dict:
        """Called ONLY after the woman presses Confirm."""
        d, c = self.state["draft"], self.state["calc"]
        order = clean_order(d)
        data = {**order, "expected_total": c["expected_total"], "net_after_expenses": c["net_after_expenses"],
                "hourly_net": c["hourly_net"]}
        sources = {k: "reported_by_worker" for k, v in order.items() if v is not None}
        sources.update({"expected_total": "calculated", "net_after_expenses": "calculated", "hourly_net": "calculated"})
        data["sources"] = sources
        t0 = time.time()
        rec = records.create_record(self.owner, data, is_sample=is_sample)
        self.trace.add("Work Record", "create_record", "code",
                       {"order_no": rec["order_no"], "version": 1}, {"hash": rec["hash"][:16], "prev": rec["prev_hash"][:16]},
                       True, int((time.time() - t0) * 1000))
        v = records.verify_record(rec)
        self.trace.add("Work Record", "verify_record", "check", {"order_no": rec["order_no"]},
                       {"integrity_ok": v["ok"]}, v["ok"], 1)
        return rec


# ------------------------------------------------------------------ Payment Discrepancy
class Narrative(BaseModel):
    explanation: str = Field(min_length=3, max_length=700)
    missing_info: list[str] = Field(default_factory=list, max_length=5)
    draft_message: str = Field(default="", max_length=900)


T_EXPL = {
    "match": {"en": "The payment matches the agreement. Nothing to follow up.",
              "roman": "Payment agreement ke mutabiq hai. Kisi follow-up ki zaroorat nahi.",
              "ur": "ادائیگی طے شدہ رقم کے مطابق ہے۔ کسی فالو اپ کی ضرورت نہیں۔"},
    "explained": {"en": "The gap of {diff} is fully explained by the advance ({adv}) and agreed deductions ({ded}).",
                  "roman": "{diff} ka farq poori tarah advance ({adv}) aur tay shuda katautiyon ({ded}) se samajh aata hai.",
                  "ur": "{diff} کا فرق پیشگی ({adv}) اور طے شدہ کٹوتیوں ({ded}) سے مکمل طور پر واضح ہے۔"},
    "short": {"en": "You received {rec} against {exp}. {unx} is not explained by any advance or agreed deduction.",
              "roman": "Aap ko {rec} mile jabke tay {exp} tha. {unx} kisi advance ya tay shuda katauti se wazeh nahi hota.",
              "ur": "آپ کو {rec} ملے جبکہ طے شدہ رقم {exp} تھی۔ {unx} کسی پیشگی یا طے شدہ کٹوتی سے واضح نہیں ہوتے۔"},
    "partial_pending": {"en": "This looks like a partial payment. {unx} is still outstanding.",
                        "roman": "Yeh partial payment lagti hai. {unx} abhi baqi hain.",
                        "ur": "یہ جزوی ادائیگی لگتی ہے۔ {unx} ابھی باقی ہیں۔"},
    "over": {"en": "You received {unx} more than the agreed amount. It may be a bonus or a mistake; worth confirming.",
             "roman": "Aap ko tay shuda raqam se {unx} zyada mile. Yeh bonus ya ghalti ho sakti hai; confirm kar lein.",
             "ur": "آپ کو طے شدہ رقم سے {unx} زیادہ ملے۔ یہ بونس یا غلطی ہو سکتی ہے؛ تصدیق کر لیں۔"},
}
T_MISS = {
    "adv": {"en": "Was any advance paid to you earlier for this order?", "roman": "Kya is order ka koi advance pehle mila tha?",
            "ur": "کیا اس آرڈر کی کوئی پیشگی رقم پہلے ملی تھی؟"},
    "ded": {"en": "Was any deduction agreed in advance (for example for faults or transport)?",
            "roman": "Kya koi katauti pehle se tay hui thi (masalan nuqs ya transport)?",
            "ur": "کیا کوئی کٹوتی پہلے سے طے ہوئی تھی (مثلاً نقص یا ٹرانسپورٹ)؟"},
    "part": {"en": "Is more payment still expected for this order?", "roman": "Kya is order ki baqi payment abhi aani hai?",
             "ur": "کیا اس آرڈر کی باقی ادائیگی ابھی آنی ہے؟"},
    "proof": {"en": "Do you have a photo of the order slip or a receipt?", "roman": "Kya order slip ya raseed ki photo hai?",
              "ur": "کیا آرڈر پرچی یا رسید کی تصویر موجود ہے؟"},
}
T_DRAFT = {
    "en": ("Assalam o Alaikum. For order {no} ({q} {it}, Rs {r:g} per piece) the agreed total was {exp}. I have received {rec}, "
           "so there is a difference of {unx}. Could you please let me know the reason for the difference, or when the remaining "
           "payment will be made? Thank you."),
    "roman": ("Assalam o Alaikum. Order {no} ({q} {it}, Rs {r:g} per piece) ka tay shuda total {exp} tha. Mujhe {rec} mile hain, "
              "is liye {unx} ka farq reh gaya hai. Meherbani karke bata dein ke yeh farq kis wajah se hai, ya baqi payment kab tak "
              "mil jayegi. Shukriya."),
    "ur": ("السلام علیکم۔ آرڈر {no} ({q} {it}، Rs {r:g} فی پیس) کا طے شدہ کل {exp} تھا۔ مجھے {rec} ملے ہیں، یوں {unx} کا فرق ہے۔ "
           "مہربانی کرکے بتا دیں کہ یہ فرق کس وجہ سے ہے، یا باقی ادائیگی کب تک ہوگی۔ شکریہ۔"),
}


def _fill(tpl, cmp):
    return tpl.format(diff=fmt_rs(cmp["difference"]), adv=fmt_rs(cmp["advance_paid"]), ded=fmt_rs(cmp["agreed_deductions"]),
                      rec=fmt_rs(cmp["received"]), exp=fmt_rs(cmp["expected"]), unx=fmt_rs(abs(cmp["unexplained"])))


class PaymentAgent:
    def __init__(self, owner, state, trace):
        self.owner, self.state, self.trace = owner, state, trace
        self.tools = ToolBox(owner, state, trace.add)

    def run(self, order_no, received, advance_paid, agreed_deductions, is_partial, note, lang, has_proof=False) -> dict:
        self.state.pop("last_compare", None)
        self.state.pop("agreement", None)
        narrative = None
        if llm.available():
            try:
                narrative = self._llm_loop(order_no, received, advance_paid, agreed_deductions, is_partial, note, lang)
            except llm.LLMUnavailable as e:
                self.trace.add("Payment Discrepancy", "fallback", "code", {"reason": str(e)}, "using rule-based report", False, 0)
        # the numbers always come from deterministic tools, even if the model skipped them
        if "agreement" not in self.state:
            self.tools.run("Payment Discrepancy", "get_record", {"order_no": order_no})
        if "last_compare" not in self.state or self.state["last_compare"]["received"] != calc._out(calc.D(received)):
            self.tools.run("Payment Discrepancy", "compare_payment",
                           {"order_no": order_no, "received": received, "advance_paid": advance_paid,
                            "agreed_deductions": agreed_deductions, "is_partial": is_partial})
        rec = self.state["agreement"]
        integrity = records.verify_record(rec)
        if not integrity["ok"]:  # never build a payment report on a record that changed after saving
            self.trace.add("Payment Discrepancy", "integrity_gate", "check", {"order_no": order_no},
                           {"integrity_ok": False, "changed_fields": integrity["changed_fields"]}, False, 0)
            return {"blocked": True, "integrity": integrity, "order_no": order_no}
        cmp = self.state["last_compare"]
        d = rec["data"]
        missing = self._missing(cmp, advance_paid, agreed_deductions, is_partial, has_proof, lang)
        explanation = T_EXPL[cmp["status"]][lang if lang in T_EXPL["match"] else "en"]
        explanation = _fill(explanation, cmp)
        draft = ""
        if cmp["status"] in ("short", "partial_pending", "over"):
            draft = _fill(T_DRAFT[lang].format(no=order_no, q=d.get("quantity"), it=d.get("item") or "pieces",
                                               r=d.get("rate_per_piece") or 0, exp="{exp}", rec="{rec}", unx="{unx}"), cmp)
        if narrative:  # the model's wording may replace the template wording, never the numbers
            facts = {"comparison": cmp, "order": order_no, "agreement": d}
            explanation = _guard(self.trace, "Payment Discrepancy", narrative.explanation, facts) or explanation
            draft = _guard(self.trace, "Payment Discrepancy", narrative.draft_message, facts) or draft
            missing = [m for m in narrative.missing_info if _guard(self.trace, "Payment Discrepancy", m, facts)] or missing
        return {"comparison": cmp, "explanation": explanation, "missing_info": missing, "draft_message": draft,
                "integrity": integrity, "order_no": order_no, "agreement_hash": rec["hash"], "note": note}

    @staticmethod
    def _missing(cmp, adv, ded, partial, proof, lang):
        L = lang if lang in T_MISS["adv"] else "en"
        out = []
        if cmp["status"] in ("short", "partial_pending"):
            if not adv:
                out.append(T_MISS["adv"][L])
            if not ded:
                out.append(T_MISS["ded"][L])
            if not partial:
                out.append(T_MISS["part"][L])
        if cmp["status"] != "match" and not proof:
            out.append(T_MISS["proof"][L])
        return out

    def _llm_loop(self, order_no, received, advance_paid, agreed_deductions, is_partial, note, lang):
        sys = ("You are the Payment Discrepancy Agent for Amana, helping a home-based woman worker check a payment. "
               "Steps: 1) call get_record, 2) call compare_payment with her numbers, 3) answer. "
               f"Write in {LANG_NAME[lang]}, very simple words. Final answer must be ONLY a JSON object: "
               '{"explanation": "...", "missing_info": ["question 1", ...], "draft_message": "..."}. '
               "explanation: 2 short sentences using ONLY numbers from compare_payment. missing_info: up to 3 short questions "
               "about what is still unknown (advance, agreed deduction, partial payment, proof). draft_message: a polite message "
               "to the contractor asking for clarification, empty string if the payment matches. "
               "Never accuse anyone, never promise to recover money, never invent numbers.")
        user = (f"Order {order_no}. Received Rs {received}. Advance paid earlier: Rs {advance_paid}. "
                f"Agreed deductions: Rs {agreed_deductions}. Partial payment: {is_partial}. Her note: {note or '-'}")
        messages = [{"role": "system", "content": sys}, {"role": "user", "content": user}]
        for _ in range(5):
            resp = _llm_call(self.trace, "Payment Discrepancy", messages, tools=PAYMENT_TOOLS, max_tokens=900)
            if not resp["tool_calls"]:
                return self._parse(resp["content"])
            messages.append(llm.assistant_message(resp))
            for c in resp["tool_calls"]:
                a = dict(c["arguments"])
                if c["name"] == "compare_payment":  # never trust model-copied numbers: use what she entered
                    a.update(order_no=order_no, received=received, advance_paid=advance_paid,
                             agreed_deductions=agreed_deductions, is_partial=is_partial)
                if c["name"] == "get_record":
                    a["order_no"] = order_no
                if c["name"] in ("get_record", "compare_payment"):
                    res = self.tools.run("Payment Discrepancy", c["name"], a)
                else:
                    res = {"error": "unknown tool"}
                messages.append({"role": "tool", "tool_call_id": c["id"], "content": json.dumps(res, ensure_ascii=False)})
        return None

    @staticmethod
    def _parse(text: str):
        if not text:
            return None
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            return None
        try:
            return Narrative.model_validate(json.loads(m.group()))
        except (json.JSONDecodeError, ValidationError):
            return None
