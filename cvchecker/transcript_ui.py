import pandas as pd
import streamlit as st

from cvchecker import transcript as tr
from cvchecker.ai import AIError
from cvchecker.cvdraft import CV_MARKER, build_docx, cv_text, draft_cv
from cvchecker.extract import extract
from cvchecker.names import MATCH, MISMATCH, NOT_SAID, PARTIAL, check_names, first_line, matching_cvs, name_parts
from cvchecker.sharepoint import SharePointError, current_intake, safe_name
from cvchecker.prepare import load_phrases
from cvchecker.similarity import analyse
from cvchecker.ui import hero, pill, quote

NAME_PILL = {MATCH: "green", PARTIAL: "amber", NOT_SAID: "amber", MISMATCH: "red"}


def originality(text, others, min_words=10, learned=()):
    """Share of the draft found word for word in any other CV, with the passages."""
    if not others:
        return None
    result = analyse([text] + others, min_words, phrases=load_phrases(learned=learned))
    pairs = [p for p in result.pairs if p.a == 0]
    best = max(pairs, key=lambda p: p.copied_a_in_b) if pairs else None
    passages = [s.text_a for p in pairs for s in p.passages]
    return (best.copied_a_in_b if best else 0.0), passages


def _lines_editor(label, items, key, height=110):
    value = st.text_area(label, "\n".join(items), key=key, height=height)
    return [v.strip() for v in value.splitlines() if v.strip()]


def _edit_draft(draft, key):
    """Editable form for the draft. Returns the edited draft (evidence kept from Claude)."""
    d = draft
    c1, c2 = st.columns(2)
    d["email"] = c1.text_input("Email", d["email"], key=f"{key}-email")
    d["phone"] = c2.text_input("Phone", d["phone"], key=f"{key}-phone")
    d["profile"]["text"] = st.text_area("Profile", d["profile"]["text"], key=f"{key}-profile", height=120)

    texts = _lines_editor("Skills (one per line)", [s["text"] for s in d["skills"]], f"{key}-skills")
    d["skills"] = [{"text": t, "evidence": next((s["evidence"] for s in d["skills"] if s["text"] == t), "")}
                   for t in texts]

    st.markdown("**Experience**")
    if not d["experience"]:
        st.caption("No work or volunteering experience mentioned.")
    for n, e in enumerate(d["experience"]):
        with st.container(border=True):
            a, b, c = st.columns([2, 2, 1])
            e["role"] = a.text_input("Role", e["role"], key=f"{key}-exp{n}-role")
            e["organisation"] = b.text_input("Organisation", e["organisation"], key=f"{key}-exp{n}-org")
            e["dates"] = c.text_input("Dates", e["dates"], key=f"{key}-exp{n}-dates")
            e["points"] = _lines_editor("What they did (one per line)", e["points"], f"{key}-exp{n}-points", 90)

    if st.button("+ Add experience", key=f"{key}-add-exp"):
        d["experience"].append({"role": "", "organisation": "", "dates": "", "points": [], "evidence": "Added by staff"})
        st.rerun()

    st.markdown("**Education**")
    if not d["education"]:
        st.caption("No qualifications mentioned.")
    for n, e in enumerate(d["education"]):
        a, b, c = st.columns([2, 2, 1])
        e["qualification"] = a.text_input("Qualification", e["qualification"], key=f"{key}-edu{n}-q")
        e["institution"] = b.text_input("Institution", e["institution"], key=f"{key}-edu{n}-i")
        e["dates"] = c.text_input("Dates", e["dates"], key=f"{key}-edu{n}-d")
    if st.button("+ Add qualification", key=f"{key}-add-edu"):
        d["education"].append({"qualification": "", "institution": "", "dates": "", "evidence": "Added by staff"})
        st.rerun()

    for field, label in (("achievements", "Achievements"), ("interests", "Interests")):
        texts = _lines_editor(f"{label} (one per line)", [x["text"] for x in d[field]], f"{key}-{field}", 90)
        d[field] = [{"text": t, "evidence": next((x["evidence"] for x in d[field] if x["text"] == t), "")}
                    for t in texts]
    return d


