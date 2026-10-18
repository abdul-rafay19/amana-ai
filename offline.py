"""Rule-based fallback so Amana still works with no API key or when every
provider is down. It handles English, Roman Urdu and Urdu script for the
common order phrasing. The LLM path is more flexible; this is the safety net."""
from __future__ import annotations

import re

_EAST = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


_WORDNUM = {
    "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "twelve": 12, "fifteen": 15, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "hundred": 100,
    "teen": 3, "char": 4, "panch": 5, "paanch": 5, "chay": 6, "saat": 7, "aath": 8, "nau": 9, "das": 10,
    "bees": 20, "tees": 30, "pachas": 50, "تین": 3, "چار": 4, "پانچ": 5, "چھ": 6, "سات": 7, "آٹھ": 8,
    "نو": 9, "دس": 10, "بیس": 20, "تیس": 30, "پچاس": 50,
}


def normalize(text: str) -> str:
    t = (text or "").translate(_EAST)
    t = re.sub(r"[\u060C\u061B\u061F\u06D4]", " ", t)  # Arabic comma, semicolon, question mark, full stop
    t = re.sub(r"(?<=\d),(?=\d{3}\b)", "", t)
    t = re.sub(r"[\w\u0600-\u06FF]+", lambda m: str(_WORDNUM[m.group().lower()]) if m.group().lower() in _WORDNUM else m.group(), t)
    return t.strip()


_URDU_RE = re.compile(r"[\u0600-\u06FF]")
_ROMAN = {"din", "dino", "rupay", "rupaye", "hai", "hain", "mein", "ka", "ke", "ki", "kar", "dena", "mila",
          "mili", "kapra", "kapray", "ghante", "ghanta", "lagega", "lagenge", "mujhe", "meri", "mera", "har",
          "aur", "kharcha", "kharch", "peshgi", "order", "hoga", "wala", "karna", "kitne", "kitna", "se",
          "payment", "milegi", "milenge", "jora", "joray", "bana", "banana", "silai"}


def detect_lang(text: str) -> str:
    """'ur' (Urdu script), 'roman' (Roman Urdu) or 'en'."""
    if _URDU_RE.search(text or ""):
        return "ur"
    words = set(re.findall(r"[a-z]+", (text or "").lower()))
    return "roman" if len(words & _ROMAN) >= 2 else "en"


CUR = {"rs", "rupees", "rupee", "rupay", "rupaye", "rupaya", "rupiya", "روپے", "روپیہ", "روپیے", "pkr"}
HOURS = {"hour", "hours", "hr", "hrs", "ghanta", "ghante", "ghantay", "گھنٹے", "گھنٹہ", "گھنٹوں"}
DAYS = {"day", "days", "din", "dino", "دن", "دنوں"}
WEEKS = {"week", "weeks", "hafta", "hafte", "ہفتہ", "ہفتے"}
PER = {"per", "each", "har", "ek", "fi", "فی", "ہر", "ایک", "pe", "prati"}
RATEW = {"rate", "price", "ریٹ", "قیمت"}
ADV = {"advance", "peshgi", "پیشگی", "ایڈوانس"}
EXP = {"material", "materials", "kharcha", "kharch", "kharche", "expense", "expenses", "cost", "costs",
       "lagat", "kapra", "kapray", "kapre", "dhaga", "thread", "fabric", "cloth", "خرچ", "خرچہ", "مٹیریل",
       "کپڑا", "کپڑے", "دھاگہ", "لاگت"}
ITEMS = {"dress", "dresses", "suit", "suits", "frock", "frocks", "garment", "garments", "piece", "pieces",
         "pcs", "pc", "shirt", "shirts", "kurta", "kurtas", "shalwar", "bag", "bags", "cap", "caps",
         "dupatta", "dupattas", "scarf", "scarves", "item", "items", "joray", "jore", "jora", "pair", "pairs",
         "جوڑے", "جوڑا", "سوٹ", "فراک", "پیس", "ڈریس", "کرتے", "کرتا", "شرٹ", "شرٹس", "دوپٹے", "عدد"}
