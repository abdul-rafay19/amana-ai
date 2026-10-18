"""Visual layer. Design idea: the khata (home ledger) and Sindhi ajrak block-print.
Palette: indigo dye, madder red, chalk white, with leaf green and amber for status."""
from __future__ import annotations

import html
import json
import re

import streamlit as st

from i18n import t

esc = html.escape

LATTICE = ("data:image/svg+xml;utf8,"
           "%3Csvg xmlns='http://www.w3.org/2000/svg' width='36' height='36' viewBox='0 0 36 36'%3E"
           "%3Crect width='36' height='36' fill='%23243063'/%3E"
           "%3Cpath d='M18 3 L33 18 L18 33 L3 18 Z' fill='none' stroke='%23F5F6FA' stroke-width='1.3'/%3E"
           "%3Cpath d='M18 10 L26 18 L18 26 L10 18 Z' fill='%23B2334A'/%3E"
           "%3Ccircle cx='18' cy='18' r='2.2' fill='%23F5F6FA'/%3E"
           "%3Ccircle cx='0' cy='0' r='2' fill='%23F5F6FA'/%3E%3Ccircle cx='36' cy='0' r='2' fill='%23F5F6FA'/%3E"
           "%3Ccircle cx='0' cy='36' r='2' fill='%23F5F6FA'/%3E%3Ccircle cx='36' cy='36' r='2' fill='%23F5F6FA'/%3E%3C/svg%3E")

