"""Agent workflow tests. The LLM is replaced by a scripted fake so the tool loop,
validation and approval flow are tested without network access."""
import json
import db, llm, records as R
from agents import Orchestrator, DealAgent, WorkRecordAgent, PaymentAgent, Trace

OWNER = "t_agent"


def setup_module():
    db.ensure_owner(OWNER)


def mk():
    state = {"draft": {}, "chat": [], "trace": []}
    return state, Trace(state["trace"])


def test_offline_flow_extracts_and_asks_followup():
    state, tr = mk()
    reply = Orchestrator(OWNER, state, tr).handle("I got 30 dresses, Rs 250 each")
    assert state["draft"]["quantity"] == 30 and state["draft"]["rate_per_piece"] == 250
    assert "materials" in reply.lower()          # next missing detail is asked
    assert tr.store[0]["tool"] == "record_order_details"


def test_invalid_numbers_are_rejected_not_saved():
    state, tr = mk()
    Orchestrator(OWNER, state, tr).handle("order of 30 dresses, 250 per dress, 0 hours")
    assert state["draft"].get("estimated_hours") in (None,)


def test_roman_urdu_reply_language():
    state, tr = mk()
    reply = Orchestrator(OWNER, state, tr).handle("mujhe 30 frock ka order mila hai, 250 rupay per piece")
    assert state["chat_lang"] == "roman" and "kharcha" in reply.lower()


def test_full_workflow_save_then_payment_report():
    state, tr = mk()
    o = Orchestrator(OWNER, state, tr)
    o.handle("100 garments, Rs 80 each, five days, materials Rs 1200, 60 hours, on delivery")
    DealAgent(OWNER, state, tr).evaluate()
    assert state["calc"]["expected_total"] == 8000
    rec = WorkRecordAgent(OWNER, state, tr).save_confirmed()
    rep = PaymentAgent(OWNER, state, tr).run(rec["order_no"], 6500, 0, 0, False, "", "en")
    assert rep["comparison"]["difference"] == 1500 and rep["comparison"]["status"] == "short"
    assert rep["integrity"]["ok"] and "Rs 1,500" in rep["draft_message"]
    assert len(rep["missing_info"]) >= 2
    rep2 = PaymentAgent(OWNER, state, tr).run(rec["order_no"], 6500, 1000, 500, False, "", "roman")
    assert rep2["comparison"]["status"] == "explained" and rep2["draft_message"] == ""
    R.tamper_demo(OWNER, rec["order_no"])
    rep3 = PaymentAgent(OWNER, state, tr).run(rec["order_no"], 6500, 0, 0, False, "", "en")
    assert rep3["blocked"] and rep3["integrity"]["changed_fields"] == ["rate_per_piece"]   # no report on a changed record
    R.restore_original(OWNER, rec["order_no"])


class FakeLLM:
    """Scripted model: first calls the tool, then writes a reply."""
    def __init__(self, script): self.script, self.i = script, 0
    def __call__(self, messages, tools=None, **kw):
        r = self.script[self.i]; self.i += 1
        return {"content": r.get("content", ""), "tool_calls": r.get("tool_calls", []), "provider": "fake", "model": "fake", "ms": 1}


def test_llm_tool_loop_uses_tools_and_validates(monkeypatch):
    fake = FakeLLM([
        {"tool_calls": [{"id": "1", "name": "record_order_details", "arguments": {"quantity": 30, "rate_per_piece": 250, "estimated_hours": -4}}]},
        {"content": "Got it. How much will you spend on materials?"},
    ])
    monkeypatch.setattr(llm, "available", lambda: ["fake"]); monkeypatch.setattr(llm, "chat", fake)
    state, tr = mk()
    reply = Orchestrator(OWNER, state, tr).handle("30 dresses at 250")
    assert reply.startswith("Got it") and state["draft"]["quantity"] == 30
    assert "estimated_hours" in tr.store[1]["result"]["errors"]      # bad value rejected by validation
    assert [e["kind"] for e in tr.store] == ["ai", "code", "ai"]


def test_llm_failure_falls_back_to_offline(monkeypatch):
    def boom(*a, **k): raise llm.LLMUnavailable("rate limited")
    monkeypatch.setattr(llm, "available", lambda: ["fake"]); monkeypatch.setattr(llm, "chat", boom)
    state, tr = mk()
    Orchestrator(OWNER, state, tr).handle("30 dresses, Rs 250 each")
    assert state["draft"]["quantity"] == 30 and any(e["tool"] == "fallback" for e in tr.store)


def test_payment_agent_numbers_never_come_from_the_model(monkeypatch):
    state, tr = mk()
    o = Orchestrator(OWNER, state, tr)
    o.handle("100 garments, Rs 80 each, 5 days, materials 1200, 60 hours, on delivery")
    DealAgent(OWNER, state, tr).evaluate()
    rec = WorkRecordAgent(OWNER, state, tr).save_confirmed()
    fake = FakeLLM([
        {"tool_calls": [{"id": "a", "name": "get_record", "arguments": {"order_no": rec["order_no"]}},
                        {"id": "b", "name": "compare_payment", "arguments": {"order_no": rec["order_no"], "received": 9999}}]},
        {"content": json.dumps({"explanation": "Short by Rs 1,500.", "missing_info": ["Was there an advance?"], "draft_message": "Salam, please clarify."})},
    ])
    monkeypatch.setattr(llm, "available", lambda: ["fake"]); monkeypatch.setattr(llm, "chat", fake)
    rep = PaymentAgent(OWNER, state, tr).run(rec["order_no"], 6500, 0, 0, False, "", "en")
    assert rep["comparison"]["received"] == 6500 and rep["comparison"]["difference"] == 1500
    assert rep["draft_message"] == "Salam, please clarify."


def test_safe_text_rejects_unknown_numbers_and_accusations():
    from agents import safe_text
    facts = {"expected": 8000, "received": 6500, "difference": 1500}
    assert safe_text("Aap ko Rs 6,500 mile, farq 1500 ka hai.", facts)
    assert not safe_text("Farq 2000 ka hai.", facts)                 # invented number
    assert not safe_text("You are a cheat, pay 1500.", facts)        # accusation
    assert safe_text("آپ کو ۶۵۰۰ ملے", facts)                        # Urdu digits are understood


def test_unsafe_model_message_is_replaced_by_template(monkeypatch):
    state, tr = mk()
    Orchestrator(OWNER, state, tr).handle("100 garments, Rs 80 each, 5 days, materials 1200, 60 hours, on delivery")
    DealAgent(OWNER, state, tr).evaluate()
    rec = WorkRecordAgent(OWNER, state, tr).save_confirmed()
    bad = {"explanation": "He is a thief, he owes you 9999.", "missing_info": [], "draft_message": "Pay 9999 or else, cheat."}
    fake = FakeLLM([{"tool_calls": [{"id": "a", "name": "get_record", "arguments": {}}, {"id": "b", "name": "compare_payment", "arguments": {}}]},
                    {"content": json.dumps(bad)}])
    monkeypatch.setattr(llm, "available", lambda: ["fake"]); monkeypatch.setattr(llm, "chat", fake)
    rep = PaymentAgent(OWNER, state, tr).run(rec["order_no"], 6500, 0, 0, False, "", "en")
    assert "9999" not in rep["explanation"] + rep["draft_message"] and "cheat" not in rep["draft_message"].lower()
    assert "Rs 1,500" in rep["draft_message"] and any(e["tool"] == "safety_check" for e in tr.store)
