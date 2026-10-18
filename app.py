"""Amana AI: voice-first agents that help home-based women workers understand offers,
keep tamper-evident work records and check payments. Run: streamlit run app.py"""
from __future__ import annotations

import time
import urllib.parse
import uuid

import streamlit as st

import calc
import db
import llm
import records
import security
from agents import DealAgent, Orchestrator, PaymentAgent, Trace, WorkRecordAgent
from i18n import t
from schemas import REQUIRED, missing_required, next_question
import ui
from ui import esc

st.set_page_config(page_title="Amana AI", page_icon="🧵", layout="wide", initial_sidebar_state="collapsed")
try:
    llm.configure(st.secrets)
except Exception:
    pass
db.init()
ui.inject_css()
ss = st.session_state

# ------------------------------------------------------------------ identity & state
if "owner" not in ss:
    p = st.query_params.get("profile", "")
    ss.owner = p if (p.isalnum() and 4 <= len(p) <= 32) else uuid.uuid4().hex[:10]
    st.query_params["profile"] = ss.owner
owner = ss.owner
db.ensure_owner(owner)

DEFAULTS = {"S": {"draft": {}, "chat": [], "trace": [], "min_hourly": 0}, "stage": "describe", "unlocked": True,
            "last_active": time.time(), "pin_entry": "", "attempts": 0, "lock_until": 0.0, "wrong": False,
            "pending": None, "asked": None, "aud_n": 0, "last_audio": None, "voice_err": False,
            "report": None, "follow": None, "order_no": None, "tts_audio": None, "lang_choice": "English"}
for k, v in DEFAULTS.items():
    ss.setdefault(k, v)
S = ss.S
lang = "ur" if ss.lang_choice == "اردو" else "en"
has_pin = security.has_pin(owner)


def chat_lang() -> str:
    return S.get("chat_lang") or lang


def reset_order():
    ss.S = {"draft": {}, "chat": [], "trace": [], "min_hourly": 0}
    ss.update(stage="describe", report=None, follow=None, order_no=None, asked=None, pending=None)
    for k in ("msg_text", "target"):
        ss.pop(k, None)


# ------------------------------------------------------------------ lock screen (Shared-Phone Safe Mode)
def press(d: str):
    if time.time() < ss.lock_until:
        return
    ss.wrong = False
    if d == "back":
        ss.pin_entry = ss.pin_entry[:-1]
        return
    if len(ss.pin_entry) < 4:
        ss.pin_entry += d
    if len(ss.pin_entry) == 4:
        if security.check_pin(owner, ss.pin_entry):
            ss.unlocked, ss.attempts, ss.last_active = True, 0, time.time()
        else:
            ss.attempts, ss.lock_until = security.register_failure(ss.attempts)
            ss.wrong = True
        ss.pin_entry = ""


def lock_screen():
    ui.md(f'<div class="lockwrap">{ui.PADLOCK}<h2 dir="auto">{esc(t("lock_title", lang))}</h2>'
          f'<p class="sub" dir="auto">{esc(t("lock_sub", lang))}</p></div>')
    wait = int(ss.lock_until - time.time())
    ui.md(ui.lock_dots(len(ss.pin_entry)))
    if wait > 0:
        msg = t("lock_wait", lang, s=wait)
    elif ss.wrong:
        msg = t("lock_wrong", lang, n=security.MAX_ATTEMPTS - ss.attempts)
    else:
        msg = ""
    ui.md(f'<div class="lockerr" dir="auto">{esc(msg)}</div>')
    with st.container(key="keypad"):
        for row in (("1", "2", "3"), ("4", "5", "6"), ("7", "8", "9")):
            cols = st.columns(3)
            for c, d in zip(cols, row):
                c.button(d, key=f"k{d}", on_click=press, args=(d,))
        cols = st.columns(3)
        cols[1].button("0", key="k0", on_click=press, args=("0",))
        cols[2].button("⌫", key="kb", on_click=press, args=("back",))
    if wait > 0:
        time.sleep(1)
        st.rerun()