CSS = """
@import url('https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,500..800&family=Figtree:wght@400;500;600;700&family=Noto+Naskh+Arabic:wght@400..700&family=Noto+Nastaliq+Urdu:wght@400..700&display=swap');
:root{
  --indigo:#243063; --indigo-2:#3A4A94; --ink:#1B2142; --muted:#5B6489; --bg:#F5F6FA; --surface:#FFFFFF;
  --tint:#E9ECF6; --line:#D9DDEC; --madder:#B2334A; --madder-d:#962A3E; --madder-bg:#FBE8EB;
  --leaf:#2E7D5B; --leaf-bg:#E3F2EA; --amber:#A66A0B; --amber-bg:#FCF0D8;
  --f-body:'Figtree','Noto Naskh Arabic',system-ui,sans-serif; --f-head:'Bricolage Grotesque','Noto Naskh Arabic',sans-serif;
  --f-ur:'Noto Nastaliq Urdu','Noto Naskh Arabic',serif;
}
html,body,.stApp,button,input,textarea,p,label,li,div[data-testid="stMarkdownContainer"]{font-family:var(--f-body)}
[data-testid="stIconMaterial"],.material-symbols-rounded{font-family:"Material Symbols Rounded"!important}
.stApp{background:var(--bg);color:var(--ink)}
#MainMenu,footer,[data-testid="stToolbar"],[data-testid="stDecoration"],[data-testid="stStatusWidget"]{display:none!important}
header[data-testid="stHeader"]{background:transparent}
.block-container{max-width:1280px;padding:1.35rem 2rem 4rem}
h1,h2,h3,h4{font-family:var(--f-head)!important;color:var(--indigo);letter-spacing:-.01em}
[dir="auto"],.ur{unicode-bidi:plaintext}
.ur{font-family:var(--f-ur);line-height:2}

/* ---------- hero ---------- */
.hero{border-radius:22px;overflow:hidden;background:var(--indigo);color:#fff;margin:.2rem 0 1rem}
.lattice{height:34px;background:url("__LATTICE__") repeat-x;background-size:34px 34px;border-bottom:3px solid var(--madder)}
.hero-body{padding:20px 26px 24px;display:flex;align-items:center;gap:26px;flex-wrap:wrap}
.mark{display:flex;align-items:baseline;gap:14px}
.mark-ur{font-family:var(--f-ur);font-size:50px;line-height:1.5;color:#fff}
.mark-en{font-family:var(--f-head);font-weight:700;font-size:26px;color:#DDE2F6}
.hero-lines{margin-inline-start:auto;text-align:end}
.hero-en{font-family:var(--f-head);font-size:20px;font-weight:600;margin:0;color:#fff}
.hero-ur{font-family:var(--f-ur);font-size:17px;line-height:2.1;margin:0;color:#C9D0EE}
@media(max-width:700px){.hero-lines{margin:0;text-align:start}.mark-ur{font-size:40px}}
.assistant-card{position:sticky;top:1rem;background:linear-gradient(155deg,#243063,#303f7e);color:#fff;border-radius:22px;padding:24px 22px;box-shadow:0 12px 30px rgba(36,48,99,.13);margin-top:2px}
.assistant-mark{width:48px;height:48px;border-radius:16px;background:rgba(255,255,255,.13);display:grid;place-items:center;font-size:24px;margin-bottom:18px}
.assistant-card h3{color:#fff!important;font-size:21px;margin:0 0 8px}
.assistant-card p{color:#e1e5f6;line-height:1.65;font-size:14px;margin:0}
.assistant-points{border-top:1px solid rgba(255,255,255,.18);margin-top:18px;padding-top:13px;display:grid;gap:11px}
.assistant-point{display:flex;align-items:flex-start;gap:10px;color:#f0f2fa;font-size:13px;line-height:1.5}
.assistant-point i{width:8px;height:8px;border-radius:50%;background:#8bd6b0;margin-top:5px;flex:none}
.assistant-foot{font-size:12px!important;color:#bbc4e8!important;margin-top:16px!important}

/* ---------- tabs ---------- */
.stTabs [role="tablist"]{gap:4px;background:var(--tint);padding:5px;border-radius:999px;width:fit-content;max-width:100%}
.stTabs [role="tab"]{height:40px;padding:0 20px;border-radius:999px;font-weight:600;color:var(--muted);background:transparent}
.stTabs [aria-selected="true"]{background:var(--surface)!important;color:var(--indigo)!important;box-shadow:0 1px 3px rgba(36,48,99,.14)}
.stTabs [data-baseweb="tab-highlight"],.stTabs [data-baseweb="tab-border"],.stTabs [role="tablist"]>div[aria-hidden]{display:none!important}.stTabs [role="tablist"]{border-bottom:none!important}

/* ---------- stepper ---------- */
.steps{display:flex;align-items:center;margin:.9rem 0 1.1rem}
.step{display:flex;align-items:center;gap:8px;flex:0 0 auto}
.dot{width:30px;height:30px;border-radius:50%;display:grid;place-items:center;font-weight:700;font-size:13px;
  border:2px solid var(--line);color:var(--muted);background:var(--surface)}
.step.done .dot{background:var(--indigo);border-color:var(--indigo);color:#fff}
.step.now .dot{border-color:var(--madder);color:var(--madder);box-shadow:0 0 0 4px var(--madder-bg)}
.step .lab{font-weight:600;font-size:14px;color:var(--muted)}
.step.now .lab,.step.done .lab{color:var(--indigo)}
.stitch{flex:1;min-width:14px;border-top:2px dashed var(--line);margin:0 10px}
.stitch.done{border-top-color:var(--indigo)}
@media(max-width:700px){.step .lab{display:none}.step.now .lab{display:inline}}

/* ---------- cards ---------- */
.card{background:var(--surface);border:1px solid var(--line);border-radius:16px;padding:18px 20px;margin-bottom:14px}
.card h3{margin:0 0 10px;font-size:19px}
.sub{color:var(--muted);font-size:13.5px;margin:0}
.note{background:var(--tint);border-radius:12px;padding:11px 14px;font-size:14px;color:var(--ink);margin:10px 0 0}
.ai-note{border-inline-start:4px solid var(--madder);background:var(--surface);border-radius:4px 14px 14px 4px;
  padding:12px 16px;margin:12px 0;font-size:15.5px;line-height:1.75;border-top:1px solid var(--line);border-bottom:1px solid var(--line);border-inline-end:1px solid var(--line)}
.ai-note b{display:block;font-family:var(--f-head);color:var(--madder);font-size:14px;margin-bottom:2px}

/* ---------- ledger (khata) ---------- */
.ledger .row{display:flex;align-items:baseline;gap:8px;padding:7px 0}
.ledger .k{color:var(--ink);font-size:15px}
.ledger .dots{flex:1;border-bottom:2px dotted var(--line);transform:translateY(-4px)}
.ledger .v{font-weight:700;font-variant-numeric:tabular-nums;font-size:16px}
.ledger .v.dim{color:var(--muted);font-weight:500}
.ledger .row.big .k{font-family:var(--f-head);font-weight:600;font-size:17px;color:var(--indigo)}
.ledger .row.big .v{font-family:var(--f-head);font-size:28px;color:var(--indigo)}
.ledger .row.warn .v{color:var(--madder)}
.ledger .row.good .v{color:var(--leaf)}
.ledger .rule{border-top:2px dashed var(--line);margin:6px 0}

/* ---------- flags ---------- */
.flag{display:flex;gap:12px;align-items:flex-start;padding:11px 14px;border-radius:12px;margin:8px 0;font-size:15px;line-height:1.7}
.flag i{width:10px;height:10px;border-radius:50%;margin-top:9px;flex:0 0 auto}
.flag.red{background:var(--madder-bg)}.flag.red i{background:var(--madder)}
.flag.amber{background:var(--amber-bg)}.flag.amber i{background:var(--amber)}
.flag.green{background:var(--leaf-bg)}.flag.green i{background:var(--leaf)}
.flag span.en{display:block}

/* ---------- draft card ---------- */
.dfield{display:flex;justify-content:space-between;align-items:center;gap:10px;padding:9px 0;border-bottom:1px dashed var(--line)}
.dfield:last-child{border-bottom:none}
.dfield .l{color:var(--muted);font-size:14px}
.dfield .val{font-weight:700;font-variant-numeric:tabular-nums}
.dfield .pend{color:#9AA1C4;font-weight:500;font-size:13.5px}
.dfield .tick{color:var(--leaf);margin-inline-end:6px}
.dfield.ask{background:var(--madder-bg);margin:0 -10px;padding:9px 10px;border-radius:10px;border-bottom:none}

/* ---------- badges, banners, record ---------- */
.badge{display:inline-flex;align-items:center;gap:7px;padding:5px 12px;border-radius:999px;font-weight:600;font-size:13.5px}
.badge.ok{background:var(--leaf-bg);color:var(--leaf)}.badge.bad{background:var(--madder-bg);color:var(--madder)}
.badge.sample{background:var(--tint);color:var(--muted)}
.banner{border-radius:16px;padding:16px 20px;margin-bottom:14px;display:flex;gap:14px;align-items:center}
.banner b{font-family:var(--f-head);font-size:20px}
.banner.match,.banner.explained{background:var(--leaf-bg);color:#1E5C42}
.banner.short,.banner.over{background:var(--madder-bg);color:#7D1F31}
.banner.partial_pending{background:var(--amber-bg);color:#7A4E08}
.banner .big{font-family:var(--f-head);font-size:30px;font-weight:700;margin-inline-start:auto}
.hash{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:13px;background:var(--tint);border-radius:10px;
  padding:9px 12px;word-break:break-all;color:var(--indigo);direction:ltr;text-align:left}
.bubble{white-space:pre-wrap;font-size:15.5px;line-height:1.75}
.msg{background:var(--tint);border-radius:14px;padding:12px 16px;white-space:pre-wrap;line-height:1.8;font-size:15.5px}
.q li{margin:6px 0;line-height:1.7}

/* ---------- agent trace (the one dark panel) ---------- */
.trace{background:#1B2352;color:#E6E9F8;border-radius:18px;padding:18px 18px 12px}
.trace h4{color:#fff;margin:0 0 4px;font-size:18px}
.trace .legend{display:flex;gap:14px;flex-wrap:wrap;font-size:12.5px;color:#AEB6DC;margin-bottom:12px}
.trace .legend span::before{content:"";display:inline-block;width:9px;height:9px;border-radius:50%;margin-inline-end:6px}
.trace .legend .c::before{background:#7FD1A8}.trace .legend .a::before{background:#F2A7B4}
.trace .empty{color:#AEB6DC;font-size:14px;line-height:1.7;padding:6px 0 12px}
.ev{position:relative;padding:2px 0 14px 26px;margin-left:6px;border-left:2px dashed #46528F}
.ev:last-child{border-left-color:transparent;padding-bottom:6px}
.ev .node{position:absolute;left:-8px;top:2px;width:14px;height:14px;border-radius:50%;border:2px solid #1B2352}
.ev.code .node{background:#7FD1A8}.ev.ai .node{background:#F2A7B4}.ev.check .node{background:#F6D58A}.ev.bad .node{background:#FF8A8A}
.ev .who{font-size:12.5px;color:#AEB6DC}
.ev .what{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:13.5px;color:#fff;font-weight:600}
.ev .res{font-size:13px;color:#CBD1EE;margin-top:2px;line-height:1.5;word-break:break-word}
.ev .ms{color:#8E97C8;font-size:12px;margin-inline-start:8px}
.ev details{margin-top:4px}.ev summary{cursor:pointer;color:#9FA8DA;font-size:12.5px}
.ev pre{background:#141A40;border-radius:8px;padding:8px 10px;font-size:11.5px;color:#D9DEF7;overflow-x:auto;white-space:pre-wrap;margin:6px 0 0}

/* ---------- summary strip ---------- */
.strip{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:6px 0 16px}
.strip div{background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:12px 14px}
.strip b{display:block;font-family:var(--f-head);font-size:22px;color:var(--indigo);font-variant-numeric:tabular-nums}
.strip small{color:var(--muted)}
@media(max-width:700px){.strip{grid-template-columns:repeat(2,1fr)}}
@media(max-width:700px){.assistant-card{position:static;margin:0 0 1rem;padding:18px}.stTabs [role="tab"]{padding:0 12px}.block-container{padding:.75rem .8rem 3rem}.card{padding:16px}}
.ocard{display:flex;align-items:center;gap:14px;flex-wrap:wrap}
.ocard .no{font-family:var(--f-head);font-weight:700;color:var(--indigo);font-size:18px}

/* ---------- notification previews ---------- */
.phone{background:#10143A;border-radius:22px;padding:16px;max-width:330px}
.phone .n{background:rgba(255,255,255,.12);color:#fff;border-radius:14px;padding:10px 14px;font-size:14px;line-height:1.5}
.phone .n b{display:block;font-size:12.5px;color:#C5CBEE}
.phone .tag{color:#C5CBEE;font-size:12.5px;margin-bottom:8px}

/* ---------- lock screen ---------- */
.lockwrap{text-align:center;padding:28px 0 4px}
.lockwrap h2{margin:12px 0 2px}
.pins{display:flex;gap:16px;justify-content:center;margin:18px 0 6px}
.pins i{width:16px;height:16px;border-radius:50%;border:2px solid var(--indigo)}
.pins i.on{background:var(--indigo)}
.lockerr{color:var(--madder);font-weight:600;min-height:26px;text-align:center}

/* ---------- native widgets ---------- */
.stButton>button,.stDownloadButton>button,.stLinkButton>a{border-radius:999px;font-weight:600;padding:.55rem 1.3rem;min-height:46px;border:1.5px solid var(--indigo);color:var(--indigo);background:var(--surface)}
.stButton>button:hover,.stLinkButton>a:hover{border-color:var(--madder);color:var(--madder)}
button[data-testid="stBaseButton-primary"],.stFormSubmitButton>button[kind="primaryFormSubmit"]{background:var(--madder)!important;border-color:var(--madder)!important;color:#fff!important}
button[data-testid="stBaseButton-primary"]:hover{background:var(--madder-d)!important;color:#fff!important}
button:focus-visible,input:focus-visible,textarea:focus-visible{outline:3px solid var(--indigo-2)!important;outline-offset:2px}
div[data-baseweb="input"],div[data-baseweb="base-input"],div[data-baseweb="textarea"],div[data-baseweb="select"]>div{border-radius:12px!important}
[data-testid="stExpander"]{border-radius:14px;border:1px solid var(--line);background:var(--surface)}
[data-testid="stChatMessage"]{background:var(--surface);border:1px solid var(--line);border-radius:16px;padding:12px 16px;margin-bottom:8px}
[data-testid="stChatMessage"]:has(.u-msg){background:var(--tint);border-color:transparent}
[data-testid="stChatInput"]{border-radius:16px}
[data-testid="stAudioInput"]{border-radius:16px}
[data-testid="stForm"]{border:1px solid var(--line);border-radius:16px;background:var(--surface);padding:18px}
[data-testid="stSidebar"]{background:var(--surface)}
.stRadio [role="radiogroup"]{gap:6px}
.st-key-keypad button{width:76px;height:76px;min-height:76px;border-radius:50%;font-size:1.5rem;font-weight:600;padding:0;border-color:var(--line);background:var(--surface)}
.st-key-keypad [data-testid="stHorizontalBlock"]{justify-content:center;gap:14px;flex-wrap:nowrap!important}
.st-key-keypad [data-testid="stColumn"]{flex:0 0 auto;width:auto;min-width:0}
.st-key-lang [role="radiogroup"]{justify-content:flex-end}
@media(prefers-reduced-motion:reduce){*{transition:none!important;animation:none!important}}
""".replace("__LATTICE__", LATTICE)


