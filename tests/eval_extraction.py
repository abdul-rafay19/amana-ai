"""Extraction accuracy on 20 hand-written inputs (English, Roman Urdu, Urdu script,
missing details, wrong numbers).  Run:  python -m tests.eval_extraction
Add --llm to evaluate the configured LLM provider instead of the offline parser."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import offline

CASES = [
    ("I received an order for 30 dresses. The contractor will pay me Rs 250 for each dress. 5 days, Rs 1,200 on materials.", None,
     {"quantity": 30, "rate_per_piece": 250, "deadline_days": 5, "material_expenses": 1200}),
    ("30 dresses at Rs 250 each, about 60 hours", None, {"quantity": 30, "rate_per_piece": 250, "estimated_hours": 60}),
    ("order of 100 garments, 80 rupees per garment, payment on delivery", None,
     {"quantity": 100, "rate_per_piece": 80, "payment_terms": "on delivery"}),
    ("They want 12 suits, Rs 900 per suit, within ten days", None, {"quantity": 12, "rate_per_piece": 900, "deadline_days": 10}),
    ("50 shirts, 120 each, thread and cloth cost 800", None, {"quantity": 50, "rate_per_piece": 120, "material_expenses": 800}),
    ("mujhe 30 frock ka order mila hai. 250 rupay per piece. 5 din mein dena hai. 1200 ka kapra lagega.", None,
     {"quantity": 30, "rate_per_piece": 250, "deadline_days": 5, "material_expenses": 1200}),
    ("20 suit, 400 rupay har suit, 40 ghante lagenge", None, {"quantity": 20, "rate_per_piece": 400, "estimated_hours": 40}),
    ("100 pieces ka order hai, 35 rupay per piece, 2 hafte mein", None, {"quantity": 100, "rate_per_piece": 35, "deadline_days": 14}),
    ("mujhe 60 dupatta milay hain, 150 per dupatta, 500 peshgi mili", None, {"quantity": 60, "rate_per_piece": 150, "advance_received": 500}),
    ("مجھے 30 فراک کا آرڈر ملا ہے، 250 روپے فی پیس، 5 دن میں دینا ہے", None,
     {"quantity": 30, "rate_per_piece": 250, "deadline_days": 5}),
    ("۴۰ سوٹ، ۳۰۰ روپے فی سوٹ، ۱۰۰۰ کا مٹیریل", None, {"quantity": 40, "rate_per_piece": 300, "material_expenses": 1000}),
    ("۲۵ جوڑے، ۲۰۰ روپے فی جوڑا، ۲ ہفتے", None, {"quantity": 25, "rate_per_piece": 200, "deadline_days": 14}),
    ("1200", "material_expenses", {"material_expenses": 1200}),
    ("60", "estimated_hours", {"estimated_hours": 60}),
    ("on delivery", "payment_terms", {"payment_terms": "on delivery"}),
    ("7", "deadline_days", {"deadline_days": 7}),
    ("hello, I need help", None, {}),                                  # no details: must extract nothing
    ("30 dresses", None, {"quantity": 30}),                            # rate missing: must not invent one
    ("Rs 250 per dress", None, {"rate_per_piece": 250}),               # quantity missing
    ("the contractor will cut some money if there is a fault", None, {}),
]


def run(use_llm=False):
    ok = fields_ok = fields_total = 0
    for text, asked, exp in CASES:
        got = offline.extract_offline(text, asked)  # offline parser
        if use_llm:
            import llm
            from tools import ToolBox
            st = {"draft": {}}
            ToolBox("eval", st, lambda *a, **k: None)
            r = llm.chat([{"role": "system", "content": "Extract order details via the tool."}, {"role": "user", "content": text}],
                         tools=__import__("tools").CHAT_TOOLS)
            got = r["tool_calls"][0]["arguments"] if r["tool_calls"] else {}
        hit = [k for k, v in exp.items() if got.get(k) == v]
        fields_ok += len(hit); fields_total += len(exp)
        extra = [k for k in got if k not in exp and k not in ("item",)]
        good = len(hit) == len(exp) and not extra
        ok += good
        print(("PASS " if good else "FAIL ") + text[:62], "" if good else f"-> got {got}")
    print(f"\nCases fully correct: {ok}/{len(CASES)}   Field-level accuracy: {fields_ok}/{fields_total} = {fields_ok / fields_total:.0%}")


if __name__ == "__main__":
    run("--llm" in sys.argv)