if has_pin and ss.unlocked and security.is_idle(ss.last_active, security.lock_seconds(owner)):
    ss.unlocked = False
if not has_pin:
    ss.unlocked = True
if has_pin and not ss.unlocked:
    _, mid, _ = st.columns([1, 1.2, 1])
    with mid:
        lock_screen()
    st.stop()
ss.last_active = time.time()  # any interaction counts as activity


@st.fragment(run_every=2)
def autolock_pill():
    if not security.has_pin(owner):
        return
    left = int(security.lock_seconds(owner) - (time.time() - ss.last_active))
    if left <= 0:
        ss.unlocked = False
        st.rerun()
    st.markdown(f'<div style="text-align:end"><span class="badge sample">🔒 {esc(t("lock_in", lang, s=max(left, 0)))}</span></div>',
                unsafe_allow_html=True)


# ------------------------------------------------------------------ sidebar
with st.sidebar:
    stt = llm.status()
    st.markdown("### Amana AI")
    st.caption("Your work companion")
    ss.voice_lang = st.radio("Voice language", ["ur", "en"], format_func=lambda x: "اردو" if x == "ur" else "English",
                             horizontal=True, key="voice_lang_r")
    ss.tts = st.toggle(t("sb_tts", lang), key="tts_on")

# ------------------------------------------------------------------ header
top = st.columns([6, 1.9, 1.5])
with top[1]:
    with st.container(key="lang"):
        st.radio("lang", ["English", "اردو"], horizontal=True, key="lang_choice", label_visibility="collapsed")
with top[2]:
    autolock_pill()
ui.hero(lang)

tab_work, tab_rec, tab_safe = st.tabs([t("nav_work", lang), t("nav_records", lang), t("nav_safe", lang)])


# ================================================================== WORK TAB
def speak_aloud(text: str):
    cl = chat_lang()
    if not ss.get("tts_on") or cl == "roman":
        return
    try:
        from gtts import gTTS
        import io
        buf = io.BytesIO()
        gTTS(text=text[:400], lang="ur" if cl == "ur" else "en").write_to_fp(buf)
        ss.tts_audio = buf.getvalue()
    except Exception:
        ss.tts_audio = None


def summary_text(rep, rec) -> str:
    c, d = rep["comparison"], rec["data"]
    return "\n".join([
        f"Amana AI payment summary for {rep['order_no']}",
        f"Item: {d.get('quantity')} x {d.get('item') or 'pieces'} at {calc.fmt_rs(d.get('rate_per_piece'))} per piece",
        f"Agreed total: {calc.fmt_rs(c['expected'])}", f"Advance paid earlier: {calc.fmt_rs(c['advance_paid'])}",
        f"Agreed deductions: {calc.fmt_rs(c['agreed_deductions'])}", f"Received now: {calc.fmt_rs(c['received'])}",
        f"Difference: {calc.fmt_rs(c['difference'])}", f"Not explained: {calc.fmt_rs(c['unexplained'])}",
        f"Status: {c['status']}", f"Agreement fingerprint: {rep['agreement_hash']}",
        "Note: the fingerprint shows whether the record changed after saving; it does not prove the information was true.",
    ])