def inject_css():
    st.markdown(f"<style>{CSS}</style>", unsafe_allow_html=True)


def _h(s: str) -> str:
    """Collapse whitespace so Streamlit's markdown never treats HTML as a code block."""
    return re.sub(r"\n\s*", "", s).strip()


def md(s: str):
    st.markdown(_h(s), unsafe_allow_html=True)


def hero(lang):
    md(f'''<div class="hero"><div class="lattice"></div><div class="hero-body">
      <div class="mark"><span class="mark-ur">امانہ</span><span class="mark-en">Amana AI</span></div>
      <div class="hero-lines"><p class="hero-en">She does the work. Amana works for her.</p>
      <p class="hero-ur" dir="rtl">کام وہ کرتی ہے۔ حساب امانہ رکھتی ہے۔</p></div></div></div>''')


def assistant_panel(lang, stage):
    if lang == "ur":
        title, intro = "آئیں، آپ کا آرڈر سمجھتے ہیں۔", "مجھے بتائیں آپ کو کون سا کام ملا ہے۔ میں رقم، وقت اور ادائیگی سمجھنے میں مدد کروں گی۔"
        points = ["اردو، رومن اردو یا انگریزی میں بات کریں", "ایک وقت میں ایک آسان سوال", "حساب اور ادائیگی صاف صاف سمجھیں"]
        foot = "ہر قدم پر فیصلہ آپ کا ہے۔"
    else:
        title, intro = "Let’s make your order clear.", "Tell me what work you were offered. I’ll help you understand the pay, time, and payment terms."
        points = ["Speak or type in Urdu, Roman Urdu, or English", "Take it one simple question at a time", "See what the offer means for you"]
        foot = "Your work. Your choices. Your record."
    items = "".join(f'<div class="assistant-point"><i></i><span>{esc(p)}</span></div>' for p in points)
    md(f'<div class="assistant-card"><div class="assistant-mark">🧵</div><h3 dir="auto">{esc(title)}</h3>'
       f'<p dir="auto">{esc(intro)}</p><div class="assistant-points">{items}</div>'
       f'<p class="assistant-foot" dir="auto">{esc(foot)}</p></div>')


