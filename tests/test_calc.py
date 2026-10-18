import pytest
import calc


def test_example_from_brief():
    c = calc.calculate_deal(30, 250, 1200, 60)
    assert c["expected_total"] == 7500
    assert c["net_after_expenses"] == 6300
    assert c["hourly_net"] == 105


def test_missing_optional_inputs():
    c = calc.calculate_deal(30, 250)
    assert c["net_after_expenses"] is None and c["hourly_net"] is None


@pytest.mark.parametrize("q,r", [(0, 250), (-5, 250), (30, 0), (30, -1)])
def test_rejects_nonsense(q, r):
    with pytest.raises(ValueError):
        calc.calculate_deal(q, r)


def test_negative_expenses_and_zero_hours():
    with pytest.raises(ValueError):
        calc.calculate_deal(10, 10, -1, 5)
    with pytest.raises(ValueError):
        calc.calculate_deal(10, 10, 5, 0)


def test_decimal_precision():
    assert calc.expected_total(3, 0.1) == 0.3  # no float drift


def test_payment_short():
    c = calc.compare_payment(8000, 6500)
    assert c["difference"] == 1500 and c["unexplained"] == 1500 and c["status"] == "short"


def test_payment_match_and_over():
    assert calc.compare_payment(8000, 8000)["status"] == "match"
    o = calc.compare_payment(8000, 8500)
    assert o["status"] == "over" and o["unexplained"] == -500


def test_advance_and_agreed_deduction_explain_gap():
    c = calc.compare_payment(8000, 6500, advance_paid=1000, agreed_deductions=500)
    assert c["status"] == "explained" and c["unexplained"] == 0


def test_partial_payment():
    c = calc.compare_payment(8000, 5000, is_partial=True)
    assert c["status"] == "partial_pending" and c["unexplained"] == 3000


def test_partial_with_advance_leaves_remainder():
    c = calc.compare_payment(8000, 5000, advance_paid=1000, is_partial=True)
    assert c["unexplained"] == 2000


def test_counteroffer_hits_target():
    r = calc.required_rate_for_target(30, 1200, 60, 150, 250)
    assert r["suggested_rate"] == 340 and r["new_hourly_net"] >= 150
    assert calc.required_rate_for_target(30, 1200, 60, 100, 250)["already_meets_target"]


def test_risk_flags():
    o = {"quantity": 30, "rate_per_piece": 250, "estimated_hours": 100, "deadline_days": 5, "material_expenses": 5000}
    c = calc.calculate_deal(30, 250, 5000, 100)
    codes = {f["code"] for f in calc.analyze_risks(o, c, min_hourly=100)}
    assert {"no_payment_terms", "high_expense", "tight_deadline", "below_target"} <= codes
    clean = {"payment_terms": "on delivery", "material_expenses": 100, "estimated_hours": 10, "deadline_days": 5}
    f = calc.analyze_risks(clean, calc.calculate_deal(30, 250, 100, 10))
    assert [x["level"] for x in f] == ["green"]
