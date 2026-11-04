# Document Similarity Checker

A local tool for comparing a batch of documents against each other, scoring how similar each pair is, and showing the exact passages they share.

Built for a higher-education provider to check student submissions, CVs and personal statements for overlap. It runs entirely on the machine it's launched from — **no document is ever uploaded to a third-party service**, which is the whole point when the files are someone's coursework or job application.

Built by **Himanshu Chadha**.

## What it does

Upload two or more PDF or Word documents and the tool will:

- **Score every pair two ways.** *Similarity* is cosine similarity over TF-IDF vectors, so it reflects distinctive vocabulary. *Copied text* is the share of one document that appears word for word in the other, so "62% of Doc #4 is found in Doc #9" reads as exactly what it is.
- **Flag pairs** at or above either threshold you set (defaults: 80% similarity, 25% copied text)
- **Show every matching passage**, wherever it sits in each document, so a student who reorders sections is still caught
- **Ignore template text.** Wording shared by most of a batch, or found in an uploaded blank template, isn't counted as copying
- **Report problem files by name.** Scanned PDFs with no text, unreadable files and identical uploads each get a warning instead of silently dropping out
- **Identify hotspots**, which surfaces the one document copied from repeatedly
- **Plot a similarity matrix**, a heatmap of every document against every other
- **Export a report** as Excel (every pair, every passage) or a PDF summary

## Why it works this way

**Two different measures, doing two different jobs.** TF-IDF with cosine similarity is good at *ranking*: it's robust to reordered sentences and swapped synonyms. But two CVs can share half their text and still score under 80%, so a second measure counts the copied words directly, by matching every run of identical words ("shingles") between the two documents.

**Minimum passage length is configurable** (default 10 words). Set it too low and every shared phrase like "excellent communication skills" is a hit; too high and short copied sentences slip through.

**Templates are not evidence.** Students who start from the same LAAT template share its headings and boilerplate. Passages found in at least half of a batch (and at least 3 documents), or in an uploaded template, are left out of both scores.

**Nothing leaves the machine.** Every online plagiarism service requires uploading the documents. For student coursework and job applications that's a data protection question nobody wants to answer. Running locally removes the question entirely.

**Case, accents, ligatures and punctuation are normalised** before matching, so formatting differences don't mask a match.

**Files are recognised by their contents**, not by the file type the browser reports, and Word text inside tables, headers, footers and text boxes is read.

## Stack

Python 3.11 to 3.13 · Streamlit · scikit-learn · PyMuPDF · python-docx · pandas · Plotly · openpyxl

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
