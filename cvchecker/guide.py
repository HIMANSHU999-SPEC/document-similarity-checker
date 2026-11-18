import fcntl
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st

GUIDE = """
**What this app does:** finds wording copied between CVs and tells you what each student needs to change.

#### Checking CVs
1. **Add the CVs** in the sidebar: PDF or Word, up to 600 at once. Add a whole intake together, because CVs
   are only compared with the others in the same check.
2. Press **Check CVs**. Claude then explains each problem by itself (big batches take a minute or two).
3. **Read the table:** 🔴 **Rewrite needed**: send the student their feedback · 🟠 **Small fixes**: a short part
   to reword · ✅ **OK**: nothing to do.
4. **Click a row** to see the copied text, edit Claude's feedback and download that student's feedback (Word),
   or download feedback for every student at once (ZIP).

#### Good to know
- The same CV uploaded twice (for example a PDF and a Word copy) is checked once.
- Contact details, headings, dates, common CV phrases and the CV template are ignored, so only real copying counts.
- Claude gives advice; the student rewrites their own CV. **Fix CVs with Claude** (sidebar, access code needed)
  rewrites only the copied wording for you.
- Results go when you close the tab, so download what you need.

#### Transcript to CV (top of the page)
Turn a student's part of a Teams interview into a CV, or update their existing CV, then download it or save it to
SharePoint.

#### Privacy
Downloads contain students' personal details: keep them within LAAT staff. Emails and phone numbers are never sent
to Claude.
"""


class SeenStore:
    """Who has dismissed the welcome guide, saved next to the learned phrases file (outside git)."""

    def __init__(self, folder: Path):
        self.path = Path(folder) / "guide_seen.json"

    def load(self) -> set[str]:
        try:
            return set(json.loads(self.path.read_text(encoding="utf-8")).get("seen", {}))
        except (OSError, ValueError, AttributeError):
            return set()

    def mark(self, email: str):
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with open(self.path.with_name(self.path.name + ".lock"), "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                data = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}
            except ValueError:
                data = {}
            seen = data.get("seen", {}) if isinstance(data.get("seen"), dict) else {}
            seen[email.lower()] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            fd, tmp = tempfile.mkstemp(dir=self.path.parent, suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({"version": 1, "seen": seen}, f, indent=2)
            os.chmod(tmp, 0o600)
            os.replace(tmp, self.path)


def should_show(email: str, seen: set[str], session) -> bool:
    return not session.get("guide_opened") and email.lower() not in seen


@st.dialog("Welcome to the CV Checker", width="large")
def show(email: str, store: SeenStore):
    st.markdown(GUIDE)
    a, b = st.columns(2)
    if a.button("Got it, don't show this again", type="primary", use_container_width=True):
        try:
            store.mark(email)
        except OSError:
            pass  # still closes; it will just show again next sign-in
        st.rerun()
    if b.button("Close", use_container_width=True):
        st.rerun()


def on_sign_in(email: str, store: SeenStore):
    """Open the guide once per session for anyone who hasn't dismissed it."""
    if should_show(email, store.load(), st.session_state):
        st.session_state.guide_opened = True
        show(email, store)


def help_button(email: str, store: SeenStore):
    if st.button("❓ How to use", use_container_width=True):
        st.session_state.guide_opened = True
        show(email, store)