def _evidence(draft):
    rows = [("Profile", draft["profile"]["text"], draft["profile"]["evidence"])]
    rows += [("Skill", s["text"], s["evidence"]) for s in draft["skills"]]
    rows += [("Experience", f"{e['role']} {e['organisation']}".strip(), e["evidence"]) for e in draft["experience"]]
    rows += [("Education", e["qualification"], e["evidence"]) for e in draft["education"]]
    rows += [("Achievement", a["text"], a["evidence"]) for a in draft["achievements"]]
    rows += [("Interest", i["text"], i["evidence"]) for i in draft["interests"]]
    return pd.DataFrame([r for r in rows if r[1]], columns=["Part", "In the CV", "Where it came from"])


def render(client, user, learned=(), sharepoint=None):
    hero("Transcript to CV",
         "Turn a student's part of a Teams interview recording into a CV draft, with every line traced back "
         "to what they said.", user[0] if user else None)

    if client is None:
        st.info("Add your Claude API key under [anthropic] in secrets.toml to create CVs from transcripts.")
        return

    st.markdown("#### 1. Upload the Teams transcript")
    upload = st.file_uploader("Teams transcript (.vtt or .docx, as downloaded from Teams)",
                              type=["vtt", "docx", "txt"], key="transcript_file")
    if not upload:
        st.caption("In Teams, open the recording, choose Transcript, then Download as .vtt or .docx.")
        return
    lines = tr.load(upload.name, upload.getvalue())
    if not lines:
        st.error("No speaker lines were found in this file. Check it's a Teams transcript.")
        return
    stats = tr.speakers(lines)
    st.caption(f"{len(lines)} lines, {len(stats)} speakers, recording length {tr.format_time(lines[-1].end)}.")

    st.markdown("#### 2. Choose the student's part")
    guess = tr.likely_interviewer(lines)
    interviewers = st.multiselect(
        "Interviewer (their questions are context only, nothing they say goes into the CV)",
        list(stats), default=[guess] if guess else [], key="interviewers",
    )
    others = {k: v for k, v in stats.items() if k not in interviewers}
    if others:
        st.dataframe(pd.DataFrame([
            {"Speaker": k, "Words": v[0], "From": tr.format_time(v[1]), "To": tr.format_time(v[2])}
            for k, v in others.items()
        ]), hide_index=True, use_container_width=True)
        fill = st.selectbox("Fill the times from a speaker (optional)", ["—"] + list(others), key="fill_from")
        if fill != "—" and st.session_state.get("filled_from") != fill:
            st.session_state.t_start = tr.format_time(max(0, others[fill][1] - 30))
            st.session_state.t_end = tr.format_time(others[fill][2] + 1)
            st.session_state.filled_from = fill

    a, b, c = st.columns([2, 1, 1])
    student = a.text_input("Student's full name (as it should appear on the CV)", key="student_name")
    start_s = b.text_input("Start time", key="t_start", placeholder="14:30")
    end_s = c.text_input("End time", key="t_end", placeholder="27:10")
    if not (student and start_s and end_s):
        st.caption("Enter the name and the start and end time of this student's part, as mm:ss or h:mm:ss.")
        return
    try:
        start, end = tr.parse_time(start_s), tr.parse_time(end_s)
    except ValueError:
        st.error("Times must look like 14:30 or 1:02:03.")
        return
    if end <= start:
        st.error("The end time must be after the start time.")
        return
    part = tr.window(lines, start, end)
    if not any(ln.speaker not in interviewers for ln in part):
        st.warning("Nobody but the interviewer speaks in that time window. Check the times.")
        return
    text, mapping = tr.redact(tr.labelled(part, set(interviewers)))
    student_words = sum(len(ln.text.split()) for ln in part if ln.speaker not in interviewers)
    with st.expander(f"Preview what Claude will read ({len(part)} lines, {student_words} words from the student)"):
        st.caption("Emails and phone numbers are replaced before sending, and put back afterwards.")
        st.text(text[:6000] + ("\n…" if len(text) > 6000 else ""))

    existing, source_index, source_label = existing_cv_section(student)

    template = st.file_uploader("LAAT CV template (optional, .docx). Put {{CV}} where the CV should go.",
                                type=["docx"], key="cv_template")

    key = f"draft::{upload.name}::{start}::{end}::{source_label}"
    action = "📝 Update the CV with Claude (about $0.05)" if existing else "📝 Create CV draft with Claude (about $0.04)"
    if st.button(action, type="primary"):
        with st.spinner("Claude is reading the transcript" + (" and the CV..." if existing else "...")):
            try:
                if existing:
                    combined, mapping = tr.redact(tr.labelled(part, set(interviewers)) + CV_MARKER + existing)
                    sent_transcript, sent_cv = combined.split(CV_MARKER, 1)
                    data, usage = draft_cv(client, sent_transcript, sent_cv)
                else:
                    data, usage = draft_cv(client, text)
                st.session_state[key] = {"draft": tr.restore(data, mapping), "mapping": mapping}
                st.session_state.ai_usage += usage
            except AIError as e:
                st.warning(str(e))
    saved = st.session_state.get(key)
    if not saved:
        return
    draft = saved["draft"]

    st.markdown("#### 3. Check and edit the draft")
    check = check_names(student, draft["name_as_said"])
    st.markdown(f"**Name check** {pill(check.result, NAME_PILL[check.result])}  \n{check.message}",
                unsafe_allow_html=True)
    if draft.get("conflicts"):
        with st.container(border=True):
            st.markdown(f"**The CV and the interview disagree ({len(draft['conflicts'])})** "
                        + pill("Staff to decide", "amber"), unsafe_allow_html=True)
            st.caption("The draft keeps the CV's version. Edit it below if the interview is right.")
            st.dataframe(pd.DataFrame([{"About": c["topic"], "CV says": c["cv_says"],
                                        "Interview says": c["interview_says"]} for c in draft["conflicts"]]),
                         hide_index=True, use_container_width=True)
    if draft["missing"]:
        with st.container(border=True):
            st.markdown("**Ask the student to complete the CV**")
            for q in draft["missing"]:
                st.markdown(f"- {q}")

    draft = _edit_draft(draft, key)
    with st.expander("Where each line came from"):
        st.dataframe(_evidence(draft), hide_index=True, use_container_width=True)

    st.markdown("#### 4. Originality and download")
    results = st.session_state.get("results") or {}
    batch = [d.text for i, d in enumerate(results["analysis"].docs) if i != source_index] \
        if results.get("analysis") else []
    earlier = [v["text"] for k, v in st.session_state.get("made_cvs", {}).items() if k != key]
    body = cv_text(draft)
    found = originality(body, batch + earlier, learned=learned)
    if found is None:
        st.caption("Run a CV check on the Check CVs page first to compare this draft against that batch.")
    else:
        share, passages = found
        kind = "green" if share < 0.1 else "amber" if share < 0.25 else "red"
        st.markdown(f"**Originality** {pill(f'{1 - share:.0%} original', kind)}  \n"
                    f"<span class='cvc-muted'>Compared with {len(batch)} CVs from the last check and "
                    f"{len(earlier)} CVs created here.</span>", unsafe_allow_html=True)
        for p in passages[:5]:
            quote(p, "Also appears in another CV")

    allowed, note = check.result == MATCH, ""
    if check.result in (PARTIAL, NOT_SAID):
        allowed = st.checkbox("I've checked the student's name is correct", key=f"{key}-confirm")
    elif check.result == MISMATCH:
        reason = st.text_input("To save anyway, give a reason (kept in the file's notes)", key=f"{key}-reason")
        allowed = bool(reason.strip())
        note = f"Name check overridden by {user[1] if user else 'staff'}: {reason.strip()}"

    filename = f"{student.strip()} CV.docx"
    data = build_docx(student.strip(), draft, template.getvalue() if template else None, note)
    if st.download_button(f"⬇️ Download {filename}", data, filename, type="primary", disabled=not allowed):
        st.session_state.setdefault("made_cvs", {})[key] = {"text": body, "name": student.strip()}
    save_section(sharepoint, student.strip(), filename, data, allowed, key, body)