def stepper(idx: int, lang):
    keys = ["s_describe", "s_review", "s_record", "s_payment", "s_report"]
    out = []
    for i, k in enumerate(keys):
        cls = "done" if i < idx else ("now" if i == idx else "")
        mark = "✓" if i < idx else str(i + 1)
        out.append(f'<div class="step {cls}"><span class="dot">{mark}</span><span class="lab">{esc(t(k, lang))}</span></div>')
        if i < len(keys) - 1:
            out.append(f'<div class="stitch {"done" if i < idx else ""}"></div>')
    md(f'<div class="steps">{"".join(out)}</div>')


def rs(x) -> str:
    from calc import fmt_rs
    return fmt_rs(x)


def ledger(rows) -> str:
    """rows: (label, value, kind) kind in '', 'big', 'warn', 'good', 'dim', 'rule'."""
    out = []
    for r in rows:
        if r == "rule":
            out.append('<div class="rule"></div>')
            continue
        k, v, kind = (list(r) + [""])[:3]
        vcls = "dim" if kind == "dim" else ""
        rcls = kind if kind in ("big", "warn", "good") else ""
        out.append(f'<div class="row {rcls}"><span class="k" dir="auto">{esc(str(k))}</span><span class="dots"></span>'
                   f'<span class="v {vcls}" dir="auto">{esc(str(v))}</span></div>')
    return f'<div class="ledger">{"".join(out)}</div>'


