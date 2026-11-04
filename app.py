# app.py
# Checks a batch of CVs (PDF and DOCX) for copied text.
#
# Author: Himanshu Chadha
# Company: London Academy for Applied Technology
#
# Run with: streamlit run app.py
from collections import defaultdict

import pandas as pd
import plotly.express as px
import streamlit as st

from cvchecker.auth import require_login
from cvchecker.extract import extract
from cvchecker.feedback import feedback_docx, feedback_zip
from cvchecker.prepare import load_phrases
from cvchecker.report import pairs_table, sections_text, to_excel, to_pdf, triage_table
from cvchecker.similarity import analyse
from cvchecker.triage import AMBER, GREEN, RED, copying_groups, summarise

MAX_FILE_SIZE_MB = 20
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024
MAX_FILES = 100
STATUS_ICON = {RED: "🔴", AMBER: "🟠", GREEN: "🟢"}


def run_analysis(uploaded_files, template_files, extra_phrases, thresholds, min_words):
    problems = []
    docs = []
    by_hash = defaultdict(list)
    for f in uploaded_files:
        if f.size > MAX_FILE_SIZE_BYTES:
            problems.append((f.name, f"Larger than {MAX_FILE_SIZE_MB} MB"))
            continue
        item = extract(f.name, f.getvalue())
        if not item.ok:
            problems.append((f.name, item.problem))
            continue
        by_hash[item.sha256].append(f.name)
        if len(by_hash[item.sha256]) == 1:
            docs.append(item)
    duplicates = [names for names in by_hash.values() if len(names) > 1]

    templates = [extract(f.name, f.getvalue()) for f in template_files or []]
    template_texts = [t.text for t in templates if t.ok]

    if len(docs) < 2:
        return {"error": "Fewer than two readable documents.", "problems": problems, "duplicates": duplicates}

    analysis = analyse([d.text for d in docs], min_words, template_texts, load_phrases(extra=extra_phrases))
    return {
        "names": [d.name for d in docs],
        "ids": [f"Doc #{i + 1}" for i in range(len(docs))],
        "analysis": analysis,
        "summaries": summarise(analysis, thresholds),
        "groups": copying_groups(analysis, thresholds),
        "thresholds": thresholds,
        "problems": problems,
        "duplicates": duplicates,
    }


st.set_page_config(layout="wide", page_title="Document Similarity Checker | LAAT")
user = require_login()

if "results" not in st.session_state:
    st.session_state.results = None

with st.sidebar:
    st.image("https://laat.ac.uk/assets/img/laat-logo.jpg", width=200)
    st.title("London Academy for Applied Technology")
    if user:
        st.caption(f"Signed in as **{user[0]}** ({user[1]})")
        st.button("Sign out", on_click=st.logout)
    st.header("⚙️ Controls")
    uploaded_files = st.file_uploader(
        f"Upload CVs (PDF or DOCX, up to {MAX_FILE_SIZE_MB} MB each, {MAX_FILES} files)",
        type=["pdf", "docx"], accept_multiple_files=True,
    )
    with st.expander("Ignore common wording (optional)"):
        template_files = st.file_uploader(
            "Blank CV template students use. Its wording is ignored.",
            type=["pdf", "docx"], accept_multiple_files=True, key="templates",
        )
        extra_phrases = st.text_area(
            "Extra phrases to ignore, one per line",
            help="Added to the built-in list of stock CV phrases, for this check only.",
        )
    similarity_threshold = st.slider(
        "Similarity threshold", 0.0, 1.0, 0.80, 0.05,
        help="Flags a pair whose overall wording is at least this similar.",
    )
    copied_threshold = st.slider(
        "Copied text threshold", 0.0, 1.0, 0.25, 0.05,
        help="Flags a pair when at least this share of either CV appears word for word in the other.",
    )
    min_block_size = st.number_input(
        "Minimum matching passage (words)", min_value=3, max_value=50, value=10,
        help="Shortest run of identical words counted as a matching passage.",
    )

    if st.button("Analyze Documents", type="primary", use_container_width=True):
        if not uploaded_files or len(uploaded_files) < 2:
            st.warning("⚠️ Please upload at least two documents.")
            st.session_state.results = None
        elif len(uploaded_files) > MAX_FILES:
            st.error(f"❌ {len(uploaded_files)} files uploaded. The limit is {MAX_FILES} per check.")
            st.session_state.results = None
        else:
            with st.spinner("Analyzing... Please wait."):
                st.session_state.results = run_analysis(
                    uploaded_files, template_files, extra_phrases,
                    (similarity_threshold, copied_threshold), min_block_size,
                )

    st.markdown("---")
    st.info("Created by: **Himanshu Chadha**")