GENERIC = {"piece", "pieces", "pcs", "pc", "item", "items", "عدد", "پیس"}
QTYW = {"order", "quantity", "qty", "total", "received", "got", "mila", "mili", "آرڈر"}
TERMS = re.compile(r"(on delivery|after delivery|on completion|after completion|cash on delivery|weekly|monthly|"
                   r"delivery par|delivery ke baad|delivery pe|delivery k baad|ڈیلیوری پر|ڈیلیوری کے بعد|مال دینے پر|ہفتہ وار|ماہانہ)", re.I)
WORD = re.compile(r"[\w\u0600-\u06FF]+")


def _classify(before: list[str], after: list[str]) -> str | None:
    a = [w for w in after if w not in CUR]
    b = [w for w in before if w not in CUR]
    a1 = a[0] if a else ""
    if a1 in HOURS:
        return "hours"
    if a1 in DAYS:
        return "days"
    if a1 in WEEKS:
        return "weeks"
    if any(w in ADV for w in a[:3] + b[-3:]):
        return "advance"
    if a1 in PER or a[:2] in (["for", "each"], ["for", "every"]) or (b and b[-1] in RATEW):
        return "rate"
    if a1 in ITEMS:
        return "qty"
    if any(w in EXP for w in a[:3] + b[-3:]):
        return "expenses"
    if b and b[-1] in QTYW:
        return "qty"
    return None


def extract_offline(text: str, asked_field: str | None = None) -> dict:
    t = normalize(text)
    low = t.lower()
    out: dict = {}
    nums = list(re.finditer(r"\d+(?:\.\d+)?", low))
    for m in nums:
        before = WORD.findall(low[max(0, m.start() - 40):m.start()])[-3:]
        after = WORD.findall(low[m.end():m.end() + 40])[:3]
        role = _classify(before, after)
        val = float(m.group())
        val = int(val) if val.is_integer() else val
        key = {"hours": "estimated_hours", "days": "deadline_days", "weeks": "deadline_days",
               "advance": "advance_received", "rate": "rate_per_piece", "qty": "quantity",
               "expenses": "material_expenses"}.get(role)
        if not key or key in out:
            continue
        if role == "weeks":
            val = int(val * 7)
        out[key] = val
        if role == "qty" and after and after[0] in ITEMS and after[0] not in GENERIC:
            out["item"] = after[0]
    # a bare number answers the question we just asked
    if asked_field and asked_field not in out and len(nums) == 1 and not out:
        v = float(nums[0].group())
        v = int(v) if v.is_integer() else v
        if asked_field not in ("payment_terms", "item"):
            out[asked_field] = v
    tm = TERMS.search(t)
    if tm:
        out["payment_terms"] = tm.group(0)
    elif asked_field == "payment_terms" and t:
        out["payment_terms"] = t[:200]
    if re.search(r"\b(nothing|none|no cost|koi kharcha nahi|kuch nahi)\b|کچھ نہیں|کوئی خرچ", low) and asked_field == "material_expenses":
        out.setdefault("material_expenses", 0)
    return out


