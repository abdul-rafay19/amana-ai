import db, records as R, security as S

OWNER = "t_rec"
BASE = {"quantity": 100, "rate_per_piece": 80, "expected_total": 8000, "sources": {}}


def setup_module():
    db.ensure_owner(OWNER)


def test_hash_is_stable_and_verifies():
    rec = R.create_record(OWNER, dict(BASE))
    assert len(rec["hash"]) == 64 and R.verify_record(rec)["ok"]
    assert R.canonical({"b": 1, "a": 2}) == R.canonical({"a": 2, "b": 1})


def test_tamper_is_detected_and_field_named():
    rec = R.create_record(OWNER, dict(BASE))
    R.tamper_demo(OWNER, rec["order_no"])
    v = R.verify_record(R.latest_record(OWNER, rec["order_no"]))
    assert not v["ok"] and v["changed_fields"] == ["rate_per_piece"]
    assert not R.verify_chain(OWNER)["ok"]
    R.restore_original(OWNER, rec["order_no"])
    assert R.verify_chain(OWNER)["ok"]


def test_chain_links_records():
    a = R.create_record(OWNER, dict(BASE)); b = R.create_record(OWNER, dict(BASE))
    assert b["prev_hash"] == a["hash"]


def test_edit_makes_new_version_and_keeps_original():
    a = R.create_record(OWNER, dict(BASE))
    b = R.add_version(OWNER, a["order_no"], {"rate_per_piece": 90})
    assert b["version"] == 2 and b["data"]["rate_per_piece"] == 90
    assert R.all_versions(OWNER, a["order_no"])[0]["data"]["rate_per_piece"] == 80


def test_payment_is_linked_to_agreement_hash():
    a = R.create_record(OWNER, dict(BASE))
    p = R.save_payment(OWNER, a["order_no"], a["hash"], {"received": 6500})
    assert R.list_payments(OWNER, a["order_no"])[0]["agreement_hash"] == a["hash"] and len(p["hash"]) == 64


def test_owners_are_isolated():
    db.ensure_owner("other")
    assert R.list_orders("other") == []


def test_pin_flow():
    S.set_pin(OWNER, "4821")
    assert S.check_pin(OWNER, "4821") and not S.check_pin(OWNER, "1111") and not S.check_pin(OWNER, "abcd")
    assert db.get_owner(OWNER)["pin_hash"] != "4821"  # never stored in plain text
    try:
        S.set_pin(OWNER, "12"); assert False
    except ValueError:
        pass


def test_lockout_and_idle():
    att, until = 0, 0
    for _ in range(5):
        att, until = S.register_failure(att, now=100.0)
    assert until == 100.0 + S.LOCKOUT_SECONDS
    assert S.is_idle(0, 60, now=61) and not S.is_idle(0, 60, now=59)


def test_notification_has_no_sensitive_details():
    n = S.safe_notification()
    assert not any(ch.isdigit() for ch in n["title"] + n["body"]) and "Rs" not in n["body"]