with tab_work:
    idx = {"describe": 0, "review": 1, "confirmed": 3, "report": 4}[ss.stage]
    ui.stepper(idx, lang)
    left, right = st.columns([1.55, .85], gap="large")
    with right:
        ui.assistant_panel(lang, ss.stage)

    def live(events):
        # Internal model/tool traces are retained in session state for diagnostics,
        # but are intentionally not exposed in the worker-facing interface.
        return None

    def mk_trace() -> Trace:
        return Trace(S["trace"], live)

    # ---------------------------------------------------------- stage: describe
    if ss.stage == "describe":
        with left:
            def chat_bubble(role, text):
                with st.chat_message(role, avatar="🧵" if role == "assistant" else "👩"):
                    mark = '<span class="u-msg"></span>' if role == "user" else ""
                    st.markdown(f'{mark}<div class="bubble" dir="auto">{esc(text)}</div>', unsafe_allow_html=True)

            # Let the conversation take only the space it needs; a fixed-height
            # chat window leaves a large empty block before the examples.
            box = st.container(border=False)
            with box:
                chat_bubble("assistant", t("greet", lang))
                for m in S["chat"]:
                    chat_bubble(m["role"], m["text"])
                if ss.pending:
                    text, ss.pending = ss.pending, None
                    chat_bubble("user", text)
                    with st.chat_message("assistant", avatar="🧵"):
                        with st.spinner(t("thinking", lang)):
                            reply = Orchestrator(owner, S, mk_trace()).handle(text, ss.asked)
                        st.markdown(f'<div class="bubble" dir="auto">{esc(reply)}</div>', unsafe_allow_html=True)
                    S["chat"] += [{"role": "user", "text": text}, {"role": "assistant", "text": reply}]
                    ss.asked = next_question(S["draft"])
                    speak_aloud(reply)
                    if ss.tts_audio:
                        st.audio(ss.tts_audio, autoplay=True)
                        ss.tts_audio = None

            if not S["chat"]:
                st.caption(t("try", lang))
                sc = st.columns(3)
                for c, k, lab in zip(sc, ("sample_en", "sample_ro", "sample_ur"), ("English", "Roman Urdu", "اردو")):
                    c.button(lab, key=f"s_{k}", use_container_width=True,
                             on_click=lambda k=k: ss.__setitem__("pending", t(k, lang)))

            if stt["voice"]:
                with st.container(border=True):
                    st.markdown(f"**🎙 {esc(t('speak', lang))}**")
                    audio = st.audio_input(t("speak", lang), key=f"aud{ss.aud_n}", label_visibility="collapsed")
                    if audio is not None:
                        data = audio.getvalue()
                        h = records.sha256_hex(data)
                        if h != ss.last_audio:
                            ss.last_audio = h
                            try:
                                txt = llm.transcribe(data, "voice.wav", language=ss.get("voice_lang", "ur"))
                            except Exception:
                                txt = ""
                            if txt:
                                ss.pending, ss.voice_err = txt, False
                            else:
                                ss.voice_err = True
                            ss.aud_n += 1
                            st.rerun()
                    if ss.voice_err:
                        st.warning(t("err_voice", lang))
            else:
                st.caption("🎙 " + t("no_voice", lang))

            st.chat_input(t("type_ph", lang), key="chat_in", on_submit=lambda: ss.__setitem__("pending", ss.chat_in))

            ui.md(ui.draft_card(S["draft"], ss.asked, lang))
            can_calc = not missing_required(S["draft"])
            b1, b2, b3 = st.columns([1.5, 1.1, 1])
            if b1.button(t("btn_numbers", lang), type="primary", disabled=not can_calc, use_container_width=True, key="go_numbers"):
                tr = mk_trace()
                deal = DealAgent(owner, S, tr)
                res = deal.evaluate()
                if "error" in res:
                    st.error(res["error"])
                else:
                    with st.spinner(t("thinking", lang)):
                        S["explain"] = deal.explain(chat_lang())
                    ss.stage = "review"
                    st.rerun()
            if ss.asked and ss.asked not in REQUIRED:
                if b2.button(t("btn_skip", lang), use_container_width=True, key="skip_q"):
                    S["draft"].setdefault("_skipped", []).append(ss.asked)
                    ss.asked = next_question(S["draft"])
                    st.rerun()
            if S["chat"] and b3.button(t("btn_restart", lang), use_container_width=True, key="restart"):
                reset_order()
                st.rerun()

    # ---------------------------------------------------------- stage: review
    elif ss.stage == "review":
        with left:
            c, d, flags = S["calc"], S["draft"], S["flags"]
            unk = t("r_unknown", lang)
            rows = [(f'{t("r_expected", lang)} ({c["quantity"]} × {calc.fmt_rs(c["rate_per_piece"])})', calc.fmt_rs(c["expected_total"]), "")]
            rows.append((t("r_costs", lang), calc.fmt_rs(c["material_expenses"]) if c["material_expenses"] is not None else unk,
                         "" if c["material_expenses"] is not None else "dim"))
            rows.append((t("r_net", lang), calc.fmt_rs(c["net_after_expenses"]) if c["net_after_expenses"] is not None else unk,
                         "" if c["net_after_expenses"] is not None else "dim"))
            rows.append((t("r_hours", lang), f'{c["estimated_hours"]:g}' if c["estimated_hours"] else unk, "" if c["estimated_hours"] else "dim"))
            rows += ["rule", (t("r_hourly", lang), calc.fmt_rs(c["hourly_net"]) if c["hourly_net"] is not None else "–", "big")]
            ui.md(f'<div class="card"><h3 dir="auto">{esc(t("review_title", lang))}</h3>{ui.ledger(rows)}'
                  f'<div class="note" dir="auto">{esc(t("estimate_note", lang))}</div></div>')
            ui.md(f'<div class="ai-note"><b>{esc(t("note_ai", lang))}</b><span dir="auto">{esc(S.get("explain", ""))}</span></div>')
            ui.md(f'<div class="card"><h3 dir="auto">{esc(t("flags_title", lang))}</h3>{ui.flags_html(flags, lang)}</div>')

            with st.expander(t("counter_title", lang)):
                tgt = st.number_input(t("counter_target", lang), min_value=0, max_value=100000, step=10,
                                      value=int(S.get("min_hourly") or 150), key="target")
                if st.button(t("counter_btn", lang), key="counter_go"):
                    if not d.get("estimated_hours"):
                        st.warning(t("need_hours", lang))
                    elif tgt <= 0:
                        st.warning(t("pay_zero", lang))
                    else:
                        S["min_hourly"] = tgt
                        tr = mk_trace()
                        DealAgent(owner, S, tr).evaluate()
                        with st.spinner(t("thinking", lang)):
                            S["counter"] = DealAgent(owner, S, tr).counteroffer(tgt, chat_lang())
                        st.rerun()
                co = S.get("counter")
                if co and "error" not in co:
                    if co["already_meets_target"]:
                        st.success(t("counter_ok", lang))
                    else:
                        st.info(t("counter_result", lang, t=calc.fmt_rs(co["target_hourly"]), r=calc.fmt_rs(co["suggested_rate"]),
                                  c=calc.fmt_rs(co["current_rate"])))
                        ui.md(f'<p class="sub">{esc(t("counter_msg", lang))}</p><div class="msg" dir="auto">{esc(co["message"])}</div>')

            ui.md(f'<p class="sub" dir="auto">{esc(t("confirm_note", lang))}</p>')
            a, b = st.columns([1.4, 1])
            if a.button(t("btn_confirm", lang), type="primary", use_container_width=True, key="confirm"):
                tr = mk_trace()
                rec = WorkRecordAgent(owner, S, tr).save_confirmed()
                ss.order_no, ss.stage = rec["order_no"], "confirmed"
                st.rerun()
            if b.button(t("btn_edit", lang), use_container_width=True, key="edit_back"):
                ss.stage = "describe"
                st.rerun()

    # ---------------------------------------------------------- stage: confirmed (record saved, enter payment)
    elif ss.stage == "confirmed":
        with left:
            rec = records.latest_record(owner, ss.order_no)
            ui.md(f'<h3 style="margin:0 0 8px" dir="auto">✓ {esc(t("rec_saved", lang))}</h3>')
            ui.md(ui.record_card(rec, records.verify_record(rec), lang))
            with st.form("pay_form"):
                st.markdown(f"### {t('pay_title', lang)}")
                st.caption(f"{t('pay_expected', lang)}: {calc.fmt_rs(rec['data']['expected_total'])}")
                received = st.number_input(t("pay_received", lang), min_value=0.0, step=100.0, value=0.0)
                c1, c2 = st.columns(2)
                adv = c1.number_input(t("pay_adv", lang), min_value=0.0, step=100.0, value=0.0)
                ded = c2.number_input(t("pay_ded", lang), min_value=0.0, step=100.0, value=0.0)
                partial = st.checkbox(t("pay_partial", lang))
                note = st.text_input(t("pay_note", lang))
                proof = st.file_uploader(t("pay_proof", lang), type=["png", "jpg", "jpeg", "pdf"])
                go = st.form_submit_button(t("pay_btn", lang), type="primary")
            if go:
                try:
                    ev_hash = records.save_evidence(owner, proof.getvalue(), proof.name) if proof else None
                    with st.spinner(t("thinking", lang)):
                        rep = PaymentAgent(owner, S, mk_trace()).run(ss.order_no, received, adv, ded, partial, note, chat_lang(), bool(proof))
                    if rep.get("blocked"):
                        st.error(t("blocked", lang))
                        st.stop()
                    c = rep["comparison"]
                    records.save_payment(owner, ss.order_no, rep["agreement_hash"],
                                         {**c, "note": note, "sources": {"received": "supported_by_evidence" if proof else "reported_by_worker"}},
                                         ev_hash)
                    ss.report, ss.follow, ss.msg_text, ss.stage = rep, None, rep["draft_message"], "report"
                    ss.report_n = ss.get("report_n", 0) + 1
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))

    # ---------------------------------------------------------- stage: report
    else:
        with left:
            rep, rec = ss.report, records.latest_record(owner, ss.order_no)
            c = rep["comparison"]
            big = calc.fmt_rs(abs(c["unexplained"])) if c["status"] in ("short", "partial_pending", "over") else ""
            ui.md(ui.banner(c["status"], t(f"st_{c['status']}", lang), big))
            rows = [(t("pay_expected", lang), calc.fmt_rs(c["expected"]), ""), (t("rep_adv", lang), calc.fmt_rs(c["advance_paid"]), "dim"),
                    (t("rep_ded", lang), calc.fmt_rs(c["agreed_deductions"]), "dim"), (t("rep_recv", lang), calc.fmt_rs(c["received"]), ""),
                    "rule", (t("rep_diff", lang), calc.fmt_rs(c["difference"]), "big"),
                    (t("rep_unx", lang), calc.fmt_rs(c["unexplained"]), "warn" if c["unexplained"] > 0 else "good")]
            integ = rep["integrity"]
            ui.md(f'<div class="card"><h3 dir="auto">{esc(t("rep_title", lang))} · {esc(rep["order_no"])}</h3>{ui.ledger(rows)}'
                  f'<div style="margin-top:12px">{ui.badge(integ["ok"], t("int_ok", lang) if integ["ok"] else t("int_bad", lang, f=", ".join(integ["changed_fields"])))}</div></div>')
            ui.md(f'<div class="ai-note"><b>{esc(t("note_ai", lang))}</b><span dir="auto">{esc(rep["explanation"])}</span></div>')
            if rep["missing_info"]:
                items = "".join(f'<li dir="auto">{esc(m)}</li>' for m in rep["missing_info"])
                ui.md(f'<div class="card q"><h3 dir="auto">{esc(t("rep_missing", lang))}</h3><ul style="margin:0;padding-inline-start:20px">{items}</ul></div>')

            if rep["draft_message"] or ss.get("msg_text"):
                ui.md(f'<p class="sub" style="margin-bottom:6px">{esc(t("rep_draft", lang))}</p><div class="msg" dir="auto">{esc(ss.get("msg_text", ""))}</div>')
                if ss.follow is None:
                    with st.expander(t("rep_edit", lang)):
                        st.text_area("msg", value=ss.msg_text, key=f"draft_edit_{ss.report_n}", height=150, label_visibility="collapsed",
                                     on_change=lambda: ss.__setitem__("msg_text", ss[f"draft_edit_{ss.report_n}"]))
                    a, b = st.columns([1.4, 1])
                    if a.button(t("rep_approve", lang), type="primary", use_container_width=True, key="approve"):
                        records.save_followup(owner, ss.order_no, ss.msg_text, "approved")
                        ss.follow = "approved"
                        st.rerun()
                    if b.button(t("rep_dismiss", lang), use_container_width=True, key="dismiss"):
                        records.save_followup(owner, ss.order_no, ss.msg_text, "dismissed")
                        ss.follow = "dismissed"
                        st.rerun()
                elif ss.follow == "approved":
                    st.success(t("rep_approved", lang))
                    st.link_button(t("rep_wa", lang), "https://wa.me/?text=" + urllib.parse.quote(ss.msg_text))
                    st.code(ss.msg_text, language=None)
                else:
                    st.info(t("rep_dismissed", lang))
            else:
                st.caption(t("rep_nomsg", lang))
            d1, d2 = st.columns(2)
            d1.download_button(t("rep_download", lang), summary_text(rep, rec), file_name=f"{rep['order_no']}-summary.txt", use_container_width=True)
            if d2.button(t("rep_new", lang), use_container_width=True, key="new_order"):
                reset_order()
                st.rerun()

    live(S["trace"])


