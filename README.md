# Document Similarity Checker

A local tool for comparing a batch of documents against each other, scoring how similar each pair is, and showing the exact passages they share.

Built for a higher-education provider to check student submissions, CVs and personal statements for overlap. All matching runs on the machine it's launched from, and **no document is ever uploaded to a third-party service**, which matters when the files are someone's coursework or job application. The optional Claude review sends only short matched passages, with contact details removed, and only when staff ask for it.

Built by **Himanshu Chadha**.

## What it does

Upload two or more PDF or Word documents and the tool will:

- **Score every pair two ways.** *Similarity* is cosine similarity over TF-IDF vectors, so it reflects distinctive vocabulary. *Copied text* is the share of one document that appears word for word in the other, so "62% of Doc #4 is found in Doc #9" reads as exactly what it is.
- **Flag pairs** at or above either threshold you set (defaults: 80% similarity, 25% copied text)
- **Show every matching passage**, wherever it sits in each document, so a student who reorders sections is still caught
- **Ignore what isn't evidence.** Contact details (emails, phone numbers, web links, postcodes), dates, section headings, stock CV phrases (`cvchecker/common_phrases.txt`, plus extra phrases per check) and wording shared by most of a batch or found in an uploaded blank template are all left out
- **Triage the batch.** Every CV gets a status (🔴 Needs review, 🟠 Check, 🟢 Original), its share of original wording, its main match, and which CV sections are affected, worst first
- **Spot copying groups**, such as one personal statement shared by three or more applicants
- **Feedback sheets.** A Word document per flagged student listing, by section, the sentences to rewrite. It never names the other applicant
- **Report problem files by name.** Scanned PDFs with no text, unreadable files and identical uploads each get a warning instead of silently dropping out
- **Identify hotspots**, which surfaces the one document copied from repeatedly
- **Plot a similarity matrix**, a heatmap of every document against every other
- **Export a report** as Excel (every pair, every passage) or a PDF summary
- **Ask Claude what to change** (optional). For each flagged CV, Claude decides whether each match is copied, template or stock wording, or coincidence, then writes what's wrong, what to change and questions for the student, per CV section, without writing replacement text. Staff can edit it before it goes into the feedback sheet. One button reviews every flagged CV and re-orders the triage list into rewrite needed, small fixes and no action

## Why it works this way

**Two different measures, doing two different jobs.** TF-IDF with cosine similarity is good at *ranking*: it's robust to reordered sentences and swapped synonyms. But two CVs can share half their text and still score under 80%, so a second measure counts the copied words directly, by matching every run of identical words ("shingles") between the two documents.

**Minimum passage length is configurable** (default 10 words). Set it too low and every shared phrase like "excellent communication skills" is a hit; too high and short copied sentences slip through.

**Templates are not evidence.** Students who start from the same LAAT template share its headings and boilerplate. Passages found in at least half of a batch (and at least 3 documents), or in an uploaded template, are left out of both scores.

**Matching never leaves the server.** Extracting, matching, scoring and triage all run locally. The optional Claude review is the one exception, and only runs when staff click it: Claude (Sonnet 5.5, via the Anthropic API) receives the matched passages of one CV with about 25 words either side. Emails, phone numbers, web links, postcodes and dates are removed first, and no file names or applicant names are added. The batch summary sends only counts and statuses, no CV text.

**Case, accents, ligatures and punctuation are normalised** before matching, so formatting differences don't mask a match.

**Files are recognised by their contents**, not by the file type the browser reports, and Word text inside tables, headers, footers and text boxes is read.

## Stack

Python 3.10 to 3.13 · Streamlit · scikit-learn · PyMuPDF · python-docx · pandas · Plotly · openpyxl

## Running it

```bash
pip install -r requirements.txt
streamlit run app.py
```

Then open the address Streamlit prints (usually `http://localhost:8501`).

1. Upload two or more PDF or DOCX files in the sidebar (up to 20 MB each, 100 files per check)
2. Optionally upload the blank CV template under **CV template**
3. Set the thresholds and minimum passage length
4. Click **Analyze Documents**

The 20 MB limit is set in `.streamlit/config.toml`. If the app sits behind nginx, nginx needs `client_max_body_size 20M;` too, or larger uploads are rejected before they reach the app.

## Microsoft sign-in

When `.streamlit/secrets.toml` has an `[auth]` section, only signed-in Microsoft users can use the app; without it the app runs open, for local use. Copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml` on the server, fill in the values from the Entra ID app registration, and run `chmod 600` on it. The real file is in `.gitignore`.

In Entra ID, the app needs a **Web** redirect URI of `https://<the app's address>/oauth2callback`, and turning on **Assignment required** (Enterprise applications > the app > Properties) limits sign-in to the users or group assigned to it.

## Claude review

Add the API key to `.streamlit/secrets.toml` under `[anthropic]` (see `secrets.toml.example`). Without it the Claude buttons are hidden and everything else works as normal. Each CV review costs about $0.01 to $0.02; set a monthly spending cap in the Anthropic Console.

## Running the tests

```bash
pip install -r requirements-dev.txt
pytest
```

## Reading the output

**Warnings**: files left out of the check, and why; identical files, which are checked once.

**Reference key**: each document is given an ID (`Doc #1`, `Doc #2`) mapped to its filename, so pairs can be discussed without repeating long filenames.

**Metrics**: documents analysed, flagged pairs, total comparisons, and how many template phrases were ignored.

**In-depth comparison**: pick any flagged pair to see both scores, how much of each document is found in the other, and every matching passage with its position in each.

**Similarity hotspots**: documents ranked by how many times they were flagged. A document flagged against five others is a different problem from two documents flagged against each other.

**Similarity matrix**: heatmap of all pairwise similarity scores.

## Notes

- Only PDF and DOCX are supported. Anything else is reported and skipped.
- Scanned PDFs with no text layer can't be read, since the tool reads text and does not OCR. They're named in a warning.
- Comparisons grow with the square of the document count, so very large batches take proportionally longer.

## Author

**Himanshu Chadha** — IT Manager, London Academy for Applied Technology
[linkedin.com/in/himanshuchadha-it](https://www.linkedin.com/in/himanshuchadha-it)

## License

Copyright © 2026 Himanshu Chadha. All rights reserved.
