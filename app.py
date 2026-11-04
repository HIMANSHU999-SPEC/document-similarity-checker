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

from cvchecker.ai import (
    OVERALL_LABEL, OVERALL_ORDER, VERDICT_LABEL, AIError, Review, Usage, make_client, review_cv, review_many,
    summarise_check,
)
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


@st.cache_resource
def claude_client():
    try:
        key = (st.secrets.get("anthropic") or {}).get("api_key", "")
    except Exception:
        key = ""
    return make_client(key) if key and not key.startswith("sk-ant-...") else None


def review_rank(s, reviews):
    review = reviews.get(s.index)
    if isinstance(review, Review):
        return {0: 0, 1: 1, 2: 3}[OVERALL_ORDER[review.overall]], s.original
    return (4 if s.status == GREEN else 2), s.original


st.set_page_config(layout="wide", page_title="Document Similarity Checker | LAAT")
user = require_login()
client = claude_client()

for key, default in (("results", None), ("ai_reviews", {}), ("ai_summary", None), ("ai_usage", Usage())):
    if key not in st.session_state:
        st.session_state[key] = default

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
            st.session_state.ai_reviews, st.session_state.ai_summary = {}, None
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

    reviews = st.session_state.ai_reviews
    to_review = [s for s in summaries if s.status != GREEN]

    st.subheader("🤖 Claude review")
    if client is None:
        st.caption("Add your Claude API key under [anthropic] in secrets.toml to turn on Claude reviews.")
    elif to_review:
        pending = [s for s in to_review if not isinstance(reviews.get(s.index), Review)]
        if pending and st.button(
            f"Ask Claude which of the {len(pending)} flagged CVs need changing "
            f"(about ${0.015 * len(pending):.2f})", type="primary",
        ):
            bar = st.progress(0.0, text="Claude is reviewing the flagged CVs...")
            done = review_many(
                client, pending, analysis,
                on_done=lambda n, total: bar.progress(n / total, text=f"Reviewed {n} of {total}"),
            )
            reviews.update(done)
            for r in done.values():
                if isinstance(r, Review):
                    st.session_state.ai_usage += r.usage
            bar.empty()
        reviewed = [reviews[s.index] for s in to_review if isinstance(reviews.get(s.index), Review)]
        failed = [s for s in to_review if isinstance(reviews.get(s.index), AIError)]
        if reviewed:
            tally = {label: sum(1 for r in reviewed if r.overall == key) for key, label in OVERALL_LABEL.items()}
            st.markdown(
                f"Claude reviewed **{len(reviewed)}** CVs: **{tally['Rewrite needed']}** need rewriting, "
                f"**{tally['Small fixes']}** need small fixes, **{tally['No action']}** need no action "
                "(the matches are template or stock wording). The triage list below is now in that order."
            )
        errors = defaultdict(list)
        for s in failed:
            errors[str(reviews[s.index])].append(ids[s.index])
        for message, doc_ids in errors.items():
            st.warning(f"Claude couldn't review {', '.join(doc_ids)}. {message}")
        if reviewed and st.button("Summarise this check for a staff meeting"):
            try:
                data, usage = summarise_check(client, ids, summaries, groups, reviews)
                st.session_state.ai_summary = data
                st.session_state.ai_usage += usage
            except AIError as e:
                st.warning(str(e))
        if st.session_state.ai_summary:
            st.info(st.session_state.ai_summary["summary"] + "\n\n" + "\n".join(
                f"{i}. {p}" for i, p in enumerate(st.session_state.ai_summary["priorities"], 1)
            ))
        if st.session_state.ai_usage.cost:
            st.caption(f"Claude cost so far in this session: about ${st.session_state.ai_usage.cost:.2f}")
    else:
        st.caption("Nothing flagged, so there's nothing for Claude to review.")

    summaries = sorted(summaries, key=lambda s: review_rank(s, reviews))
    to_review = [s for s in summaries if s.status != GREEN]

    st.subheader("🗂️ Triage")
    table = triage_table(names, ids, summaries)
    table["Status"] = [f"{STATUS_ICON[s]} {s}" for s in table["Status"]]
    if reviews:
        table.insert(1, "Claude", [
            OVERALL_LABEL[reviews[s.index].overall] if isinstance(reviews.get(s.index), Review) else ""
            for s in summaries
        ])
    st.dataframe(
        table, use_container_width=True, hide_index=True,
        column_config={"Original": st.column_config.ProgressColumn(
            "Original wording", format="percent", min_value=0, max_value=1,
        )},
    )

    if to_review:
        st.subheader("🔬 Review a CV")
        options = [
            f"{STATUS_ICON[s.status]} {ids[s.index]} · {names[s.index]} · {s.original:.0%} original"
            for s in to_review
        ]
        choice = st.selectbox("Choose a CV:", options, key="cv_selector")
        s = to_review[options.index(choice)]

        review = reviews.get(s.index)
        if not isinstance(review, Review):
            review = None
            if client is not None and st.button("🤖 Ask Claude what to change in this CV"):
                try:
                    review = review_cv(client, s, analysis)
                    reviews[s.index] = review
                    st.session_state.ai_usage += review.usage
                except AIError as e:
                    st.warning(str(e))

        if review:
            st.markdown(f"**Claude: {OVERALL_LABEL[review.overall]}.** {review.staff_note}")
        elif s.sections:
            st.markdown("**Sections affected:** " + sections_text(s.sections))

        verdict_by_start = {}
        if review:
            for item in review.items:
                verdict_by_start[(item["section"], item["passage"])] = review.verdicts.get(item["id"])
            if review.sections:
                st.caption("Edit Claude's wording below if needed. The feedback sheet uses what's shown here.")
            for n, sec in enumerate(review.sections):
                st.markdown(f"#### {sec['section']}")
                sec["problem"] = st.text_area(
                    "What's wrong", sec["problem"], key=f"ai-{s.index}-{n}-problem", height=70)
                sec["what_to_change"] = st.text_area(
                    "What to change", sec["what_to_change"], key=f"ai-{s.index}-{n}-change", height=90)
                questions = st.text_area(
                    "Questions for the student (one per line)", "\n".join(sec["questions"]),
                    key=f"ai-{s.index}-{n}-questions", height=90)
                sec["questions"] = [q.strip() for q in questions.splitlines() if q.strip()]

        with st.expander("Matching passages", expanded=review is None):
            by_section = defaultdict(list)
            for m in s.matches:
                by_section[m.section].append(m)
            for section, items in by_section.items():
                st.markdown(f"##### {section}")
                for m in items:
                    verdict = verdict_by_start.get((m.section, m.text))
                    note = f" · Claude: {VERDICT_LABEL[verdict[0]]}, {verdict[1]}" if verdict else ""
                    st.caption(
                        f"{m.words} words · also in {ids[m.other]} ({names[m.other]}), {m.other_section}{note}"
                    )
                    st.code(m.text, language=None, wrap_lines=True)
        st.download_button(
            "⬇️ Feedback sheet for this student (Word)",
            feedback_docx(names[s.index], s, review),
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
        f"Feedback sheets ({len(to_review)} students, ZIP)", feedback_zip(names, summaries, reviews),
        "cv-feedback.zip", use_container_width=True, disabled=not to_review,
    )

else:
    st.info("Upload your PDF and DOCX files and click 'Analyze Documents' to begin.")
