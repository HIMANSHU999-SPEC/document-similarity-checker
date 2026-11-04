# Design: simple "what to change" results table and learned common phrases

Status: agreed with Himanshu Chadha on 4 November 2026. Not yet built.
Based on: `app.py` at commit `3a6f338` ("Add Transcript to CV page"), branch `claude/check-pdf-size-limit-LA5lQ`.
Scope: the **Check CVs** page only. The **Transcript to CV** page is unchanged except where noted in Part 2.

## Why

Staff found the results too hard to use. After a check they currently see five metric cards and five tabs
(Triage, Review a CV, Groups, All pairs, Downloads). The useful answer, what each student needs to change,
only appears after pressing a Claude button and then opening each CV one at a time in "Review a CV".

Staff want what their earlier software gave them: **one table, one row per CV, saying what to change.**
They also want the list of common CV phrases (wording that is not evidence of copying) to grow over
time with Claude's help, instead of being a fixed file in the code.

Who uses it: the 8 staff on the allow-list (`[access] allowed_emails`). Students never see the app. They
receive the Word feedback sheets.

Decisions made with Himanshu:

| Question | Decision |
|---|---|
| Results layout | One table: CV, Status, What to change. Everything else moves under "Details". |
| When Claude runs | Automatically on every **Analyze Documents**, for flagged CVs only. |
| How phrases are learned | Claude suggests them. Staff press **Add** or **Ignore**. Nothing is added without a click. |

---

## Part 1: the results table

### What it does for staff

After pressing **Analyze Documents**, staff get one table that says, for every CV, whether it needs work
and what to change, in plain words. They don't need to press any extra button or open any tab to get
the answer.

### Flow

1. **Analyze Documents** runs the matching exactly as now (`run_analysis`, unchanged).
2. Straight afterwards, if a Claude client is configured, every CV whose matching status is not
   Original (`RED` or `AMBER`) is sent to Claude with the existing `review_many(...)` (6 in parallel).
   Original (`GREEN`) CVs are never sent.
   - Show a progress bar: "Claude is reviewing 4 CVs…", then "Reviewed n of N".
   - Replace the current "Ask Claude which of the N flagged CVs need changing" button. Reviews are no
     longer optional.
   - Store results in `st.session_state.ai_reviews` as today. Pressing Analyze again starts a fresh check
     and fresh reviews (as today).
3. The table is shown.

### On screen

Keep the hero header and the "files need attention" expander as they are.

**Counts row:** keep it, but make it match the table: CVs checked · Rewrite needed · Small fixes · OK.
When Claude didn't run, use the matching counts as today (Needs review · Check · Original).

**The table** (an `st.dataframe` with single-row selection, `on_select="rerun"`, `selection_mode="single-row"`):

| CV | Status | What to change |
|---|---|---|
| Priya Nair | 🔴 Rewrite needed | Profile and Experience bullets are copied: rewrite them in your own words, using your council internship. |
| Aisha Rahman | 🔴 Rewrite needed | Profile and four job bullets match another CV: check which student wrote them. |
| Daniel Okafor | 🟠 Small fixes | Profile is copied: rewrite it in your own words. |
| Grace Mensah | ✅ OK | Nothing to change. |

- **CV** is the file name without its extension. Keep the Doc ID in a narrow first column (`Doc #3`),
  because the feedback sheets and the staff-meeting summary refer to Doc IDs.
- **Status** comes from Claude's `overall`:
  - `rewrite_needed`: 🔴 Rewrite needed
  - `small_fixes`: 🟠 Small fixes
  - `no_action`: ✅ OK
  - A CV Claude wasn't asked about (matching status Original): ✅ OK
  - Claude's verdict wins over the matching status. A CV the matcher flagged whose passages Claude judged
    all template or coincidence shows ✅ OK. The detail panel still shows the matching status, so staff
    can see it was flagged.
- **What to change** is Claude's new `one_line` field (see "Changes to the Claude review" below). For ✅ rows,
  it says "Nothing to change."
- **Sort order:** Rewrite needed, then Small fixes, then OK. Within each, lowest original share first. The
  existing `review_rank` already does nearly this; adapt it.
- **Fallback when Claude is missing or failed for a row:** Status uses the matching status (🔴 Needs review,
  🟠 Check, 🟢 Original). What to change is built from the matches without Claude, e.g.
  "Profile and Experience match another CV: rewrite these sections in your own words." (use
  `sections_text(s.sections)`). Show one `st.warning` naming the Doc IDs Claude couldn't review and the
  reason, grouped by message as the current code does.

