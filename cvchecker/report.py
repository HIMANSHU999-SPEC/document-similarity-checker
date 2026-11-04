import html
import io
from datetime import datetime

import fitz
import pandas as pd


def sections_text(counter) -> str:
    return ", ".join(f"{name} ({words} words)" for name, words in counter.most_common())


def triage_table(names, ids, summaries):
    return pd.DataFrame([{
        "Status": s.status,
        "Doc ID": ids[s.index],
        "File": names[s.index],
        "Original": round(s.original, 4),
        "Main match": f"{ids[s.main_source]} ({s.main_source_share:.0%} of this CV)" if s.main_source_share else "",
        "Sections affected": sections_text(s.sections),
    } for s in summaries])


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


def to_excel(names, ids, analysis, summaries, thresholds, problems, duplicates) -> bytes:
    pairs = analysis.pairs
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xl:
        triage_table(names, ids, summaries).to_excel(xl, sheet_name="Triage", index=False)
        pairs_table(names, pairs, thresholds).to_excel(xl, sheet_name="Pairs", index=False)
        passages = [{
            "Document A": names[p.a], "Section in A": s.section_a,
            "Document B": names[p.b], "Section in B": s.section_b,
            "Words": s.length, "Passage": s.text_a,
        } for p in pairs if p.flagged(thresholds) for s in p.passages]
        pd.DataFrame(passages or [{"Passage": "None"}]).to_excel(xl, sheet_name="Passages", index=False)
        issues = [{"File": n, "Issue": msg} for n, msg in problems] + [
            {"File": " = ".join(group), "Issue": "Identical files"} for group in duplicates
        ]
        pd.DataFrame(issues or [{"Issue": "None"}]).to_excel(xl, sheet_name="Issues", index=False)
    return buf.getvalue()


def to_pdf(names, ids, analysis, summaries, thresholds, problems, duplicates, groups=(), run_by=None) -> bytes:
    e = html.escape
    review = [s for s in summaries if s.status != "Original"]
    rows = "".join(
        f"<tr><td>{e(s.status)}</td><td>{e(ids[s.index])}</td><td>{e(names[s.index])}</td>"
        f"<td>{s.original:.0%}</td>"
        f"<td>{e(ids[s.main_source]) if s.main_source_share else ''}</td>"
        f"<td>{e(sections_text(s.sections))}</td></tr>"
        for s in review
    )
    group_items = "".join(
        f"<li>{e(g.section)}: " + e(", ".join(f"{ids[i]} ({names[i]})" for i in g.docs))
        + f"<br/><i>{e(g.text)}</i></li>" for g in groups
    )
    issues = "".join(f"<li>{e(n)}: {e(m)}</li>" for n, m in problems)
    issues += "".join(f"<li>Identical files: {e(' = '.join(g))}</li>" for g in duplicates)
    flagged = sum(1 for p in analysis.pairs if p.flagged(thresholds))
    body = (
        "<h1>CV similarity report</h1>"
        f"<p>{datetime.now():%d %B %Y %H:%M}{' · run by ' + e(run_by) if run_by else ''}<br/>"
        f"{len(names)} CVs · {len(analysis.pairs)} comparisons · {flagged} flagged pairs "
        f"(similarity at least {thresholds[0]:.0%} or copied text at least {thresholds[1]:.0%})</p>"
        "<h2>CVs to review</h2>"
        + (f"<table><tr><th>Status</th><th>ID</th><th>File</th><th>Original</th><th>Main match</th>"
           f"<th>Sections affected</th></tr>{rows}</table>" if review else "<p>None.</p>")
        + (f"<h2>Copying groups</h2><ul>{group_items}</ul>" if group_items else "")
        + (f"<h2>Issues</h2><ul>{issues}</ul>" if issues else "")
    )
    css = ("body{font-family:sans-serif;font-size:9pt} table{border-collapse:collapse} "
           "td,th{border:1px solid #999;padding:3px;vertical-align:top}")
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