def flags_html(flags, lang) -> str:
    out = []
    for f in flags:
        main, other = (f["ur"], f["en"]) if lang == "ur" else (f["en"], f["ur"])
        out.append(f'<div class="flag {f["level"]}"><i></i><div><span dir="auto">{esc(main)}</span></div></div>')
    return "".join(out)


FIELD_ROWS = [("item", "f_item"), ("quantity", "f_quantity"), ("rate_per_piece", "f_rate"),
              ("material_expenses", "f_materials"), ("estimated_hours", "f_hours"),
              ("deadline_days", "f_deadline"), ("payment_terms", "f_terms")]


def draft_card(draft: dict, asked: str | None, lang) -> str:
    rows = []
    skipped = draft.get("_skipped", [])
    for key, lab in FIELD_ROWS:
        v = draft.get(key)
        if v is None:
            txt = t("skipped", lang) if key in skipped else t("not_yet", lang)
            cls = "dfield ask" if key == asked else "dfield"
            rows.append(f'<div class="{cls}"><span class="l">{esc(t(lab, lang))}</span><span class="pend" dir="auto">{esc(txt)}</span></div>')
            continue
        if key in ("rate_per_piece", "material_expenses"):
            shown = rs(v)
        elif key == "estimated_hours":
            shown = f"{v:g} {t('hours', lang)}"
        elif key == "deadline_days":
            shown = f"{v:g} {t('days', lang)}"
        else:
            shown = str(v)
        rows.append(f'<div class="dfield"><span class="l">{esc(t(lab, lang))}</span>'
                    f'<span class="val" dir="auto"><span class="tick">✓</span>{esc(shown)}</span></div>')
    return f'<div class="card"><h3>{esc(t("so_far", lang))}</h3>{"".join(rows)}</div>'


