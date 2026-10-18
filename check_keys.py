"""Run:  python check_keys.py   -> shows which providers have a key and sends one test message."""
import llm
try:
    import streamlit as st
    llm.configure(st.secrets)
except Exception:
    pass
print("Providers with keys:", llm.available() or "none")
for p in llm.available():
    print(f"  {p}: model {llm.model_for(p)}")
try:
    r = llm.chat([{"role": "system", "content": "Reply with one word."}, {"role": "user", "content": "Say OK"}], max_tokens=20)
    print("OK via", r["provider"], "-", r["content"])
except llm.LLMUnavailable as e:
    print("FAILED:", e, "\nSee README > Troubleshooting")