def existing_cv_section(student):
    """Optional existing CV to update. Returns (text, index in the last check or None, label for caching)."""
    st.markdown("#### Existing CV (optional)")
    results = st.session_state.get("results") or {}
    names, texts = results.get("names") or [], results.get("texts") or []
    modes = ["Create a new CV"] + (["Use a CV from the last check"] if names else []) + ["Upload the student's CV"]
    mode = st.radio("Start from", modes, horizontal=True, key="cv_source",
                    help="Updating keeps everything accurate in the CV and adds what the student said.")
    existing, index, label = "", None, "new"
    if mode == "Use a CV from the last check":
        found = matching_cvs(student, names, texts)
        order = found + [i for i in range(len(names)) if i not in found]
        labels = [names[i] + ("  (name matches)" if i in found else "") for i in order]
        pick = st.selectbox("Student's CV", labels, index=0 if found else None, key="cv_pick",
                            placeholder="Choose the student's CV")
        if not found:
            st.caption(f"No CV in the last check is named {student}. Pick the right one, or upload it.")
        if pick is not None:
            index = order[labels.index(pick)]
            existing, label = texts[index], f"batch:{names[index]}"
    elif mode == "Upload the student's CV":
        uploaded = st.file_uploader("Student's current CV (PDF or Word)", type=["pdf", "docx"], key="cv_existing")
        if uploaded:
            item = extract(uploaded.name, uploaded.getvalue())
            if not item.ok:
                st.error(f"{uploaded.name} couldn't be used: {item.problem}.")
            else:
                existing, label = item.text, f"upload:{item.sha256[:12]}"
    if existing:
        on_cv = first_line(existing)
        check = check_names(student, on_cv)
        kind = NAME_PILL[MISMATCH if check.result == NOT_SAID else check.result]
        st.markdown(f"Name on the CV: **{on_cv}** {pill(check.result if check.result != NOT_SAID else 'No name found', kind)}",
                    unsafe_allow_html=True)
        if check.result != MATCH:
            st.warning("The name on this CV doesn't match the student. Using the wrong CV would put another "
                       "person's details into this student's CV.")
            if not st.checkbox(f"This is {student}'s CV, use it anyway", key=f"cv_confirm::{label}"):
                return "", None, "new"
    return existing, index, label


