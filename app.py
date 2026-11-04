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

from cvchecker import transcript_ui
from cvchecker.ai import (
    OVERALL_LABEL, VERDICT_LABEL, AIError, Review, Usage, make_client, review_cv, review_many, summarise_check,
)
from cvchecker.auth import require_login
from cvchecker.extract import extract
from cvchecker.feedback import feedback_docx, feedback_zip
from cvchecker.fix_table import fix_rows
from cvchecker.phrases_store import PhraseStore, StoreError, phrase_key, validate_suggestions
from cvchecker.prepare import builtin_phrases, load_phrases
from cvchecker.sharepoint import from_secrets as sharepoint_from_secrets
from cvchecker.report import fix_table_excel, pairs_table, sections_text, to_excel, to_pdf
from cvchecker.similarity import analyse
from cvchecker.triage import AMBER, GREEN, RED, copying_groups, summarise
from cvchecker.ui import hero, inject_css, pill, quote, steps

MAX_FILE_SIZE_MB = 20
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024
MAX_FILES = 100
STATUS_ICON = {RED: "🔴", AMBER: "🟠", GREEN: "🟢"}
ROW_PILL = {"Rewrite needed": "red", "Needs review": "red", "Small fixes": "amber", "Check": "amber", "OK": "green"}


def run_analysis(uploaded_files, template_files, extra_phrases, thresholds, min_words, learned=()):
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

    analysis = analyse([d.text for d in docs], min_words, template_texts,
                       load_phrases(extra=extra_phrases, learned=learned))
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


@st.cache_resource
def sharepoint_client():
    try:
        return sharepoint_from_secrets(st.secrets)
    except Exception:
        return None


def phrase_store():
    try:
        path = (st.secrets.get("phrases") or {}).get("path")
    except Exception:
        path = None
    return PhraseStore(path)


def load_learned(store):
    phrases = store.load()
    if phrases.warning and not st.session_state.get("phrases_warning_shown"):
        st.warning(phrases.warning)
        st.session_state.phrases_warning_shown = True
    return phrases


def run_reviews(client, results):
    """Claude reviews every flagged CV of a fresh check, with a progress bar."""
    pending = [s for s in results["summaries"] if s.status != GREEN]
    if not pending:
        return
    bar = st.progress(0.0, text=f"Claude is reviewing {len(pending)} CV{'s' if len(pending) != 1 else ''}...")
    done = review_many(
        client, pending, results["analysis"],
        on_done=lambda n, total: bar.progress(n / total, text=f"Reviewed {n} of {total}"),
    )
    bar.empty()
    st.session_state.ai_reviews.update(done)
    cost = Usage()
    for r in done.values():
        if isinstance(r, Review):
            cost += r.usage
    st.session_state.ai_usage += cost
    st.session_state.check_cost = (cost, sum(isinstance(r, Review) for r in done.values()))


st.set_page_config(layout="wide", page_title="Document Similarity Checker | LAAT", page_icon="📄")
inject_css()
user = require_login()
client = claude_client()

for key, default in (("results", None), ("ai_reviews", {}), ("ai_summary", None), ("ai_usage", Usage())):
    if key not in st.session_state:
        st.session_state[key] = default

st.set_page_config(layout="wide", page_title="Document Similarity Checker | LAAT", page_icon="📄")
inject_css()
user = require_login()
client = claude_client()
store = phrase_store()
sharepoint = sharepoint_client()
email = user[1] if user else "local user"

for key, default in (("results", None), ("ai_reviews", {}), ("ai_summary", None), ("ai_usage", Usage()),
                     ("review_pending", False), ("check_cost", None), ("phrase_msg", None)):
    if key not in st.session_state:
        st.session_state[key] = default


def phrase_action(action, *args):
    try:
        action(*args)
        return True
    except StoreError as e:
        st.session_state.phrase_msg = ("error", str(e))
        return False


def phrase_sidebar(phrases):
    with st.expander("Common phrases"):
        builtin = builtin_phrases()
        st.caption(f"Built-in ({len(builtin)})")
        with st.container(height=150):
            st.markdown("\n".join(f"- {p}" for p in builtin))
        st.caption(f"Learned ({len(phrases.learned)})")
        if not phrases.learned:
            st.markdown("<span class='cvc-muted'>None yet. Add Claude's suggestions under the results.</span>",
                        unsafe_allow_html=True)
        for n, item in enumerate(phrases.learned):
            text, button = st.columns([4, 1.4])
            text.markdown(f"{item['phrase']}  \n<span class='cvc-muted'>{item.get('added_by', '')} · "
                          f"{item.get('added_at', '')[:10]}</span>", unsafe_allow_html=True)
            if button.button("Remove", key=f"remove-phrase-{n}"):
                if phrase_action(store.remove, item["key"]):
                    st.session_state.phrase_msg = ("ok", f"Removed “{item['phrase']}”.")
                st.rerun()