**Below the table:**

- Two buttons side by side: **Download table (Excel)**, which is just these three or four columns, one
  sheet, and **Download all feedback sheets (ZIP)** (existing `feedback_zip(names, summaries, reviews)`).
- A caption with the Claude cost for this check, e.g. "Claude: about $0.06 for 4 CVs". The app already
  tracks `Usage` in US dollars. Keep dollars unless asked otherwise.
- The **Suggested common phrases** box (Part 2).

**Row detail panel:** when a row is selected, show underneath the table what "Review a CV" shows today for
that CV:

- name, matching status pill, original-share pill, Claude overall pill
- Claude's `staff_note`
- the per-section **What's wrong / What to change / Questions** text areas. Keep them editable, because
  the feedback sheet uses the edited text.
- **Feedback sheet (Word)** download for this CV
- "Matching passages" with quotes and Claude's verdict per passage, collapsed by default once Claude
  has reviewed the CV

If no row is selected, show a caption: "Select a row to see the copied text and the full feedback."
Keep a "🤖 Ask Claude again" button in the panel for rows where Claude failed (the existing `review_cv` call).

**Details:** one collapsed `st.expander("Details")` at the bottom holds what is left of today's tabs:

- Copying groups (today's Groups tab)
- All flagged pairs table and the similarity matrix (today's All pairs tab)
- The full Excel workbook and the PDF summary (today's Downloads tab, minus the ZIP, which moved up)
- "Summarise this check for a staff meeting" (today's button and result)

Remove `st.tabs(...)` and the "Review a CV" selectbox. The empty-state `steps([...])` text changes step 3
to "Read the table and download feedback sheets".

### Changes to the Claude review (`cvchecker/ai.py`)

Add to `REVIEW_SCHEMA` (top level, both required):

- `one_line` (string): one or two short sentences for the table, at most 25 words. Names the affected
  sections and the action. Like the other fields: no replacement wording, no mention of the other
  applicant, UK English. For `no_action` it is "Nothing to change."
- `common_phrases` (array of strings): see Part 2. Empty when there is nothing generic.

Add matching instructions to `REVIEW_SYSTEM`. Add `one_line` and `common_phrases` to the `Review`
dataclass. `feedback_docx` doesn't need `one_line`.

---

## Part 2: learning common phrases

### What it does for staff

Today the stock-phrase list is `cvchecker/common_phrases.txt` (about 40 phrases, changeable only in code),
plus a per-check "Extra phrases to ignore" box that is forgotten after the check. Under this part, phrases
Claude recognises as generic CV wording are offered to staff once. Staff approve with one click, and from
then on every check ignores them.

### Where suggestions come from

In each review, Claude also returns `common_phrases`: short generic phrases (3–15 words) taken **only**
from passages it judged `template_or_stock`. Examples: "level 3 extended diploma in information
technology", "references available on request". The prompt must say: never include a person's name, an
employer or school name, numbers, or anything about the student's own experience.

The app checks every suggestion before showing it. Reject the suggestion if any of these fail:

1. After normalising (`prepare.TOKEN` + `prepare.normalize`), it is 3–15 words.
2. It appears as a contiguous run of words in that CV's tokens, **inside a passage Claude gave the verdict
   `template_or_stock`** (use `Review.items` and `Review.verdicts`).
3. It contains no digit and no `@`.
4. None of its words is one of the CV's top-of-page name words. Take the first 2–3 tokens of the
   extracted text, or use `names.name_parts` on the file name. Keep it simple and conservative.
5. It is not already in the built-in list, the learned list or the ignored list.
6. At most 5 suggestions are kept per CV.

Suggestions are merged across the check and counted by how many CVs contained them.

### On screen

**Suggested common phrases (n)**, shown under the table only when n > 0, as a bordered container. Each
line shows:

> "references available on request" · in 4 CVs   **[Add]** **[Ignore]**

- **Add** saves the phrase as learned (who, when) and shows the toast "Saved. Click Analyze Documents
  again to apply it to this check." Re-running is the staff's choice, because it also re-runs Claude
  and costs money.
- **Ignore** saves the phrase as ignored, so it is never suggested again.
- Both remove the line from the box straight away.

**Sidebar:** add a `st.expander("Common phrases")` under "Ignore common wording" on the Check CVs page.

- "Built-in (n)" shows `common_phrases.txt` as a read-only list.
- "Learned (n)" lists each learned phrase with who added it and when, and a **Remove** button. Removing
  deletes it from learned. It does not add it to ignored.
- Keep the existing "Extra phrases to ignore, one per line" text area. It stays per-check only.

### Applying learned phrases

`load_phrases(path, extra)` today reads the built-in file plus the extra text. Change `run_analysis` to
pass learned phrases too, either by a new `learned` argument to `load_phrases` or by appending them to
`extra`. The **Transcript to CV** originality check (`transcript_ui.py`, line 18:
`analyse([text] + others, min_words)`) currently passes no phrases at all. It should use the same
built-in + learned list, so the two pages agree.

### Data that must be saved

One JSON file, **outside the git checkout**, so `git pull` never touches it:

- Path: `[phrases] path` in `.streamlit/secrets.toml` if set, otherwise `~/cvapp/data/learned_phrases.json`.
  On the server that is `/home/ubuntu/cvapp/data/learned_phrases.json`. `cvapp.service` runs as `ubuntu`.
- Create the folder on first save with mode `0700`, and the file with mode `0600`.
- No student data: the file never stores CV file names, student names or CV text beyond the approved
  phrase itself. It records only the phrase, who acted and when.

Format (UTF-8, pretty-printed):

```json
{
  "version": 1,
  "learned": [
    {
      "phrase": "references available on request",
      "key": "references available on request",
      "added_by": "himanshu@laat.ac.uk",
      "added_at": "2026-11-04T15:40:12Z",
      "source": "claude"
    }
  ],
  "ignored": [
    {
      "phrase": "worked as part of a busy team",
      "key": "worked as part of a busy team",
      "ignored_by": "raghav.malhotra@laat.ac.uk",
      "ignored_at": "2026-11-04T15:41:03Z"
    }
  ]
}
```

- `phrase` is shown to staff exactly as Claude wrote it. `key` is the normalised words joined by single
  spaces, and is used for matching and de-duplication.
- `added_by` / `ignored_by` is the signed-in email (`require_login()` returns `(name, email)`).
- `source` is `"claude"` for now. It leaves room for staff-typed phrases later.

Saving rules, in a new module `cvchecker/phrases_store.py`:

- **Read-modify-write under a lock:** `fcntl.flock` on a sidecar `learned_phrases.json.lock`. Re-read the
  file inside the lock, apply the change, write to a temp file in the same folder, `fsync`, then
  `os.replace`. Two staff clicking at the same moment must not lose either change.
- **Missing file:** empty lists, no error.
- **Unreadable or invalid JSON:** rename it to `learned_phrases.json.corrupt-<UTC timestamp>`, carry on with
  built-in phrases only, and show `st.warning` once: "The learned phrases file couldn't be read. It was
  kept as … and the app is using the built-in phrases." Never overwrite a bad file in place.
- **Write failure** (permissions, disk full): show `st.error` and leave the current results on screen.
  The click is not recorded.

Backups: the file is tiny. Mention in the README that it should be copied along with `secrets.toml` when
the server is backed up.

---

## Part 3: build, errors, testing and deployment

### Code layout

| File | Change |
|---|---|
| `cvchecker/ai.py` | `one_line` and `common_phrases` in the schema, the prompt and `Review` |
| `cvchecker/phrases_store.py` (new) | load / add / ignore / remove, locking, corrupt-file handling, `validate_suggestions(review, analysis, index, known)` |
| `cvchecker/fix_table.py` (new) | `fix_rows(names, ids, summaries, reviews)` returns the table rows (status label, icon, what to change, sort key), including the no-Claude fallback text |
| `cvchecker/prepare.py` | `load_phrases` accepts learned phrases |
| `cvchecker/report.py` | `fix_table_excel(rows)` for the small Excel download, or reuse `to_excel` with a new sheet |
| `app.py` | auto-review after Analyze, the table with row selection, the detail panel, Details expander, suggestions box, sidebar phrase manager. Remove the tabs. |
| `cvchecker/transcript_ui.py` | pass built-in + learned phrases to `analyse` |
| `README.md` | the phrases file, its location, and that it needs backing up |

`requirements.txt` needs no new packages (`fcntl`, `json` and `tempfile` are standard library).
**Do not change the `Authlib==1.6.5` pin.** See the commit "Pin Authlib 1.6.5 so Microsoft sign-in works
with Streamlit 1.48".

### Error handling summary

| Situation | What staff see |
|---|---|
| No Claude key configured | The table appears with fallback rows, and a caption says how to turn Claude on. No suggestions box. |
| Claude fails for some CVs | Those rows use fallback text, plus one warning naming them. The others are normal. |
| Claude fails for all | As above for every flagged row. |
| Phrases file missing | Nothing, just an empty learned list. |
| Phrases file corrupt | One warning. The file is kept as `.corrupt-…`, and built-in phrases are used. |
| Saving a phrase fails | `st.error`, and the results stay. |

### Cost and privacy

What goes to Claude is unchanged from today's review: matched passages with up to 25 words of
context, from flagged CVs only. The only difference is that it now happens automatically. With up to 100
files per check (`MAX_FILES`), the worst case is about $1.50 per check at today's estimate of about $0.015
per CV. Show the actual cost per check, as above.

### Tests to write (pytest, no real API calls; use `FakeClient` from `tests/test_ai.py`)

`phrases_store`:
- A missing file loads as empty, and the first `add` creates folder `0700` and file `0600`.
- `add`, then `load`, round-trips. Adding the same phrase twice (different case or punctuation) keeps one.
- `ignore` stops a phrase being suggested. `remove` deletes a learned phrase and does not ignore it.
- Two processes adding different phrases at the same time both survive (use `multiprocessing`, or two
  threads each opening the store).
- Invalid JSON is renamed to `.corrupt-…`, load returns empty, and a warning flag is set. The bad file
  still exists.
- A write failure (read-only folder) raises a clear error, and the original file is unchanged.

Suggestion validation:
- Accepts a 3–15 word phrase found inside a `template_or_stock` passage.
- Rejects: fewer than 3 or more than 15 words, not in the CV, inside a `copied` passage, containing a digit or `@`,
  containing the CV's name words, already built-in, learned or ignored, and more than 5 per CV.

`fix_table`:
- Each Claude `overall` maps to the right status and icon, and `no_action` beats the matching status RED.
- Sort order: Rewrite needed, then Small fixes, then OK, then by original share.
- Fallback text when the review is missing or an `AIError`, naming the affected sections.

`ai`:
- `review_cv` returns `one_line` and `common_phrases` from a `FakeClient` answer.
- The request schema includes both new fields as required.

`prepare` and `similarity`:
- A learned phrase passed to `load_phrases` removes that wording from matching (two CVs that only share
  that phrase come out Original).

App (Streamlit `AppTest`, with a fake client injected):
- After Analyze with 2+ files, the page shows one dataframe and no `st.tabs`. Flagged CVs were sent to
  the fake client and Original ones weren't.
- With no client, the table still renders with fallback text.
- Pressing Add in the suggestions box writes to a temp phrases file (point `[phrases] path` at
  `tmp_path`).

Manual check before deploying, with the demo CVs (5 files: Aisha Rahman, Daniel Okafor, Priya Nair,
Tomasz Kowalski, Grace Mensah). Matching results today, default settings:

- Priya and Aisha are red, with 67% / 58% copied from each other.
- Daniel and Tomasz are red, sharing only the profile paragraph (35% / 34%).
- Grace is Original. Her generic phrases are already ignored by the built-in list.

Expected with this design: Priya and Aisha "Rewrite needed". Daniel and Tomasz "Small fixes" or
"Rewrite needed", as Claude decides. Grace ✅ OK. Every row has a one-line "what to change".
Selecting a row shows quotes and editable feedback. Add a suggested phrase, re-run, and that wording no
longer matches. The file appears at `~/cvapp/data/learned_phrases.json` with mode 600.

### Deployment (same as previous releases)

On the server, in `/home/ubuntu/cvapp/CV-CHECKER-`:

1. Back up `.streamlit/config.toml`. The server keeps its own `[server]` and `[browser]` settings on top of
   the repo's version.
2. `git stash`, `git pull` on `claude/check-pdf-size-limit-LA5lQ`, `git stash pop`, keeping the server's
   settings if anything conflicts.
3. `venv/bin/pip install -r requirements.txt` only if `requirements.txt` changed.
4. `sudo systemctl restart cvapp`, then check: the health endpoint, the sign-in screen, and the allow-list
   (8 emails) still enforced.
5. Don't touch the Stock Check app (PM2 processes `stock-*`, nginx `stock.laat.ac.uk`).

`/home/ubuntu/cvapp/data/` is created by the app on the first **Add** or **Ignore**. No manual step is
needed.
