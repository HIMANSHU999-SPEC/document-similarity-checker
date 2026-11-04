# app.py
# Checks a batch of PDF and DOCX documents for copied text.
#
# Author: Himanshu Chadha
# Company: London Academy for Applied Technology
#
# Run with: streamlit run app.py
from collections import defaultdict

import pandas as pd
import plotly.express as px
import streamlit as st

from cvchecker.extract import extract
from cvchecker.report import pairs_table, to_excel, to_pdf
from cvchecker.similarity import analyse

MAX_FILE_SIZE_MB = 20
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024
MAX_FILES = 100


def run_analysis(uploaded_files, template_files, thresholds, min_words):
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

    matrix, pairs, boilerplate = analyse([d.text for d in docs], min_words, template_texts)
    return {
        "names": [d.name for d in docs],
        "ids": [f"Doc #{i + 1}" for i in range(len(docs))],
        "matrix": matrix,
        "pairs": pairs,
        "thresholds": thresholds,
        "problems": problems,
        "duplicates": duplicates,
        "boilerplate": boilerplate,
        "templates_used": len(template_texts),
    }


st.set_page_config(layout="wide", page_title="Document Similarity Checker | LAAT")

if "results" not in st.session_state:
    st.session_state.results = None

with st.sidebar:
    st.image("https://laat.ac.uk/assets/img/laat-logo.jpg", width=200)
    st.title("London Academy for Applied Technology")
    st.header("⚙️ Controls")
    uploaded_files = st.file_uploader(
        f"Upload documents (PDF or DOCX, up to {MAX_FILE_SIZE_MB} MB each, {MAX_FILES} files)",
        type=["pdf", "docx"], accept_multiple_files=True,
    )
    with st.expander("CV template (optional)"):
        template_files = st.file_uploader(
            "Upload the blank template students use. Its wording is ignored when scoring.",
            type=["pdf", "docx"], accept_multiple_files=True, key="templates",
        )
    similarity_threshold = st.slider(
        "Similarity threshold", 0.0, 1.0, 0.80, 0.05,
        help="Flags a pair whose overall wording is at least this similar.",
    )
    copied_threshold = st.slider(
        "Copied text threshold", 0.0, 1.0, 0.25, 0.05,
        help="Flags a pair when at least this share of either document appears word for word in the other.",
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
                    uploaded_files, template_files, (similarity_threshold, copied_threshold), min_block_size
                )

    st.markdown("---")
    st.info("Created by: **Himanshu Chadha**")

st.title("📄 Document Similarity Checker")
st.markdown("This tool analyzes a batch of documents to identify copied text and shows exactly what matches.")

results = st.session_state.results

if results:
    for name, problem in results["problems"]:
        st.warning(f"⚠️ **{name}** was not included: {problem}.")
    for group in results["duplicates"]:
        st.error("🟰 Identical files uploaded: " + ", ".join(f"**{n}**" for n in group) + ". Checked once.")

if results and "error" in results:
    st.error(results["error"])
elif results:
    names, ids, pairs = results["names"], results["ids"], results["pairs"]
    matrix, thresholds = results["matrix"], results["thresholds"]
    flagged = sorted((p for p in pairs if p.flagged(thresholds)), key=lambda p: -p.score)

    st.header("📊 Analysis Results")

    st.subheader("✅ Uploaded Documents Reference Key")
    st.dataframe(pd.DataFrame({"Assigned ID": ids, "Original Filename": names}), use_container_width=True)

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Docs Analyzed", len(names))
    col2.metric("Flagged Pairs", len(flagged))
    col3.metric("Total Comparisons", len(pairs))
    col4.metric("Template phrases ignored", results["boilerplate"])

    if flagged:
        st.subheader("🔬 In-Depth Comparison")
        options = [
            f"{ids[p.a]} and {ids[p.b]}: similarity {p.similarity:.0%}, copied {p.copied:.0%}"
            for p in flagged
        ]
        choice = st.selectbox("Choose a flagged pair to inspect:", options, key="pair_selector")
        pair = flagged[options.index(choice)]

        c1, c2, c3 = st.columns(3)
        c1.metric("Similarity", f"{pair.similarity:.0%}")
        c2.metric(f"Share of {ids[pair.a]} found in {ids[pair.b]}", f"{pair.copied_a_in_b:.0%}")
        c3.metric(f"Share of {ids[pair.b]} found in {ids[pair.a]}", f"{pair.copied_b_in_a:.0%}")

        if pair.passages:
            st.markdown(f"**{len(pair.passages)} matching passages** ({names[pair.a]} and {names[pair.b]}):")
            for i, passage in enumerate(pair.passages, 1):
                st.caption(
                    f"Passage {i} · {passage.length} words · word {passage.a_start + 1} in "
                    f"{ids[pair.a]}, word {passage.b_start + 1} in {ids[pair.b]}"
                )
                st.code(passage.text, language=None, wrap_lines=True)
        else:
            st.info("Similar vocabulary, but no identical passage of the minimum length.")

        st.markdown("---")

        st.subheader("🎯 Similarity Hotspots")
        hotspots = defaultdict(list)
        for p in flagged:
            hotspots[ids[p.a]].append(ids[p.b])
            hotspots[ids[p.b]].append(ids[p.a])
        hotspot_df = pd.DataFrame([
            {"Doc ID": d, "Times Flagged": len(m), "Similar To": ", ".join(m)} for d, m in hotspots.items()
        ]).sort_values(by="Times Flagged", ascending=False)
        st.dataframe(hotspot_df, use_container_width=True)

        st.subheader("Flagged pairs")
        table = pairs_table(names, flagged, thresholds).drop(columns="Flagged")
        st.dataframe(table, use_container_width=True)
    else:
        st.success(
            f"✅ No pairs at or above {thresholds[0]:.0%} similarity or {thresholds[1]:.0%} copied text."
        )

    st.subheader("Visual Similarity Matrix")
    fig = px.imshow(
        matrix, x=ids, y=ids, color_continuous_scale="Blues", text_auto=".2f",
        labels=dict(color="Similarity"),
    )
    fig.update_xaxes(side="top")
    fig.update_layout(title_text="Document-to-Document Similarity Scores", title_x=0.5)
    st.plotly_chart(fig, use_container_width=True)

    st.subheader("⬇️ Download report")
    d1, d2 = st.columns(2)
    args = (names, pairs, thresholds, results["problems"], results["duplicates"])
    d1.download_button("Excel (all pairs)", to_excel(*args), "cv-similarity.xlsx", use_container_width=True)
    d2.download_button("PDF summary", to_pdf(*args), "cv-similarity.pdf", use_container_width=True)

else:
    st.info("Upload your PDF and DOCX files and click 'Analyze Documents' to begin.")