def suggestions_box(names, analysis, summaries, reviews, phrases):
    known = {phrase_key(p) for p in builtin_phrases()} | phrases.keys
    merged = {}
    for s in summaries:
        review = reviews.get(s.index)
        if isinstance(review, Review):
            for phrase, key in validate_suggestions(review, analysis.docs[s.index], names[s.index], known):
                merged.setdefault(key, [phrase, 0])[1] += 1
    if not merged:
        return
    with st.container(border=True):
        st.markdown(f"**Suggested common phrases ({len(merged)})**")
        st.caption("Claude found these in wording it judged standard. Add one and every check ignores it "
                   "from now on.")
        for key, (phrase, count) in sorted(merged.items(), key=lambda kv: -kv[1][1]):
            text, add, skip = st.columns([6, 1, 1])
            text.markdown(f"“{phrase}” <span class='cvc-muted'>· in {count} CV{'s' if count != 1 else ''}</span>",
                          unsafe_allow_html=True)
            if add.button("Add", key=f"add-{key}", use_container_width=True):
                if phrase_action(store.add, phrase, email):
                    st.session_state.phrase_msg = ("ok", "Saved. Click Analyze Documents again to apply it to this check.")
                st.rerun()
            if skip.button("Ignore", key=f"ignore-{key}", use_container_width=True):
                if phrase_action(store.ignore, phrase, email):
                    st.session_state.phrase_msg = ("ok", f"“{phrase}” won't be suggested again.")
                st.rerun()


def detail_panel(row, names, ids, analysis, summaries, reviews):
    s = next(x for x in summaries if x.index == row.index)
    review = reviews.get(s.index)
    failed = isinstance(review, AIError)
    if not isinstance(review, Review):
        review = None

    with st.container(border=True):
        head, action = st.columns([3, 1])
        badges = [pill(f"Matching: {s.status}", {"Needs review": "red", "Check": "amber"}.get(s.status, "green")),
                  pill(f"{s.original:.0%} original", "blue")]
        if review:
            badges.append(pill(f"Claude: {OVERALL_LABEL[review.overall]}", ROW_PILL[row.status]))
        head.markdown(f"#### {row.cv}<br>" + " ".join(badges), unsafe_allow_html=True)
        if review is None and s.status != GREEN and client is not None and action.button(
            "🤖 Ask Claude again" if failed else "🤖 Ask Claude", use_container_width=True,
        ):
            try:
                review = review_cv(client, s, analysis)
                reviews[s.index] = review
                st.session_state.ai_usage += review.usage
                st.rerun()
            except AIError as e:
                st.warning(str(e))
        action.download_button(
            "⬇️ Feedback sheet (Word)", feedback_docx(names[s.index], s, review),
            f"{row.cv} - feedback.docx", use_container_width=True, key=f"sheet-{s.index}",
        )

        st.markdown(f"**What to change:** {row.what}")
        if review:
            st.markdown(f"<span class='cvc-muted'>{review.staff_note}</span>", unsafe_allow_html=True)
        elif s.sections:
            st.markdown(f"<span class='cvc-muted'>Sections affected: {sections_text(s.sections)}</span>",
                        unsafe_allow_html=True)

        verdicts = {}
        if review:
            for item in review.items:
                verdicts[(item["section"], item["passage"])] = review.verdicts.get(item["id"])
            if review.sections:
                st.caption("Edit Claude's wording if needed. The feedback sheet uses what's shown here.")
            for n, sec in enumerate(review.sections):
                st.markdown(f"**{sec['section']}**")
                sec["problem"] = st.text_area(
                    "What's wrong", sec["problem"], key=f"ai-{s.index}-{n}-problem", height=70)
                sec["what_to_change"] = st.text_area(
                    "What to change", sec["what_to_change"], key=f"ai-{s.index}-{n}-change", height=90)
                questions = st.text_area(
                    "Questions for the student (one per line)", "\n".join(sec["questions"]),
                    key=f"ai-{s.index}-{n}-questions", height=90)
                sec["questions"] = [q.strip() for q in questions.splitlines() if q.strip()]

        if s.matches:
            with st.expander("Matching passages", expanded=review is None):
                by_section = defaultdict(list)
                for m in s.matches:
                    by_section[m.section].append(m)
                for section, items in by_section.items():
                    st.markdown(f"**{section}**")
                    for m in items:
                        verdict = verdicts.get((m.section, m.text))
                        note = f" · Claude: {VERDICT_LABEL[verdict[0]]}, {verdict[1]}" if verdict else ""
                        quote(m.text, f"{m.words} words · also in {ids[m.other]} ({names[m.other]}), "
                                      f"{m.other_section}{note}")


