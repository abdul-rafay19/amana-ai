# Amana AI: She does the work. Amana works for her.

Voice-first AI agents that help Pakistan's home-based women workers understand an offer, keep a tamper-evident
record of the agreement, and check whether the payment matches. NYLP 2026, category: AI Agents.

## Run it
```bash
pip install -r requirements.txt
cp .env.example .env     # or .streamlit/secrets.toml.example -> secrets.toml. Use YOUR OWN keys
python check_keys.py     # should end with: OK via gemini (or groq)
streamlit run app.py
python -m pytest tests -q                                     # 33 tests, no network needed
python -m tests.eval_extraction                               # extraction accuracy (add --llm for the model)
```
No key? The app still works in **offline mode** with a rule-based parser (the sidebar says so).

## Deploy (no Railway/Render)
Push to GitHub, open share.streamlit.io, choose `app.py`, paste your keys under Settings > Secrets.
Storage on Streamlit Cloud resets on restart, so use "Load sample data" in the Records tab for the demo.

## How the agents work
| Piece | AI does | Code does |
|---|---|---|
| Orchestrator (`agents.py`) | Reads Urdu / Roman Urdu / English, chooses tools, asks ONE follow-up | Validates every field (`schemas.py`) |
| Deal Intelligence | Explains the offer simply, drafts a counteroffer message | `calc.py`: totals, earnings, hourly rate, risk flags, required rate |
| Work Record | Nothing (on purpose) | `records.py`: canonical JSON, SHA-256, hash chain, versions, verify |
| Payment Discrepancy | Tool loop: get_record, compare_payment; writes explanation and polite message | `calc.compare_payment`; numbers the model sends are ignored |
| Safe Mode | Nothing | bcrypt PIN, auto-lock, lockout, masked notifications |

Every model and tool call appears live in the **agents panel** (code = exact, AI = language).
If a provider fails, the next one is tried; if all fail, the rule-based path takes over.

## Demo script (the 9 steps)
1. Tap an example (or speak). 2. Answer Amana's one-at-a-time questions. 3. "Show me the numbers".
4. Try the counteroffer, then "Confirm agreement". 5. Open Records: see the SHA-256 fingerprint.
6. Enter what she received (try 6500 against 8000). 7. Read the report. 8. Approve the message (it only opens WhatsApp, never auto-sends).
9. Safe mode tab: set a PIN, "Lock now", use the keypad. Records tab: "Demo: secretly change the rate", then "Check all records".

## Honest limits (say them in the pitch)
- A hash detects changes; it does not prove the information was true. Fields are tagged told-by-you or calculated.
- Estimates use only her own figures; they are not guaranteed profit or market rates.
- A PIN alone cannot fully protect a shared phone; notification previews are simulated.
- Not an official registration system; that would need validation with labour departments.
- Profile ids in the URL separate visitors but are not accounts. Do not store real personal data on a public demo.
- The offline parser scores 20/20 on our 20 test inputs, but we wrote those while building it. Measure the LLM path on fresh inputs before quoting accuracy.

## Troubleshooting (found while testing with live keys)
| You see | Fix |
|---|---|
| No keys / offline mode | File must be named exactly `.env` (not `.env.txt`), next to `llm.py`, lines like `GEMINI_API_KEY=...` |
| Gemini 404 | Model name not available for your key. Set `GEMINI_MODEL` (default `gemini-flash-lite-latest`) |
| Gemini 429 | Free-tier limit. Wait a minute, send one message at a time, and give each teammate their own key |
| Groq 401 | Use a **Groq** key (`gsk_...`, console.groq.com), not a **Grok** / x.ai key |
| Groq 404 | Retired model. Set `GROQ_MODEL` (default `openai/gpt-oss-120b`) |
| Voice does nothing | Needs `GROQ_API_KEY` (Whisper) or `GEMINI_API_KEY` (fallback). Always keep typing as backup |

AI-written text is checked before use (`agents.safe_text`): any number that is not in the facts, or any accusing word,
causes a fixed polite template to be used instead, and the rejection shows in the agents panel.
A payment is never compared against a record whose fingerprint no longer matches.
