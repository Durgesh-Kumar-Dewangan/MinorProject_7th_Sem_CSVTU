"""
Rebuild the internship report's front matter and splice it onto the
existing body.

What this does, and why:

  * Personal identifiers (student name, roll number, enrolment number)
    are replaced with the placeholders the official template uses
    ("Name of Student", "Roll No. XXXXXXXXX", "Enrollment No. XXXXX").
    They occur only on pages 1-5 of the source, all of which are rebuilt
    here, so nothing is left behind in the body.
  * Declaration, both certificates, the internship-completion
    certificate, Acknowledgement and Abstract become title-only pages,
    each with a bracketed placeholder for the text to be written later.
  * The Table of Contents keeps every chapter and section title but no
    page numbers, since the content is still to be added.
  * Lists of Figures / Tables / Abbreviations keep their real content:
    they contain no personal data and point at body pages that are not
    being changed.
  * Body pages (source page 13 onward) are copied through untouched, so
    every figure, table and screenshot survives exactly as it was.

Layout follows InternShipReportFormat.pdf and its GENERAL GUIDELINES:
Times New Roman throughout, chapter/section headings bold at 18-20,
content headings 14 bold, body 12.

Run:  python build_report_frontmatter.py
"""
import os
import sys

from pypdf import PdfReader, PdfWriter
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate, Frame, NextPageTemplate, PageBreak, PageTemplate,
    Paragraph, Spacer, Table, TableStyle,
)

DOWNLOADS = os.path.join(os.path.expanduser("~"), "Downloads")
SOURCE = os.path.join(DOWNLOADS, "organized (==best).pdf")
OUTPUT = os.path.join(DOWNLOADS, "Internship_Report_formatted.pdf")
FRONT_TMP = os.path.join(os.environ.get("TEMP", "."), "_frontmatter.pdf")

BODY_STARTS_AT = 13          # 1-based source page where CHAPTER I begins

# ---------------------------------------------------------------- fonts ----
# The guidelines require Times New Roman. Use the real Windows font when it
# is present so the rebuilt pages match the body exactly; fall back to
# ReportLab's built-in Times, which is metrically equivalent.
FONT, FONT_B, FONT_I = "Times-Roman", "Times-Bold", "Times-Italic"
_win_fonts = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
try:
    pdfmetrics.registerFont(TTFont("TNR", os.path.join(_win_fonts, "times.ttf")))
    pdfmetrics.registerFont(TTFont("TNR-Bold", os.path.join(_win_fonts, "timesbd.ttf")))
    pdfmetrics.registerFont(TTFont("TNR-Italic", os.path.join(_win_fonts, "timesi.ttf")))
    pdfmetrics.registerFontFamily("TNR", normal="TNR", bold="TNR-Bold", italic="TNR-Italic")
    FONT, FONT_B, FONT_I = "TNR", "TNR-Bold", "TNR-Italic"
except Exception as exc:                                  # pragma: no cover
    print(f"  (Times New Roman not found, using built-in Times: {exc})")

# --------------------------------------------------------------- styles ----
def _style(name, size, font=None, leading=None, align=TA_CENTER, space=0):
    return ParagraphStyle(
        name, fontName=font or FONT, fontSize=size,
        leading=leading or size * 1.35, alignment=align, spaceAfter=space,
    )

S_TITLE      = _style("title", 16, FONT_B, space=4)
S_CENTER     = _style("center", 12)
S_CENTER_B   = _style("centerB", 12, FONT_B)
S_CENTER_14B = _style("center14B", 14, FONT_B)
S_HEAD       = _style("head", 18, FONT_B, space=18)        # chapter/section heading
S_FOOT       = _style("foot", 11, FONT_B, leading=14)
S_BODY       = _style("body", 12, align=TA_JUSTIFY, leading=18)
S_PLACE      = _style("place", 12, FONT_I, align=TA_CENTER, leading=18)
S_CELL       = _style("cell", 11, align=0, leading=14)     # TA_LEFT
S_CELL_B     = _style("cellB", 11, FONT_B, align=0, leading=14)

DEPT_FOOTER = [
    "DEPARTMENT OF COMPUTER SCIENCE &amp; ENGINEERING",
    "UNIVERSITY TEACHING DEPARTMENT",
    "CHHATTISGARH SWAMI VIVEKANAND TECHNICAL UNIVERSITY, BHILAI",
]

# Pages (1-based, within the front matter) that carry the department block
# at the foot, matching the original and the template.
FOOTER_PAGES = {2, 3, 4, 6}
UNNUMBERED_PAGES = {1}

ROMAN = ["", "i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x",
         "xi", "xii", "xiii", "xiv", "xv", "xvi"]


