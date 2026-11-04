from html import escape

import streamlit as st

LOGO = "https://laat.ac.uk/assets/img/laat-logo.jpg"

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
:root { --cvc-accent: #1d4ed8; --cvc-accent-dark: #1e3a8a; --cvc-line: rgba(127,127,127,.20);
        --cvc-soft: rgba(127,127,127,.06); }
html, body, .stApp, .stMarkdown, button, input, textarea { font-family: 'Inter', system-ui, -apple-system, sans-serif; }
code, pre { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
.stAppDeployButton, #MainMenu, footer, [data-testid="stDecoration"] { display: none !important; }
.stTabs [data-baseweb="tab-highlight"] { background-color: var(--cvc-accent); }
.block-container { padding-top: 1.6rem; padding-bottom: 3rem; max-width: 1320px; }
h1, h2, h3, h4 { font-weight: 650; letter-spacing: -0.015em; }

.stButton > button, .stDownloadButton > button { border-radius: 10px; font-weight: 550; padding: .5rem 1rem;
        transition: transform .05s ease, box-shadow .15s ease; }
.stButton > button:hover, .stDownloadButton > button:hover { box-shadow: 0 2px 10px rgba(29,78,216,.15); }
.stButton > button:active { transform: translateY(1px); }
.stButton > button[kind="primary"], .stDownloadButton > button[kind="primary"] {
        background: var(--cvc-accent); border-color: var(--cvc-accent); color: #fff; }
.stButton > button[kind="primary"]:hover { background: var(--cvc-accent-dark); border-color: var(--cvc-accent-dark); }

[data-testid="stMetric"] { background: var(--cvc-soft); border: 1px solid var(--cvc-line); border-radius: 14px;
        padding: 14px 18px; }
[data-testid="stMetricLabel"] p { font-size: .82rem; font-weight: 550; opacity: .75; }
[data-testid="stMetricValue"] { font-weight: 700; }

[data-testid="stExpander"] details { border-radius: 12px; border-color: var(--cvc-line); }
[data-testid="stVerticalBlockBorderWrapper"] { border-radius: 14px; }
.stTabs [data-baseweb="tab-list"] { gap: 4px; border-bottom: 1px solid var(--cvc-line); }
.stTabs [data-baseweb="tab"] { padding: 8px 14px; border-radius: 10px 10px 0 0; font-weight: 550; }
[data-testid="stSidebar"] { border-right: 1px solid var(--cvc-line); }
[data-testid="stSidebar"] .block-container { padding-top: 1rem; }
[data-testid="stFileUploaderDropzone"] { border-radius: 12px; }
.stCode pre { border-radius: 10px; }

.cvc-hero { display: flex; align-items: center; gap: 16px; padding: 18px 22px; margin-bottom: 18px;
        border-radius: 16px; border: 1px solid var(--cvc-line);
        background: linear-gradient(120deg, rgba(29,78,216,.10), rgba(29,78,216,.02) 60%); }
.cvc-hero img { height: 46px; border-radius: 10px; background: #fff; padding: 4px; }
.cvc-hero .t { font-size: 1.45rem; font-weight: 700; letter-spacing: -0.02em; line-height: 1.2; }
.cvc-hero .s { opacity: .72; font-size: .92rem; margin-top: 2px; }
.cvc-hero .u { margin-left: auto; font-size: .82rem; padding: 6px 12px; border-radius: 999px;
        border: 1px solid var(--cvc-line); background: var(--cvc-soft); white-space: nowrap; }
.cvc-steps { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 14px; margin: 8px 0 4px; }
.cvc-step { border: 1px solid var(--cvc-line); border-radius: 14px; padding: 16px 18px; background: var(--cvc-soft); }
.cvc-step .n { display: inline-flex; width: 26px; height: 26px; border-radius: 50%; align-items: center;
        justify-content: center; background: var(--cvc-accent); color: #fff; font-weight: 700; font-size: .85rem; }
.cvc-step .h { font-weight: 650; margin: 10px 0 4px; }
.cvc-step .d { opacity: .75; font-size: .9rem; }
.cvc-pill { display: inline-block; padding: 3px 10px; border-radius: 999px; font-size: .8rem; font-weight: 600;
        border: 1px solid transparent; }
.cvc-pill.red { background: rgba(220,38,38,.12); color: #dc2626; border-color: rgba(220,38,38,.25); }
.cvc-pill.amber { background: rgba(217,119,6,.12); color: #d97706; border-color: rgba(217,119,6,.25); }
.cvc-pill.green { background: rgba(22,163,74,.12); color: #16a34a; border-color: rgba(22,163,74,.25); }
.cvc-pill.blue { background: rgba(29,78,216,.10); color: var(--cvc-accent); border-color: rgba(29,78,216,.25); }
.cvc-login { max-width: 460px; margin: 9vh auto 20px; text-align: center; padding: 36px 32px; border-radius: 18px;
        border: 1px solid var(--cvc-line); background: var(--cvc-soft); }
.cvc-login img { height: 64px; border-radius: 12px; background: #fff; padding: 6px; }
.cvc-login .t { font-size: 1.5rem; font-weight: 700; margin-top: 14px; letter-spacing: -0.02em; }
.cvc-login .s { opacity: .72; margin: 6px 0 4px; }
.cvc-muted { opacity: .7; font-size: .88rem; }
.cvc-quote { border-left: 3px solid var(--cvc-accent); background: var(--cvc-soft); padding: 10px 14px;
        border-radius: 0 10px 10px 0; margin: 2px 0 14px; line-height: 1.6; }
.cvc-meta { font-size: .8rem; opacity: .7; margin-top: 6px; }
</style>
"""

PILL = {"Needs review": "red", "Check": "amber", "Original": "green",
        "Rewrite needed": "red", "Small fixes": "amber", "No action": "green"}


def inject_css():
    st.markdown(CSS, unsafe_allow_html=True)


def hero(title, subtitle, user=None):
    chip = f'<div class="u">Signed in as {escape(user)}</div>' if user else ""
    st.markdown(
        f'<div class="cvc-hero"><img src="{LOGO}" alt="LAAT"><div><div class="t">{escape(title)}</div>'
        f'<div class="s">{escape(subtitle)}</div></div>{chip}</div>',
        unsafe_allow_html=True,
    )


def login_card(title, subtitle):
    st.markdown(
        f'<div class="cvc-login"><img src="{LOGO}" alt="LAAT"><div class="t">{escape(title)}</div>'
        f'<div class="s">{escape(subtitle)}</div></div>',
        unsafe_allow_html=True,
    )


def pill(label, kind=None):
    return f'<span class="cvc-pill {kind or PILL.get(label, "blue")}">{escape(label)}</span>'


def steps(items):
    cards = "".join(
        f'<div class="cvc-step"><span class="n">{i}</span><div class="h">{escape(h)}</div>'
        f'<div class="d">{escape(d)}</div></div>' for i, (h, d) in enumerate(items, 1)
    )
    st.markdown(f'<div class="cvc-steps">{cards}</div>', unsafe_allow_html=True)


def quote(text, meta=""):
    meta_html = f'<div class="cvc-meta">{escape(meta)}</div>' if meta else ""
    st.markdown(f'{meta_html}<div class="cvc-quote">{escape(text)}</div>', unsafe_allow_html=True)