def banner(status: str, text: str, big: str = "") -> str:
    icon = {"match": "✓", "explained": "✓", "short": "!", "over": "↑", "partial_pending": "…"}.get(status, "•")
    return (f'<div class="banner {status}"><span style="font-size:28px">{icon}</span><b dir="auto">{esc(text)}</b>'
            f'<span class="big">{esc(big)}</span></div>')


def badge(ok: bool, text: str) -> str:
    return f'<span class="badge {"ok" if ok else "bad"}">{"✓" if ok else "!"} <span dir="auto">{esc(text)}</span></span>'


def record_card(rec: dict, verify: dict, lang) -> str:
    d = rec["data"]
    chain = t("rec_first", lang) if rec["prev_hash"] == "GENESIS" else f'{t("rec_chain", lang)}: {rec["prev_hash"][:12]}…'
    ibad = t("int_bad", lang, f=", ".join(verify["changed_fields"]) or "?")
    return _h(f'''<div class="card"><div class="ocard"><span class="no">{esc(rec["order_no"])}</span>
      {badge(verify["ok"], t("int_ok", lang) if verify["ok"] else ibad)}
      {'<span class="badge sample">' + esc(t("sample_tag", lang)) + '</span>' if rec.get("is_sample") else ''}
      <span class="sub" style="margin-inline-start:auto">v{rec["version"]}</span></div>
      <p class="sub" style="margin:12px 0 6px">{esc(t("rec_fp", lang))}</p>
      <div class="hash">{esc(rec["hash"])}</div>
      <p class="sub" style="margin-top:8px">{esc(chain)}</p>
      <div class="note" dir="auto">{esc(t("rec_honest", lang))}</div></div>''')