def _decorate(canvas, doc):
    """Roman page number, and the department block where the template has it."""
    page = doc.page
    canvas.saveState()
    if page in FOOTER_PAGES:
        canvas.setFont(FONT_B, 11)
        y = 0.72 * inch
        for line in reversed([l.replace("&amp;", "&") for l in DEPT_FOOTER]):
            canvas.drawCentredString(letter[0] / 2.0, y, line)
            y += 14
    if page not in UNNUMBERED_PAGES:
        canvas.setFont(FONT, 11)
        canvas.drawCentredString(letter[0] / 2.0, 0.5 * inch, ROMAN[page - 1])
    canvas.restoreState()


def placeholder(text="Content to be added"):
    return Paragraph(f"[ {text} ]", S_PLACE)


def title_only_page(heading, note="Content to be added"):
    """A front-matter page that keeps its title and leaves the text for later."""
    return [
        Spacer(1, 0.35 * inch),
        Paragraph(heading, S_HEAD),
        Spacer(1, 0.45 * inch),
        placeholder(note),
    ]


# ------------------------------------------------------------ title page ----
def title_page():
    out = [Spacer(1, 0.15 * inch)]
    out += [
        Paragraph("&ldquo;An Explainable &amp; Responsible AI Framework", S_TITLE),
        Paragraph("for Trustworthy LLM Systems&rdquo;", S_TITLE),
        Spacer(1, 0.18 * inch),
        Paragraph("Internship Based Project Report Submitted", S_CENTER),
        Paragraph("To", S_CENTER),
        Paragraph("Chhattisgarh Swami Vivekanand Technical University, Bhilai", S_CENTER_B),
        Spacer(1, 0.14 * inch),
        Paragraph("for", S_CENTER),
        Paragraph("Completion of 6th Semester Internship of the degree", S_CENTER),
        Paragraph("of", S_CENTER),
        Paragraph("BACHELOR OF TECHNOLOGY (HONORS)", S_CENTER_B),
        Paragraph("In", S_CENTER),
        Paragraph("ARTIFICIAL INTELLIGENCE", S_CENTER_B),
        Paragraph("(COMPUTER SCIENCE &amp; ENGINEERING)", S_CENTER_B),
        Spacer(1, 0.12 * inch),
        Paragraph("By", S_CENTER),
        # --- the three identifiers, now template placeholders -------------
        Paragraph("Name of Student", S_CENTER_14B),
        Paragraph("Roll No. XXXXXXXXX", S_CENTER),
        Paragraph("Enrollment No. XXXXX", S_CENTER),
        Paragraph("B.Tech.(Hon) 6th Semester", S_CENTER),
        Spacer(1, 0.16 * inch),
        Paragraph("Under the Guidance of", S_CENTER),
        Paragraph("Dr. J.P. Patra", S_CENTER_B),
        Paragraph("(Associate Professor &amp; HOD)", S_CENTER),
        Paragraph("Computer Science and Engineering", S_CENTER),
        Paragraph("UTD-CSVTU, Bhilai(CG)", S_CENTER),
        Spacer(1, 0.26 * inch),
    ]
    for line in DEPT_FOOTER:
        out.append(Paragraph(line, S_FOOT))
    out += [Spacer(1, 0.10 * inch), Paragraph("Session : 2025-2026", S_CENTER_B)]
    return out


# --------------------------------------------------------------- the TOC ----
# Chapter -> section titles, taken from the existing report so the contents
# still describe the body that follows. Page numbers are deliberately left
# blank: the front matter is being rewritten, so they get filled in last.
TOC = [
    ("I", "Introduction", [
        "1.1 Background Information",
        "1.2 Project Objectives",
        "1.3 Significance of the Project",
        "1.4 Scope and Limitations",
        "1.5 Overview of the Report Structure",
    ]),
    ("II", "Organization Overview", [
        "2.1 Company Profile \u2013 TestAIng Solutions Pvt. Ltd.",
        "2.2 Vision and Mission",
        "2.3 Organizational Structure",
        "2.4 Products and Services",
        "2.5 Awards and Recognition",
        "2.6 Global Presence and Customer Segments",
        "2.7 Summary",
    ]),
    ("III", "Internship Activities", [
        "3.1 Overview of Activities",
        "3.2 Skills Developed",
        "3.3 Challenges Faced",
        "3.4 Achievements and Contributions",
        "3.5 Learning Outcomes",
    ]),
    ("IV", "Methodology", [
        "4.1 Project Overview",
        "4.2 Methodology",
        "4.3 Ethical Considerations",
        "4.4 Limitations and Future Improvements",
    ]),
    ("V", "Implementation", [
        "5.1 Overview of Implementation",
        "5.2 Development Environment",
        "5.3 Project Execution Plan",
        "5.4 Timeline Overview",
        "5.5 Resource Allocation",
        "5.6 Challenges Faced",
        "5.7 Success Factors",
        "5.8 Lessons Learned",
        "5.9 Tools and Resources Summary",
    ]),
    ("VI", "Results and Discussion", [
        "6.1 Overview",
        "6.2 Presentation of Results",
        "6.3 Interpretation of Results",
        "6.4 Comparison with Objectives",
        "6.5 Discussion of Key Findings",
        "6.6 Limitations and Future Directions",
    ]),
    ("VII", "Conclusion and Future Scope", [
        "7.1 Summary of Findings",
        "7.2 Achievement of Objectives",
        "7.3 Implications",
        "7.4 Future Work",
        "7.5 Personal Reflections",
    ]),
    ("VIII", "Learning Outcomes", [
        "8.1 Overview",
        "8.2 Skills Developed",
        "8.3 Knowledge Gained",
        "8.4 Professional Development",
        "8.5 Personal Growth",
        "8.6 Future Application",
    ]),
    ("IX", "References", []),
    ("X", "Annexure 1: Internship Completion Certificate", []),
]