# ---------------- replies (en / roman / ur) ----------------
Q = {
    "quantity": {"en": "How many pieces is the order?", "roman": "Order kitne pieces ka hai?",
                 "ur": "آرڈر کتنے پیس کا ہے؟"},
    "rate_per_piece": {"en": "How much will you be paid for each piece (in Rs)?",
                       "roman": "Har piece ke kitne rupay milenge?", "ur": "ہر پیس کے کتنے روپے ملیں گے؟"},
    "material_expenses": {"en": "How much will you spend on materials (thread, cloth, etc.)? Say 0 if nothing.",
                          "roman": "Material (dhaga, kapra wagera) par kitna kharcha hoga? Kuch nahi to 0 likhein.",
                          "ur": "مٹیریل (دھاگہ، کپڑا وغیرہ) پر کتنا خرچ ہوگا؟ اگر کچھ نہیں تو 0 لکھیں۔"},
    "estimated_hours": {"en": "About how many hours will the whole order take you?",
                        "roman": "Poora order karne mein taqreeban kitne ghante lagenge?",
                        "ur": "پورا آرڈر کرنے میں تقریباً کتنے گھنٹے لگیں گے؟"},
    "deadline_days": {"en": "In how many days must you deliver it?", "roman": "Order kitne din mein dena hai?",
                      "ur": "آرڈر کتنے دن میں دینا ہے؟"},
    "payment_terms": {"en": "When and how will you be paid? (for example, on delivery)",
                      "roman": "Payment kab aur kaise milegi? (masalan delivery par)",
                      "ur": "ادائیگی کب اور کیسے ہوگی؟ (مثلاً ڈیلیوری پر)"},
}
LABEL = {
    "quantity": {"en": "pieces", "roman": "pieces", "ur": "پیس"},
    "rate_per_piece": {"en": "per piece", "roman": "per piece", "ur": "فی پیس"},
    "material_expenses": {"en": "materials", "roman": "material", "ur": "مٹیریل"},
    "estimated_hours": {"en": "hours", "roman": "ghante", "ur": "گھنٹے"},
    "deadline_days": {"en": "days", "roman": "din", "ur": "دن"},
}
MSG = {
    "got": {"en": "Got it:", "roman": "Samajh gayi:", "ur": "سمجھ گئی:"},
    "ready": {"en": "I have what I need. Press “Show me the numbers” to see the calculation.",
              "roman": "Mujhe zaroori maloomat mil gayi hain. “Hisaab dikhayein” dabayein.",
              "ur": "ضروری معلومات مل گئی ہیں۔ “حساب دکھائیں” دبائیں۔"},
    "nothing": {"en": "I could not find order details in that. Tell me the number of pieces and the rate, for example: “30 dresses, Rs 250 each”.",
                "roman": "Is mein order ki tafseel nahi mili. Pieces aur rate batayein, masalan: “30 dress, 250 per piece”.",
                "ur": "اس میں آرڈر کی تفصیل نہیں ملی۔ پیس اور ریٹ بتائیں، مثلاً: “30 ڈریس، 250 روپے فی پیس”۔"},
    "bad": {"en": "That number does not look right:", "roman": "Yeh number theek nahi lag raha:",
            "ur": "یہ عدد درست نہیں لگ رہا:"},
}


def _unit(field, v):
    return v


def summarize(draft: dict, lang: str) -> str:
    parts = []
    for f in ("quantity", "rate_per_piece", "material_expenses", "estimated_hours", "deadline_days"):
        v = draft.get(f)
        if v is None:
            continue
        lab = LABEL[f][lang]
        if f in ("rate_per_piece", "material_expenses"):
            parts.append(f"Rs {v:,.0f} {lab}" if lang != "ur" else f"{lab} Rs {v:,.0f}")
        else:
            parts.append(f"{v:g} {lab}")
    if draft.get("payment_terms"):
        parts.append(str(draft["payment_terms"]))
    return "، ".join(parts) if lang == "ur" else ", ".join(parts)


def reply_offline(draft: dict, updated: list, errors: dict, next_q: str | None, lang: str, can_calc: bool) -> str:
    L = lang if lang in ("en", "roman", "ur") else "en"
    lines = []
    if errors:
        lines.append(f"{MSG['bad'][L]} {', '.join(errors.keys())}")
    if updated:
        lines.append(f"{MSG['got'][L]} {summarize(draft, L)}")
    elif not errors and not draft.get("quantity") and not draft.get("rate_per_piece"):
        lines.append(MSG["nothing"][L])
    if next_q:
        lines.append(Q[next_q][L])
    elif can_calc:
        lines.append(MSG["ready"][L])
    return "\n\n".join(lines)