st.title("📄 Document Similarity Checker")
st.markdown(
    "Finds wording copied between CVs. Headings, contact details, dates, common CV phrases "
    "and shared template text are ignored."
)

results = st.session_state.results

if results:
    for name, problem in results["problems"]:
        st.warning(f"⚠️ **{name}** was not included: {problem}.")
    for group in results["duplicates"]:
        st.error("🟰 Identical files uploaded: " + ", ".join(f"**{n}**" for n in group) + ". Checked once.")

if results and "error" in results:
    st.error(results["error"])
elif results:
    names, ids = results["names"], results["ids"]
    analysis, summaries, thresholds = results["analysis"], results["summaries"], results["thresholds"]
    groups = results["groups"]
    counts = {status: sum(1 for s in summaries if s.status == status) for status in (RED, AMBER, GREEN)}

    st.header("📊 Results")
    c = st.columns(5)
    c[0].metric("CVs checked", len(names))
    c[1].metric("🔴 Needs review", counts[RED])
    c[2].metric("🟠 Check", counts[AMBER])
    c[3].metric("🟢 Original", counts[GREEN])
    c[4].metric("Copying groups", len(groups))
    st.caption(
        f"🔴 shares at least {thresholds[1]:.0%} of its wording with another CV, or is at least "
        f"{thresholds[0]:.0%} similar. 🟠 has a shorter matching passage. "
        f"{analysis.boilerplate} template phrases were ignored."
    )

    for g in groups:
        st.error(
            f"👥 **{len(g.docs)} CVs share the same {g.section} text:** "
            + ", ".join(f"{ids[i]} ({names[i]})" for i in g.docs)
        )
        st.code(g.text, language=None, wrap_lines=True)

    st.subheader("🗂️ Triage")
    table = triage_table(names, ids, summaries)
    table["Status"] = [f"{STATUS_ICON[s]} {s}" for s in table["Status"]]
    st.dataframe(
        table, use_container_width=True, hide_index=True,
        column_config={"Original": st.column_config.ProgressColumn(
            "Original wording", format="percent", min_value=0, max_value=1,
        )},
    )

    to_review = [s for s in summaries if s.status != GREEN]
    if to_review:
        st.subheader("🔬 Review a CV")
        options = [
            f"{STATUS_ICON[s.status]} {ids[s.index]} · {names[s.index]} · {s.original:.0%} original"
            for s in to_review
        ]
        choice = st.selectbox("Choose a CV:", options, key="cv_selector")
        s = to_review[options.index(choice)]

        if s.sections:
            st.markdown("**What to change:** " + sections_text(s.sections))
        by_section = defaultdict(list)
        for m in s.matches:
            by_section[m.section].append(m)
        for section, items in by_section.items():
            st.markdown(f"#### {section}")
            for m in items:
                st.caption(
                    f"{m.words} words · also in {ids[m.other]} ({names[m.other]}), {m.other_section}"
                )
                st.code(m.text, language=None, wrap_lines=True)
        st.download_button(
            "⬇️ Feedback sheet for this student (Word)",
            feedback_docx(names[s.index], s),
            f"{names[s.index].rsplit('.', 1)[0]} - feedback.docx",
        )

    flagged = sorted((p for p in analysis.pairs if p.flagged(thresholds)), key=lambda p: -p.score)
    with st.expander(f"All flagged pairs ({len(flagged)})"):
        if flagged:
            st.dataframe(pairs_table(names, flagged, thresholds).drop(columns="Flagged"),
                         use_container_width=True, hide_index=True)
        else:
            st.write("None.")

    with st.expander("Similarity matrix", expanded=len(names) <= 30):
        fig = px.imshow(
            analysis.matrix, x=ids, y=ids, color_continuous_scale="Blues",
            text_auto=".2f" if len(names) <= 30 else False, labels=dict(color="Similarity"),
        )
        fig.update_xaxes(side="top")
        st.plotly_chart(fig, use_container_width=True)

    st.subheader("⬇️ Downloads")
    d1, d2, d3 = st.columns(3)
    common = (names, ids, analysis, summaries, thresholds, results["problems"], results["duplicates"])
    d1.download_button("Excel (all results)", to_excel(*common), "cv-similarity.xlsx", use_container_width=True)
    d2.download_button(
        "PDF summary", to_pdf(*common, groups=groups, run_by=user[1] if user else None),
        "cv-similarity.pdf", use_container_width=True,
    )
    d3.download_button(
        f"Feedback sheets ({len(to_review)} students, ZIP)", feedback_zip(names, summaries),
        "cv-feedback.zip", use_container_width=True, disabled=not to_review,
    )

else:
    st.info("Upload your PDF and DOCX files and click 'Analyze Documents' to begin.")