def _summ(ev: dict) -> str:
    r = ev.get("result")
    if ev["tool"] == "model_call":
        a = ev["args"]
        calls = ", ".join(a.get("tool_calls") or []) or "reply"
        return f'{a.get("provider")} · {a.get("model")} → {calls}'
    if ev["tool"] == "fallback":
        return f'{ev["args"].get("reason", "")} · {r}'
    if isinstance(r, dict):
        if "updated" in r:
            return (f'saved: {", ".join(r["updated"]) or "nothing new"}'
                    + (f' · rejected: {", ".join(r["errors"])}' if r["errors"] else "")
                    + (f' · next: {r["next_question"]}' if r.get("next_question") else ""))
        if "calc" in r:
            c = r["calc"]
            return f'total {rs(c["expected_total"])} · after costs {rs(c["net_after_expenses"])} · {rs(c["hourly_net"])}/hr'
        if "status" in r:
            return f'{r["status"]} · difference {rs(r["difference"])} · unexplained {rs(r["unexplained"])}'
        if "integrity_ok" in r and "agreement" in r:
            return f'agreement v{r["version"]} · integrity {"ok" if r["integrity_ok"] else "CHANGED"}'
        if "hash" in r:
            return f'sha256 {r["hash"]}…'
        if "integrity_ok" in r:
            return "integrity " + ("verified" if r["integrity_ok"] else "FAILED")
        if "suggested_rate" in r:
            return f'needs {rs(r["suggested_rate"])} per piece for {rs(r["target_hourly"])}/hr'
        if "error" in r:
            return "error: " + str(r["error"])
    return str(r or "")[:120]


def trace_html(events: list, lang) -> str:
    head = (f'<h4>{esc(t("trace_title", lang))}</h4><div class="legend"><span class="c">{esc(t("legend_code", lang))}</span>'
            f'<span class="a">{esc(t("legend_ai", lang))}</span></div>')
    if not events:
        return _h(f'<div class="trace">{head}<div class="empty" dir="auto">{esc(t("trace_empty", lang))}</div></div>')
    rows = []
    for ev in events[-14:]:
        cls = "bad" if not ev["ok"] else ev["kind"]
        detail = json.dumps({"args": ev["args"], "result": ev["result"]}, ensure_ascii=False, indent=1, default=str)[:1400]
        rows.append(f'''<div class="ev {cls}"><span class="node"></span><div class="who">{esc(ev["agent"])}<span class="ms">{ev["ms"]} ms</span></div>
          <div class="what">{esc(ev["tool"])}</div><div class="res">{esc(_summ(ev))}</div>
          <details><summary>details</summary><pre>{esc(detail)}</pre></details></div>''')
    return _h(f'<div class="trace">{head}{"".join(rows)}</div>')


def notification(title, body, tag):
    return _h(f'<div class="phone"><div class="tag">{esc(tag)}</div><div class="n"><b>{esc(title)}</b><span dir="auto">{esc(body)}</span></div></div>')


def lock_dots(n: int) -> str:
    return '<div class="pins">' + "".join(f'<i class="{"on" if i < n else ""}"></i>' for i in range(4)) + "</div>"


PADLOCK = ('<svg width="54" height="54" viewBox="0 0 24 24" fill="none" stroke="#243063" stroke-width="1.7" stroke-linecap="round" '
           'stroke-linejoin="round"><rect x="4.5" y="10.5" width="15" height="10" rx="3"/><path d="M8 10.5V8a4 4 0 0 1 8 0v2.5"/>'
           '<circle cx="12" cy="15.5" r="1.3" fill="#B2334A" stroke="none"/></svg>')