def details_section(names, ids, analysis, summaries, groups, thresholds, reviews, results):
    flagged = sorted((p for p in analysis.pairs if p.flagged(thresholds)), key=lambda p: -p.score)
    with st.expander("Details"):
        st.markdown(f"**Copying groups ({len(groups)})**")
        if not groups:
            st.caption("No passage is shared by three or more CVs.")
        for g in groups:
            quote(g.text, f"{len(g.docs)} CVs share this {g.section} text: "
                          + ", ".join(f"{ids[i]} ({names[i]})" for i in g.docs))

        st.markdown(f"**All flagged pairs ({len(flagged)})**")
        if flagged:
            st.dataframe(pairs_table(names, flagged, thresholds).drop(columns="Flagged"),
                         use_container_width=True, hide_index=True)
        else:
            st.caption("No pairs reach either threshold.")
        fig = px.imshow(
            analysis.matrix, x=ids, y=ids, color_continuous_scale="Blues",
            text_auto=".2f" if len(names) <= 30 else False, labels=dict(color="Similarity"),
        )
        fig.update_xaxes(side="top")
        fig.update_layout(margin=dict(l=0, r=0, t=30, b=0), title_text="Similarity matrix", title_x=0)
        st.plotly_chart(fig, use_container_width=True)

        common = (names, ids, analysis, summaries, thresholds, results["problems"], results["duplicates"])
        d1, d2 = st.columns(2)
        d1.download_button("Full Excel workbook", to_excel(*common), "cv-similarity.xlsx", use_container_width=True)
        d2.download_button("PDF summary", to_pdf(*common, groups=groups, run_by=email if user else None),
                           "cv-similarity.pdf", use_container_width=True)

        if client is not None and any(isinstance(r, Review) for r in reviews.values()):
            if st.button("Summarise this check for a staff meeting"):
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


