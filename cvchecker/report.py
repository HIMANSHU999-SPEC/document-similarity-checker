import html
import io
from datetime import datetime

import fitz
import pandas as pd


def pairs_table(names, pairs, thresholds):
    rows = [{
        "Document A": names[p.a],
        "Document B": names[p.b],
        "Similarity": round(p.similarity, 4),
        "Copied (A in B)": round(p.copied_a_in_b, 4),
        "Copied (B in A)": round(p.copied_b_in_a, 4),
        "Matching passages": len(p.passages),
        "Flagged": p.flagged(thresholds),
    } for p in pairs]
    return pd.DataFrame(rows).sort_values(
        ["Flagged", "Similarity"], ascending=False, ignore_index=True
    ) if rows else pd.DataFrame(rows)


def to_excel(names, pairs, thresholds, problems, duplicates) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xl:
        pairs_table(names, pairs, thresholds).to_excel(xl, sheet_name="Pairs", index=False)
        passages = [{
            "Document A": names[p.a], "Document B": names[p.b], "Words": s.length, "Passage": s.text,
        } for p in pairs if p.flagged(thresholds) for s in p.passages]
        pd.DataFrame(passages or [{"Passage": "None"}]).to_excel(xl, sheet_name="Passages", index=False)
        issues = [{"File": n, "Issue": msg} for n, msg in problems] + [
            {"File": " = ".join(group), "Issue": "Identical files"} for group in duplicates
        ]
        pd.DataFrame(issues or [{"Issue": "None"}]).to_excel(xl, sheet_name="Issues", index=False)
    return buf.getvalue()


def to_pdf(names, pairs, thresholds, problems, duplicates, run_by=None) -> bytes:
    flagged = sorted((p for p in pairs if p.flagged(thresholds)), key=lambda p: -p.score)
    e = html.escape
    rows = "".join(
        f"<tr><td>{e(names[p.a])}</td><td>{e(names[p.b])}</td>"
        f"<td>{p.similarity:.0%}</td><td>{p.copied:.0%}</td><td>{len(p.passages)}</td></tr>"
        for p in flagged
    )
    issues = "".join(f"<li>{e(n)}: {e(m)}</li>" for n, m in problems)
    issues += "".join(f"<li>Identical files: {e(' = '.join(g))}</li>" for g in duplicates)
    body = (
        "<h1>CV similarity report</h1>"
        f"<p>{datetime.now():%d %B %Y %H:%M}{' · run by ' + e(run_by) if run_by else ''}<br/>"
        f"{len(names)} documents · {len(pairs)} comparisons · {len(flagged)} flagged "
        f"(similarity at least {thresholds[0]:.0%} or copied text at least {thresholds[1]:.0%})</p>"
        "<h2>Flagged pairs</h2>"
        + (f"<table><tr><th>Document A</th><th>Document B</th><th>Similarity</th><th>Copied</th>"
           f"<th>Passages</th></tr>{rows}</table>" if flagged else "<p>None.</p>")
        + (f"<h2>Issues</h2><ul>{issues}</ul>" if issues else "")
    )
    css = "body{font-family:sans-serif;font-size:10pt} table{border-collapse:collapse} td,th{border:1px solid #999;padding:3px}"
    story = fitz.Story(html=body, user_css=css)
    buf = io.BytesIO()
    writer = fitz.DocumentWriter(buf)
    rect = fitz.paper_rect("a4")
    more = True
    while more:
        device = writer.begin_page(rect)
        more, _ = story.place(rect + (40, 40, -40, -40))
        story.draw(device)
        writer.end_page()
    writer.close()
    return buf.getvalue()