FIGURES = [
    ("Fig 4.2.1(iii)", "Showing retrieved image output of vision based retrieval using BLIP", "19"),
    ("Fig 4.2.1(iv)", "Showing retrieved output of multimodal RAG", "20"),
    ("Fig 4.2.2(i) (a)", "Showing sentiment analysis of SHAP values", "23"),
    ("Fig 4.2.2(i) (b)", "Showing SHAP values in waterfall graph", "23"),
    ("Fig 4.2.2(ii)", "Showing comparison of ROUGE scores in In-context learning", "24"),
    ("Fig 4.2.2(iii)", "Showing influence score on chunks in counterfactual explanation", "26"),
    ("Fig 4.2.2(iv) (a)", "Predicting probabilities of LIME Explainer", "27"),
    ("Fig 4.2.2(iv) (b)", "Word influence of LIME Explainer", "27"),
    ("Fig 4.2.2(v)", "Showing score of labels, sentiment prediction and word importance", "28"),
    ("Fig 4.2.2(vi)", "Showing sentiment distribution in probing based explainer", "29"),
    ("Fig 4.2.3", "Showing output of hallucination and groundedness score", "31"),
    ("Fig 5.3", "Project Execution Plan Flowchart", "36"),
]

TABLES = [
    ("Table 4.2.2(i)", "Showing different SHAP explainers", "22"),
    ("Table 4.4", "Limitations and Future Improvements", "32"),
    ("Table 5.2.1", "Tech stacks and purpose", "33"),
    ("Table 5.4", "Timeline Overview", "36"),
    ("Table 5.9", "Showing the summary of used tools", "43"),
    ("Table 6.4", "Project Objective and Outcome Comparison", "47"),
]

ABBREVIATIONS = [
    ("rAI", "Responsible Artificial Intelligence"),
    ("xAI", "Explainable Artificial Intelligence"),
    ("LLM", "Large Language Model"),
    ("RAG", "Retrieval-Augmented Generation"),
    ("Multi-RAG", "Multiple Retrieval-Augmented Generation"),
    ("SHAP", "SHapley Additive exPlanations"),
    ("LIME", "Local Interpretable Model-Agnostic Explanations"),
    ("FAISS", "Facebook AI Similarity Search"),
    ("BM25", "Best Matching 25"),
    ("NLP", "Natural Language Processing"),
    ("OCR", "Optical Character Recognition"),
    ("API", "Application Programming Interface"),
    ("SaaS", "Software as a Service"),
    ("PDF", "Portable Document Format"),
    ("GPT", "Generative Pre-trained Transformer"),
    ("BLIP", "Bootstrapping Language-Image Pre-training"),
    ("VQA", "Visual Question Answering"),
    ("BLEU", "Bilingual Evaluation Understudy"),
    ("ROUGE", "Recall-Oriented Understudy for Gisting Evaluation"),
]

GRID = TableStyle([
    ("GRID", (0, 0), (-1, -1), 0.6, (0, 0, 0)),
    ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ("LEFTPADDING", (0, 0), (-1, -1), 6),
    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ("TOPPADDING", (0, 0), (-1, -1), 4),
    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
])


