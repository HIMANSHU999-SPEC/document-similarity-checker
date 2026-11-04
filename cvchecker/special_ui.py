import pandas as pd
import streamlit as st

from cvchecker.fixer import fix_batch, fixed_zip, log_event, record, recent_failures, test_run
from cvchecker.special import MAX_ATTEMPTS, can_use, code_matches
from cvchecker.ui import quote


def sidebar_button(config, email, log_dir):
    if not can_use(email, config):
        return
    if st.session_state.get("special_unlocked"):
        if st.button("🔓 Lock special actions", use_container_width=True):
            st.session_state.special_unlocked = False
            st.rerun()
        return
    if st.button("🔒 Special actions", use_container_width=True):
        unlock_dialog(config, email, log_dir)


@st.dialog("Special actions")
def unlock_dialog(config, email, log_dir):
    if recent_failures(log_dir, email) >= MAX_ATTEMPTS:
        st.error("Too many wrong codes. Try again in an hour.")
        return
    code = st.text_input("Access code", type="password")
    if st.button("Unlock", type="primary"):
        if code_matches(code, config):
            log_event(log_dir, email, "unlock")
            st.session_state.special_unlocked = True
            st.rerun()
        log_event(log_dir, email, "wrong code")
        left = MAX_ATTEMPTS - recent_failures(log_dir, email)
        st.error(f"Wrong code. {left} tr{'y' if left == 1 else 'ies'} left." if left > 0
                 else "Too many wrong codes. Try again in an hour.")


def _result(fix):
    if fix.error:
        return "⚠️ Claude error"
    if not fix.changes:
        return "No copied wording to rewrite"
    if fix.text != fix.tested:
        return "✏️ Edited: re-run the test"
    return "⚠️ Still matches: fix by hand" if fix.still_matches else "✅ Unique"


def fix_section(client, results, rows, reviews, email, log_dir, original_report):
    if not st.session_state.get("special_unlocked"):
        return
    names, ids = results["names"], results["ids"]
    with st.container(border=True):
        st.markdown("#### 🔒 Special actions: fix copied sections")
        st.caption("Claude rewrites only the copied passages of each chosen CV, keeping the applicant's facts. "
                   "Everything else stays as it is. The batch is then re-checked, including fixed CVs against each other.")
        if client is None:
            st.caption("Add the Claude API key to use this.")
            return
        options = {f"{r.doc_id} · {r.cv}": r.index for r in rows if r.status != "OK"}
        if not options:
            st.caption("No CV in this check needs fixing.")
            return
        chosen = st.multiselect("CVs to fix", list(options), default=list(options), key="fix_choice")
        st.caption(f"About ${0.04 * len(chosen):.2f} for {len(chosen)} CV{'s' if len(chosen) != 1 else ''}.")
        if st.button("Fix selected CVs with Claude", type="primary", disabled=not chosen):
            bar = st.progress(0.0, text="Claude is rewriting the copied passages...")
            fixes = fix_batch(client, results, [options[c] for c in chosen], reviews,
                              on_done=lambda n, total: bar.progress(n / total, text=f"Rewritten {n} of {total}"))
            bar.empty()
            st.session_state.fixes = fixes
            for f in fixes.values():
                st.session_state.ai_usage += f.usage
            log_event(log_dir, email, "fix", f"{len(fixes)} CVs")

        fixes = st.session_state.get("fixes")
        if not fixes:
            return
        table = pd.DataFrame([{
            "CV": f"{ids[i]} · {names[i].rsplit('.', 1)[0]}",
            "Original before": f.before, "Original after": f.after if f.after is not None else 0.0,
            "Result": _result(f), "Passages rewritten": len(f.changes),
            "Questions for the applicant": " · ".join(f.questions),
        } for i, f in sorted(fixes.items())])
        st.dataframe(table, hide_index=True, use_container_width=True, column_config={
            "Original before": st.column_config.ProgressColumn(format="percent", min_value=0, max_value=1, width=130),
            "Original after": st.column_config.ProgressColumn(format="percent", min_value=0, max_value=1, width=130),
        })

        labels = {f"{ids[i]} · {names[i]}": i for i, f in sorted(fixes.items()) if f.changes}
        if labels:
            pick = st.selectbox("Check a fixed CV", list(labels), key="fix_pick")
            fix = fixes[labels[pick]]
            for old, new in fix.changes:
                left, right = st.columns(2)
                with left:
                    quote(old, "Copied wording")
                with right:
                    quote(new, "Rewritten")
            fix.text = st.text_area("Full fixed CV (edit if needed)", fix.text, height=320,
                                    key=f"fixtext-{labels[pick]}")
            if fix.questions:
                st.caption("Ask the applicant: " + " · ".join(fix.questions))

        stale = [i for i, f in fixes.items() if f.changes and f.text != f.tested]
        a, b = st.columns(2)
        if a.button("Re-run the test", disabled=not stale, use_container_width=True):
            _, after = test_run(results, {i: f.text for i, f in fixes.items()})
            record(fixes, after)
            st.rerun()
        a.caption("Re-checks the batch after your edits." if stale else "The results above are up to date.")
        b.download_button(
            "⬇️ Download fixed CVs (ZIP)", fixed_zip(names, ids, fixes, original_report()), "fixed-cvs.zip",
            type="primary", use_container_width=True, disabled=bool(stale) or not labels,
        )
        b.caption("CVs/ holds the CVs ready to upload. Reports (staff only)/ holds the change report "
                  "and the original check.")