# ================================================================== RECORDS TAB
def load_sample():
    data = {"item": "embroidered suits", "quantity": 100, "rate_per_piece": 80, "deadline_days": 10, "material_expenses": 1500,
            "estimated_hours": 90, "payment_terms": "on delivery", "contractor_name": None, "other_terms": None,
            "advance_received": None, "expected_total": 8000, "net_after_expenses": 6500, "hourly_net": 72.22}
    data["sources"] = {k: "reported_by_worker" for k in ("item", "quantity", "rate_per_piece", "deadline_days", "material_expenses",
                                                           "estimated_hours", "payment_terms")}
    data["sources"].update(expected_total="calculated", net_after_expenses="calculated", hourly_net="calculated")
    rec = records.create_record(owner, data, is_sample=True)
    cmp = calc.compare_payment(8000, 6500)
    records.save_payment(owner, rec["order_no"], rec["hash"], {**cmp, "note": "sample", "sources": {"received": "reported_by_worker"}})


with tab_rec:
    orders = records.list_orders(owner)
    ui.md(f'<h3 style="margin:.2rem 0 .6rem" dir="auto">{esc(t("records_title", lang))}</h3>')
    if not orders:
        ui.md(f'<div class="card"><p dir="auto" style="margin:0">{esc(t("rec_empty", lang))}</p></div>')
        st.button(t("btn_sample", lang), key="load_sample", on_click=load_sample, type="primary")
    else:
        exp = recv = unx = 0
        pays = {o["order_no"]: records.list_payments(owner, o["order_no"]) for o in orders}
        for o in orders:
            exp += o["data"].get("expected_total") or 0
            if pays[o["order_no"]]:
                p = pays[o["order_no"]][-1]["data"]
                recv += p["received"]
                unx += max(p["unexplained"], 0)
        ui.md(f'<div class="strip"><div><b>{len(orders)}</b><small>{esc(t("sum_orders", lang))}</small></div>'
              f'<div><b>{calc.fmt_rs(exp)}</b><small>{esc(t("sum_expected", lang))}</small></div>'
              f'<div><b>{calc.fmt_rs(recv)}</b><small>{esc(t("sum_received", lang))}</small></div>'
              f'<div><b>{calc.fmt_rs(unx)}</b><small>{esc(t("sum_open", lang))}</small></div></div>')
        if st.button(t("btn_verify", lang), key="verify_all"):
            res = records.verify_chain(owner)
            if res["ok"]:
                st.success(t("chain_ok", lang, n=res["length"]))
            else:
                st.error(t("chain_bad", lang, p="; ".join(f"{a} v{b}: {c}" for a, b, c in res["problems"])))
        for o in orders:
            d, no = o["data"], o["order_no"]
            ver = records.verify_record(o)
            with st.expander(f'{no} · {d.get("quantity")} × {d.get("item") or "—"} · {calc.fmt_rs(d.get("expected_total"))}' + ("" if ver["ok"] else "  ⚠"),
                             expanded=not ver["ok"]):
                ui.md(ui.record_card(o, ver, lang))
                src = d.get("sources", {})
                lab = {"item": "f_item", "quantity": "f_quantity", "rate_per_piece": "f_rate", "material_expenses": "f_materials",
                       "estimated_hours": "f_hours", "deadline_days": "f_deadline", "payment_terms": "f_terms"}
                rows = []
                for k, lk in lab.items():
                    if d.get(k) is not None:
                        shown = calc.fmt_rs(d[k]) if k in ("rate_per_piece", "material_expenses") else str(d[k])
                        rows.append((f'{t(lk, lang)} ({t("src_worker" if src.get(k) == "reported_by_worker" else "src_calc", lang)})', shown, ""))
                rows += ["rule", (t("r_expected", lang), calc.fmt_rs(d.get("expected_total")), "big")]
                ui.md(f'<div class="card">{ui.ledger(rows)}</div>')
                st.markdown(f"**{t('pay_hist', lang)}**")
                if not pays[no]:
                    st.caption(t("no_pay", lang))
                for p in pays[no]:
                    pd_ = p["data"]
                    st.markdown(f'- {p["created_at"][:10]}: {calc.fmt_rs(pd_["received"])} · {t("st_" + pd_["status"], lang)} · `{p["hash"][:12]}…`')
                c1, c2 = st.columns(2)
                if c1.button(t("btn_tamper", lang), key=f"tam_{no}"):
                    records.tamper_demo(owner, no)
                    st.rerun()
                if c2.button(t("btn_restore", lang), key=f"res_{no}", disabled=ver["ok"]):
                    records.restore_original(owner, no)
                    st.rerun()
                st.caption(t("tamper_note", lang))

