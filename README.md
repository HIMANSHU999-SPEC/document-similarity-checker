# Document Similarity Checker

A local tool for comparing a batch of documents against each other, scoring how similar each pair is, and showing the exact passages they share.

Built for a higher-education provider to check student submissions, CVs and personal statements for overlap. It runs entirely on the machine it's launched from — **no document is ever uploaded to a third-party service**, which is the whole point when the files are someone's coursework or job application.

Built by **Himanshu Chadha**.

## What it does

Upload two or more PDF or Word documents and the tool will:

- **Score every pair** — cosine similarity over TF-IDF vectors, so scoring is based on distinctive vocabulary rather than common words
- **Flag pairs above a threshold** you set (default 80%)
- **Show the exact matching text** — side by side, so you can see precisely which passages overlap rather than being handed a percentage and left to hunt
- **Identify hotspots** — a table of which documents get flagged most often, and against whom, which surfaces the one document that's been copied from repeatedly
- **Plot a similarity matrix** — a heatmap of every document against every other

## Why it works this way

**Two different algorithms, doing two different jobs.** TF-IDF with cosine similarity is good at *ranking* — it tells you which pairs are worth looking at, and it's robust to reordered sentences and swapped synonyms. But it can't tell you *what* matched. So once a pair is flagged, `difflib.SequenceMatcher` runs over the word sequences to extract the actual contiguous blocks. Scoring and evidence are separate problems and are solved separately.

**Minimum block size is configurable** (default 10 words). Set it too low and every shared phrase like "excellent communication skills" is a hit; too high and paraphrased passages slip through. Making it a control rather than a constant means the person reviewing can tune it to the document type in front of them.

**Nothing leaves the machine.** Every online plagiarism service requires uploading the documents. For student coursework and job applications that's a data protection question nobody wants to answer. Running locally removes the question entirely.

**Stop words, accents and case are all normalised** before vectorising, so formatting differences and accented characters don't mask a match.

## Stack

Python · Streamlit · scikit-learn (TF-IDF, cosine similarity) · PyMuPDF · python-docx · pandas · Plotly

## Running it

```bash
pip install -r requirements.txt
streamlit run app.py
```

Then open the address Streamlit prints (usually `http://localhost:8501`).

1. Upload two or more PDF or DOCX files in the sidebar
2. Set the similarity threshold and minimum matching block size
3. Click **Analyze Documents**

## Reading the output

**Reference key** — each document is given an ID (`Doc #1`, `Doc #2`) mapped to its filename, so pairs can be discussed without repeating long filenames.

**Metrics** — documents analysed, similar pairs found, total comparisons made.

**In-depth comparison** — pick any flagged pair to see the matching blocks side by side.

**Similarity hotspots** — documents ranked by how many times they were flagged. A document flagged against five others is a different problem from two documents flagged against each other.

**Similarity matrix** — heatmap of all pairwise scores.

## Notes

- Only PDF and DOCX are supported. Anything else is skipped with a warning rather than failing the run.
- Scanned PDFs with no text layer will extract nothing — the tool reads text, it does not OCR.
- Comparisons grow with the square of the document count, so very large batches take proportionally longer.

## Author

**Himanshu Chadha** — IT Manager, London Academy for Applied Technology
[linkedin.com/in/himanshuchadha-it](https://www.linkedin.com/in/himanshuchadha-it)

## License

Copyright © 2026 Himanshu Chadha. All rights reserved.