def toc_flowables():
    rows = [[Paragraph("Chapter", S_CELL_B),
             Paragraph("Title", S_CELL_B),
             Paragraph("Page No.", S_CELL_B)]]
    for num, title, sections in TOC:
        body = [Paragraph(f"<b>{title}</b>", S_CELL)]
        body += [Paragraph(s, S_CELL) for s in sections]
        rows.append([Paragraph(f"<b>{num}</b>", S_CELL), body, Paragraph("", S_CELL)])
    table = Table(rows, colWidths=[0.85 * inch, 4.45 * inch, 0.95 * inch], repeatRows=1)
    table.setStyle(GRID)
    return [Paragraph("Table of Contents", S_HEAD), Spacer(1, 0.12 * inch), table]


def list_flowables(heading, col_head, rows):
    data = [[Paragraph(col_head[0], S_CELL_B),
             Paragraph(col_head[1], S_CELL_B),
             Paragraph(col_head[2], S_CELL_B)]]
    for a, b, c in rows:
        data.append([Paragraph(a, S_CELL), Paragraph(b, S_CELL), Paragraph(c, S_CELL)])
    table = Table(data, colWidths=[1.45 * inch, 3.85 * inch, 0.95 * inch], repeatRows=1)
    table.setStyle(GRID)
    return [Paragraph(heading, S_HEAD), Spacer(1, 0.12 * inch), table]


def abbrev_flowables():
    data = [[Paragraph("S.No.", S_CELL_B),
             Paragraph("Abbreviation", S_CELL_B),
             Paragraph("Full Form", S_CELL_B)]]
    for i, (abbr, full) in enumerate(ABBREVIATIONS, start=1):
        data.append([Paragraph(str(i), S_CELL), Paragraph(abbr, S_CELL), Paragraph(full, S_CELL)])
    table = Table(data, colWidths=[0.75 * inch, 1.65 * inch, 3.85 * inch], repeatRows=1)
    table.setStyle(GRID)
    return [Paragraph("List of Abbreviations", S_HEAD), Spacer(1, 0.12 * inch), table]


def build_front_matter(path):
    doc = BaseDocTemplate(
        path, pagesize=letter,
        leftMargin=1.0 * inch, rightMargin=1.0 * inch,
        topMargin=0.9 * inch, bottomMargin=1.1 * inch,
        title="Internship Based Project Report",
        author="",            # no author metadata - it is an identifier too
        subject="6th Semester Internship Based Project Report",
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="main")
    doc.addPageTemplates([PageTemplate(id="all", frames=[frame], onPage=_decorate)])

    story = []
    story += title_page()                                           # page 1
    story.append(PageBreak())
    story += title_only_page("DECLARATION BY THE CANDIDATE")        # i
    story.append(PageBreak())
    story += title_only_page("CERTIFICATE BY THE SUPERVISOR")       # ii
    story.append(PageBreak())
    story += title_only_page("CERTIFICATE BY THE EXAMINER")         # iii
    story.append(PageBreak())
    story += title_only_page("CERTIFICATE OF INTERNSHIP COMPLETION",
                             "To be issued on the organisation's letterhead")  # iv
    story.append(PageBreak())
    story += title_only_page("ACKNOWLEDGEMENT")                     # v
    story.append(PageBreak())
    story += title_only_page("ABSTRACT", "Abstract to be written in 250-300 words")  # vi
    story.append(PageBreak())
    story += toc_flowables()                                        # vii ...
    story.append(PageBreak())
    story += list_flowables("List of Figures", ("Figure", "Title of Figure", "Page No."), FIGURES)
    story.append(PageBreak())
    story += list_flowables("List of Tables", ("Table", "Title of Table", "Page No."), TABLES)
    story.append(PageBreak())
    story += abbrev_flowables()

    doc.build(story)
    return PdfReader(path)


def main():
    if not os.path.exists(SOURCE):
        sys.exit(f"source not found: {SOURCE}")

    print("Building front matter...")
    front = build_front_matter(FRONT_TMP)
    print(f"  front matter: {len(front.pages)} pages")

    body = PdfReader(SOURCE)
    print(f"  source: {len(body.pages)} pages; keeping {BODY_STARTS_AT}-{len(body.pages)} unchanged")

    writer = PdfWriter()
    for page in front.pages:
        writer.add_page(page)
    for page in body.pages[BODY_STARTS_AT - 1:]:
        writer.add_page(page)

    # Document metadata carries the author name too - clear it.
    writer.add_metadata({
        "/Title": "Internship Based Project Report",
        "/Author": "",
        "/Subject": "6th Semester Internship Based Project Report",
        "/Creator": "",
        "/Producer": "",
    })

    with open(OUTPUT, "wb") as fh:
        writer.write(fh)
    print(f"\nWrote {OUTPUT}  ({len(writer.pages)} pages)")
    os.remove(FRONT_TMP)


if __name__ == "__main__":
    main()