# ================================================================== SAFE MODE TAB
with tab_safe:
    sl, sr = st.columns([1.1, 1], gap="large")
    with sl:
        ui.md(f'<h3 style="margin:.2rem 0 .6rem" dir="auto">{esc(t("safe_title", lang))}</h3>')
        if has_pin:
            st.success(t("safe_on", lang))
            secs = st.select_slider(t("autolock", lang), options=[30, 60, 120, 300], value=security.lock_seconds(owner),
                                    format_func=lambda s: f"{s}s", key="lock_secs")
            if secs != security.lock_seconds(owner):
                db.set_owner_field(owner, "lock_seconds", secs)
            a, b = st.columns(2)
            if a.button(t("lock_now", lang), type="primary", use_container_width=True, key="lock_now"):
                ss.unlocked, ss.pin_entry = False, ""
                st.rerun()
            if b.button(t("pin_off", lang), use_container_width=True, key="pin_off"):
                security.clear_pin(owner)
                st.rerun()
        else:
            st.warning(t("safe_off", lang))
            with st.form("pin_form"):
                p1 = st.text_input(t("pin_new", lang), type="password", max_chars=4)
                p2 = st.text_input(t("pin_again", lang), type="password", max_chars=4)
                ok = st.form_submit_button(t("pin_save", lang), type="primary")
            if ok:
                if not security.valid_pin(p1):
                    st.error(t("pin_invalid", lang))
                elif p1 != p2:
                    st.error(t("pin_mismatch", lang))
                else:
                    security.set_pin(owner, p1)
                    st.success(t("pin_ok", lang))
                    st.rerun()
        items = "".join(f"<li dir='auto'>{esc(x)}</li>" for x in t("limits", lang))
        ui.md(f'<div class="card" style="margin-top:14px"><h3 dir="auto">{esc(t("limits_title", lang))}</h3>'
              f'<ul style="margin:0;padding-inline-start:20px;line-height:1.8">{items}</ul></div>')
    with sr:
        ui.md(f'<h3 style="margin:.2rem 0 .6rem" dir="auto">{esc(t("notif_title", lang))}</h3>')
        bad = security.unsafe_notification_example()
        good = security.safe_notification(lang=lang)
        ui.md(ui.notification(bad["title"], bad["body"], t("notif_bad", lang)))
        st.write("")
        ui.md(ui.notification(good["title"], good["body"], t("notif_good", lang)))
        st.caption(t("notif_note", lang))