def check_page():
    phrases = load_learned(store)
    with st.sidebar:
        st.markdown("### Check CVs")
        uploaded_files = st.file_uploader(
            f"PDF or Word, up to {MAX_FILE_SIZE_MB} MB each, {MAX_FILES} files",
            type=["pdf", "docx"], accept_multiple_files=True,
        )
        with st.expander("Ignore common wording"):
            template_files = st.file_uploader(
                "Blank CV template students use. Its wording is ignored.",
                type=["pdf", "docx"], accept_multiple_files=True, key="templates",
            )
            extra_phrases = st.text_area(
                "Extra phrases to ignore, one per line",
                help="Added to the built-in and learned phrases, for this check only.",
            )
        phrase_sidebar(phrases)
        with st.expander("Settings"):
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
                st.warning("Please upload at least two documents.")
                st.session_state.results = None
            elif len(uploaded_files) > MAX_FILES:
                st.error(f"{len(uploaded_files)} files uploaded. The limit is {MAX_FILES} per check.")
                st.session_state.results = None
            else:
                st.session_state.ai_reviews, st.session_state.ai_summary = {}, None
                st.session_state.check_cost = None
                with st.spinner("Analyzing..."):
                    st.session_state.results = run_analysis(
                        uploaded_files, template_files, extra_phrases,
                        (similarity_threshold, copied_threshold), min_block_size,
                        [p["phrase"] for p in phrases.learned],
                    )
                st.session_state.review_pending = "error" not in st.session_state.results

    hero(
        "Document Similarity Checker",
        "Finds wording copied between CVs and says what each student needs to change.",
        user[0] if user else None,
    )

    message = st.session_state.phrase_msg
    if message:
        (st.error if message[0] == "error" else st.toast)(message[1])
        st.session_state.phrase_msg = None

    results = st.session_state.results
    if results and (results["problems"] or results["duplicates"]):
        issues = len(results["problems"]) + len(results["duplicates"])
        with st.expander(f"⚠️ {issues} file{'s' if issues != 1 else ''} need{'' if issues != 1 else 's'} attention",
                         expanded=issues <= 3):
            for name, problem in results["problems"]:
                st.markdown(f"**{name}** wasn't included: {problem}.")
            for group in results["duplicates"]:
                st.markdown("Identical files, checked once: " + ", ".join(f"**{n}**" for n in group))

    if not results:
        steps([
            ("Upload CVs", f"Add up to {MAX_FILES} PDF or Word CVs in the sidebar. Optionally add the blank template."),
            ("Analyze", "Matching runs on this server, then Claude reviews every flagged CV."),
            ("Read the table and download feedback sheets", "One row per CV says what to change."),
        ])
        return
    if "error" in results:
        st.error(results["error"])
        return

    if st.session_state.review_pending:
        st.session_state.review_pending = False
        if client is not None:
            run_reviews(client, results)

    names, ids = results["names"], results["ids"]
    analysis, summaries, thresholds = results["analysis"], results["summaries"], results["thresholds"]
    groups, reviews = results["groups"], st.session_state.ai_reviews
    rows = fix_rows(names, ids, summaries, reviews)

    counted = {}
    for r in rows:
        counted.setdefault((r.rank, r.icon, r.status), 0)
        counted[(r.rank, r.icon, r.status)] += 1
    cols = st.columns(1 + len(counted))
    cols[0].metric("CVs checked", len(rows))
    for col, ((_, icon, status), n) in zip(cols[1:], sorted(counted.items())):
        col.metric(f"{icon} {status}", n)

    failed = defaultdict(list)
    for s in summaries:
        if isinstance(reviews.get(s.index), AIError):
            failed[str(reviews[s.index])].append(ids[s.index])
    for message, doc_ids in failed.items():
        st.warning(f"Claude couldn't review {', '.join(doc_ids)}. {message} Those rows use the matching results.")
    if client is None:
        st.caption("Claude isn't turned on, so the table uses the matching results. "
                   "Add your Claude API key under [anthropic] in secrets.toml for plain-English advice.")

    table = pd.DataFrame([{"Doc ID": r.doc_id, "CV": r.cv, "Status": f"{r.icon} {r.status}",
                           "What to change": r.what} for r in rows])
    event = st.dataframe(
        table, hide_index=True, use_container_width=True, on_select="rerun", selection_mode="single-row",
        key="fix_table",
        column_config={
            "Doc ID": st.column_config.TextColumn(width=70),
            "CV": st.column_config.TextColumn(width=170),
            "Status": st.column_config.TextColumn(width=140),
            "What to change": st.column_config.TextColumn(width=760),
        },
    )

    flagged_rows = [r for r in rows if r.status != "OK"]
    d1, d2 = st.columns(2)
    d1.download_button("Download table (Excel)", fix_table_excel(rows), "what-to-change.xlsx",
                       use_container_width=True)
    d2.download_button(f"Download all feedback sheets ({len(flagged_rows)}, ZIP)",
                       feedback_zip(names, summaries, reviews), "cv-feedback.zip",
                       use_container_width=True, disabled=not any(s.status != GREEN for s in summaries))
    if st.session_state.check_cost:
        cost, n = st.session_state.check_cost
        st.caption(f"Claude: about ${cost.cost:.2f} for {n} CV{'s' if n != 1 else ''}")

    suggestions_box(names, analysis, summaries, reviews, phrases)

    selected = event.selection.rows if event and event.selection else []
    if selected:
        detail_panel(rows[selected[0]], names, ids, analysis, summaries, reviews)
    else:
        st.caption("Select a row to see the copied text and the full feedback.")

    details_section(names, ids, analysis, summaries, groups, thresholds, reviews, results)

pages = [
    st.Page(check_page, title="Check CVs", icon="🔍", default=True),
    st.Page(lambda: transcript_ui.render(client, user, [p["phrase"] for p in store.load().learned], sharepoint),
            title="Transcript to CV", icon="📝", url_path="transcript"),
]
st.navigation(pages, position="top").run()

with st.sidebar:
    st.divider()
    if user:
        st.caption(f"Signed in as **{user[0]}**  \n{user[1]}")
        st.button("Sign out", on_click=st.logout, use_container_width=True)
    st.caption("London Academy for Applied Technology · Created by Himanshu Chadha")
