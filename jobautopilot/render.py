"""Render a tailored resume to a one-page-ish ATS-friendly PDF (plain text layer, no tables)."""
import re
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer

BASE = ParagraphStyle("b", fontName="Helvetica", fontSize=9.5, leading=12.5, alignment=TA_LEFT)
H1 = ParagraphStyle("h1", parent=BASE, fontName="Helvetica-Bold", fontSize=18, leading=22)
H2 = ParagraphStyle("h2", parent=BASE, fontName="Helvetica-Bold", fontSize=10.5, spaceBefore=7, spaceAfter=1)
ROLE = ParagraphStyle("r", parent=BASE, fontName="Helvetica-Bold")
BUL = ParagraphStyle("bu", parent=BASE, leftIndent=11, bulletIndent=1, spaceBefore=1)


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:60]


def build_pdf(resume: dict, tailored: dict, path: Path) -> Path:
    e = escape
    b = resume["basics"]
    bullets = {(r["id"], x["id"]): x["text"] for r in resume["experience"] for x in r["bullets"]}
    roles = {r["id"]: r for r in resume["experience"]}
    story = [Paragraph(e(b["name"]), H1)]
    contact = [b.get("location"), b.get("email"), b.get("phone")]
    contact += [f'<link href="{e(u)}">{e(k)}</link>' for k, u in (b.get("links") or {}).items()]
    story.append(Paragraph(" · ".join(c if c and c.startswith("<link") else e(c) for c in contact if c), BASE))
    story.append(HRFlowable(width="100%", thickness=0.6, spaceBefore=4, spaceAfter=2))

    story += [Paragraph("SUMMARY", H2), Paragraph(e(tailored["summary"]), BASE)]

    groups = {}
    order = {s: i for i, s in enumerate(tailored["skills_order"])}
    for g, items in resume["skills"].items():
        groups[g] = sorted(items, key=lambda s: order.get(s, 999))
    story.append(Paragraph("SKILLS", H2))
    for g in sorted(groups, key=lambda g: min(order.get(s, 999) for s in groups[g])):
        story.append(Paragraph(f"<b>{e(g)}:</b> {e(', '.join(groups[g]))}", BASE))

    story.append(Paragraph("EXPERIENCE", H2))
    for item in tailored["experience"]:
        r = roles[item["id"]]
        story.append(Paragraph(f'{e(r["title"])}, {e(r["org"])} <font name="Helvetica" size="9">— {e(r["dates"])}</font>', ROLE))
        for bid in item["bullet_ids"]:
            story.append(Paragraph(e(bullets[(r["id"], bid)]), BUL, bulletText="•"))

    if resume.get("projects"):
        story.append(Paragraph("PROJECTS", H2))
        for p in resume["projects"]:
            story.append(Paragraph(f'<b>{e(p["name"])}</b>: {e(p["text"])}', BASE))

    story.append(Paragraph("EDUCATION", H2))
    for ed in resume["education"]:
        story.append(Paragraph(f'{e(ed["degree"])}, {e(ed["school"])} ({e(ed["years"])})', BASE))
    if resume.get("certifications"):
        story.append(Paragraph("CERTIFICATIONS", H2))
        story.append(Paragraph(e("; ".join(resume["certifications"])), BASE))
    if resume.get("extras"):
        story.append(Paragraph("LEADERSHIP", H2))
        for x in resume["extras"]:
            story.append(Paragraph(e(x), BUL, bulletText="•"))

    path.parent.mkdir(parents=True, exist_ok=True)
    SimpleDocTemplate(str(path), pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm,
                      topMargin=13 * mm, bottomMargin=12 * mm, title=f'{b["name"]} — Resume',
                      author=b["name"]).build(story)
    return path