def folder_choices(student, folders):
    """Existing folders for this student: exact name matches first, then folders that look alike."""
    wanted = sorted(name_parts(student))
    exact = [f for f in folders if sorted(name_parts(f)) == wanted]
    alike = [f for f in folders if f not in exact and len(set(name_parts(f)) & set(wanted)) >= min(2, len(wanted))]
    return exact, alike


def save_section(sharepoint, student, filename, data, allowed, key, body):
    st.markdown("#### 5. Save to SharePoint")
    if sharepoint is None:
        st.caption("Add [sharepoint] hostname and site_path to secrets.toml to save CVs straight to SharePoint.")
        return
    with st.expander("SharePoint connection"):
        st.caption(f"Site: {sharepoint.site_url} · folder: {sharepoint.folder}")
        if st.button("Test SharePoint connection", key="sp_test"):
            try:
                st.success(f"Connected to {sharepoint.check()}.")
            except SharePointError as e:
                st.error(str(e))
    intake = st.text_input("Intake folder", current_intake(), key="sp_intake")
    intake = safe_name(intake)
    cache = st.session_state.setdefault("sp_folders", {})
    if intake not in cache or st.button("Refresh folder list", key="sp_refresh"):
        try:
            cache[intake] = sharepoint.list_folders(sharepoint.folder, intake)
        except SharePointError as e:
            st.error(str(e))
            return
    exact, alike = folder_choices(student, cache[intake])
    new_folder = safe_name(student)
    options = exact + alike + ([] if new_folder in exact else [f"New folder: {new_folder}"])
    if alike:
        st.warning("Some existing folders look like this student's name. Pick the right one.")
    choice = st.radio(f"Save into {sharepoint.folder} / {intake} /", options, key=f"{key}-folder",
                      index=0 if exact and not alike else None)
    if choice is None:
        st.caption("Choose a folder to enable saving.")
        return
    folder = choice.removeprefix("New folder: ")
    saved = st.session_state.setdefault("sp_saved", {})
    if st.button(f"☁️ Save {filename} to SharePoint", type="primary", disabled=not allowed, key=f"{key}-save"):
        with st.spinner("Saving to SharePoint..."):
            try:
                link = sharepoint.upload(data, safe_name(filename), sharepoint.folder, intake, folder)
            except SharePointError as e:
                st.error(str(e))
                return
        saved[key] = (link, folder, intake)
        cache.pop(intake, None)
        st.session_state.setdefault("made_cvs", {})[key] = {"text": body, "name": student}
    if key in saved:
        link, folder, intake = saved[key]
        st.success(f"Saved to {sharepoint.folder} / {intake} / {folder}. "
                   f"If a CV was already there, SharePoint kept it as an earlier version.")
        st.link_button("Open in SharePoint", link)
