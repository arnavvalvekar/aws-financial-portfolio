"""Build the 3-slide pitch deck as a themed .pptx.

Theme ties to the project: a dark "market" navy background, and the three pipeline-lane
colors from the README diagram — blue = data/backtest (A), magenta = agents (B),
green = evidence/story (C) — with a gold accent for highlights. Run:

    python presentation/build_deck.py

Output: presentation/portfolio-pitch.pptx
"""

from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Emu, Pt

# ---- project palette ---------------------------------------------------------
NAVY      = RGBColor(0x0B, 0x15, 0x22)   # background, the "market at night"
NAVY_CARD = RGBColor(0x13, 0x26, 0x3A)   # card fill
EDGE      = RGBColor(0x24, 0x45, 0x64)   # card borders
INK       = RGBColor(0xEA, 0xF1, 0xF8)   # primary text
MUTED     = RGBColor(0x9F, 0xB0, 0xC0)   # secondary text
BLUE      = RGBColor(0x1B, 0x5F, 0xA8)   # lane A — data & backtest
MAGENTA   = RGBColor(0x9B, 0x3F, 0x7E)   # lane B — agents
GREEN     = RGBColor(0x0E, 0x7A, 0x5F)   # lane C — evidence & story
GOLD      = RGBColor(0xF2, 0xC4, 0x5A)   # accent / placeholders
BLUE_LT   = RGBColor(0x7F, 0xA6, 0xCC)

EMU = 914400
SW, SH = int(13.333 * EMU), int(7.5 * EMU)  # 16:9

prs = Presentation()
prs.slide_width = SW
prs.slide_height = SH
BLANK = prs.slide_layouts[6]


def slide():
    s = prs.slides.add_slide(BLANK)
    bg = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, SW, SH)
    bg.fill.solid()
    bg.fill.fore_color.rgb = NAVY
    bg.line.fill.background()
    bg.shadow.inherit = False
    # a thin gold "ticker tape" rule near the top
    tape = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, in_(0.7), in_(1.18), in_(2.2), Pt(3))
    tape.fill.solid()
    tape.fill.fore_color.rgb = GOLD
    tape.line.fill.background()
    tape.shadow.inherit = False
    return s


def in_(v):
    return int(v * EMU)


def _set(tf_para_run, size, color, bold=False, italic=False):
    tf_para_run.font.size = Pt(size)
    tf_para_run.font.color.rgb = color
    tf_para_run.font.bold = bold
    tf_para_run.font.italic = italic
    tf_para_run.font.name = "Segoe UI"


def text(s, x, y, w, h, runs, align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP, space=4):
    """runs: list of paragraphs; each paragraph is a list of (text, size, color, bold, italic)."""
    tb = s.shapes.add_textbox(in_(x), in_(y), in_(w), in_(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    for i, para in enumerate(runs):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        p.space_after = Pt(space)
        for seg in para:
            t, size, color = seg[0], seg[1], seg[2]
            bold = seg[3] if len(seg) > 3 else False
            italic = seg[4] if len(seg) > 4 else False
            r = p.add_run()
            r.text = t
            _set(r, size, color, bold, italic)
    return tb


def card(s, x, y, w, h, fill=NAVY_CARD, edge=EDGE, edge_w=1.25):
    c = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, in_(x), in_(y), in_(w), in_(h))
    c.adjustments[0] = 0.06
    c.fill.solid()
    c.fill.fore_color.rgb = fill
    c.line.color.rgb = edge
    c.line.width = Pt(edge_w)
    c.shadow.inherit = False
    return c


def lane(s, x, y, w, h, title, body, edge):
    card(s, x, y, w, h, edge=edge, edge_w=2)
    tb = s.shapes.add_textbox(in_(x + 0.12), in_(y + 0.1), in_(w - 0.24), in_(h - 0.2))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    r = p.add_run(); r.text = title; _set(r, 13, INK, bold=True)
    p2 = tf.add_paragraph(); p2.alignment = PP_ALIGN.CENTER; p2.space_before = Pt(3)
    r2 = p2.add_run(); r2.text = body; _set(r2, 9.5, MUTED)


def arrow(s, x, y):
    a = s.shapes.add_shape(MSO_SHAPE.RIGHT_ARROW, in_(x), in_(y), in_(0.35), in_(0.3))
    a.fill.solid(); a.fill.fore_color.rgb = BLUE_LT
    a.line.fill.background(); a.shadow.inherit = False


def style_table(table, header_fill, placeholder_cells=()):
    for ri, row in enumerate(table.rows):
        for ci, cell in enumerate(row.cells):
            cell.fill.solid()
            cell.fill.fore_color.rgb = NAVY_CARD if ri else header_fill
            cell.margin_top = Pt(3); cell.margin_bottom = Pt(3)
            cell.margin_left = Pt(8); cell.margin_right = Pt(8)
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            para = cell.text_frame.paragraphs[0]
            para.alignment = PP_ALIGN.LEFT if ci == 0 else PP_ALIGN.CENTER
            for run in para.runs:
                _set(run, 13, INK if ri == 0 else INK, bold=(ri == 0))
                if (ri, ci) in placeholder_cells:
                    run.font.color.rgb = GOLD


def notes(s, body):
    s.notes_slide.notes_text_frame.text = body


# ============================= SLIDE 1 — FRAME IT =============================
s1 = slide()
text(s1, 0.7, 0.45, 12, 0.9,
     [[("Multi-agent portfolio research", 36, INK, True)]])
text(s1, 0.7, 1.35, 11.9, 0.9,
     [[("Five analyst agents plus a portfolio manager build a portfolio from data up to a "
        "cutoff. A backtest scores it against what the market did next.", 16, MUTED)]])

# fact strip as four lane-tinted cards
labels = [("Universe", "10 S&P 500 names\n7+ sectors", BLUE),
          ("Cutoff", "2026-01-30", MAGENTA),
          ("End scored", "2026-10-16", GREEN),
          ("Baselines", "SPY, equal weight", BLUE)]
cx, cw, gap = 0.7, 2.86, 0.23
for i, (k, v, col) in enumerate(labels):
    x = cx + i * (cw + gap)
    lane(s1, x, 2.5, cw, 1.25, k, v, col)

# no-peeking callout
card(s1, 0.7, 4.1, 11.93, 1.0, fill=RGBColor(0x1A, 0x24, 0x12), edge=RGBColor(0x5A, 0x6D, 0x1F))
text(s1, 0.95, 4.28, 11.5, 0.7,
     [[("No peeking.  ", 15, GOLD, True),
       ("One point-in-time guard is the only door to data, and a leakage test fails the "
        "run if any date slips past the cutoff.", 13.5, INK)]],
     anchor=MSO_ANCHOR.MIDDLE)

text(s1, 0.7, 5.35, 11.9, 0.5,
     [[("Historical experiment, not financial advice or a trading recommendation.",
        12, MUTED, False, True)]])

notes(s1, "20s. Say what it is and that it's a historical experiment, not advice. Point at "
          "the four cards: universe, cutoff, end date, baselines. One line on the "
          "point-in-time guard so judges know there's no look-ahead.")

# ===================== SLIDE 2 — HOW IT THINKS + ONE DECISION =================
s2 = slide()
text(s2, 0.7, 0.45, 12, 0.7, [[("How it thinks", 30, INK, True)]])

# pipeline: four lanes with arrows
lane_defs = [("Evidence", "prices · macro · filings\nnews · geopolitics\n(each claim cites an ID)", GREEN),
             ("5 analysts", "technical · fundamentals\nmacro · sentiment · geopolitics\nstance + confidence", MAGENTA),
             ("Portfolio manager", "reconciles conflicts into\nweights, rationale,\nsources, triggers", MAGENTA),
             ("Backtest", "vs SPY & equal weight\nfees, metrics", BLUE)]
lw, lh, ly = 2.74, 1.5, 1.4
lx = 0.7
for i, (t, b, col) in enumerate(lane_defs):
    lane(s2, lx, ly, lw, lh, t, b, col)
    if i < 3:
        arrow(s2, lx + lw + 0.02, ly + lh / 2 - 0.15)
    lx += lw + 0.39

text(s2, 0.7, 3.2, 12, 0.6, [[("Open one decision ", 22, INK, True),
                              ("— the biggest analyst disagreement", 15, GOLD, True)]])

card(s2, 0.7, 3.95, 5.9, 2.6, edge=MAGENTA, edge_w=2)
text(s2, 0.95, 4.15, 5.4, 2.3,
     [[("MSFT", 16, GOLD, True), ("  most contested (spread 0.78)", 12, MUTED)],
      [("Technical: ", 13, INK), ("-0.85", 13, GOLD), ("   Fundamentals: ", 13, INK), ("+0.90", 13, GOLD)],
      [("Conflict: ", 13, INK),
       ("weak price trend vs strong growth & margins", 13, GOLD)],
      [("Manager's call: ", 13, INK), ("8%", 13, GOLD),
       (" — sized down, not cut, until the trend confirms", 13, INK)]],
     space=8)

card(s2, 6.73, 3.95, 5.9, 2.6, edge=BLUE, edge_w=2)
text(s2, 6.98, 4.15, 5.4, 2.3,
     [[("Traceable by construction", 15, INK, True)],
      [("•  weights sum to 1, caps enforced in code", 13, MUTED)],
      [("•  cited IDs must exist in the evidence pack", 13, MUTED)],
      [("•  re-prompt once, then deterministic repair", 13, MUTED)]],
     space=8)

notes(s2, "~1:40. One sentence on the pipeline, one per analyst if time. Then open ONE "
          "decision: MSFT is the most contested (spread 0.78) - technical bearish (-0.85) "
          "on a weak trend, fundamentals bullish (+0.90) on growth/margins. Manager sized "
          "it to 8% rather than cutting. Picked by largest disagreement, not by which "
          "analyst won. Stress traceability: sources and the validator, not vibes.")

# ================= SLIDE 3 — WHAT HAPPENED + WHY TRUST IT ====================
s3 = slide()
text(s3, 0.7, 0.45, 12, 0.7, [[("What happened", 30, INK, True)]])

rows, cols = 4, 4
tbl_shape = s3.shapes.add_table(rows, cols, in_(0.7), in_(1.3), in_(11.93), in_(2.1))
table = tbl_shape.table
table.columns[0].width = in_(3.8)
for c in (1, 2, 3):
    table.columns[c].width = in_(2.71)
headers = ["Metric", "Portfolio", "SPY", "Equal weight"]
# from runs/final/metrics.json (frozen final run, cutoff 2026-01-30 -> 2026-10-16)
data = [
    ["Total return", "16.7%", "11.2%", "15.5%"],
    ["Sharpe",       "2.37",  "1.19",  "2.02"],
    ["Max drawdown", "-5.3%", "-8.9%", "-6.1%"],
]
for ci, h in enumerate(headers):
    table.cell(0, ci).text = h
for ri, row in enumerate(data, start=1):
    for ci, val in enumerate(row):
        table.cell(ri, ci).text = val
# highlight the portfolio column in gold
ph = {(1, 1), (2, 1), (3, 1)}
style_table(table, BLUE, placeholder_cells=ph)

text(s3, 0.7, 3.5, 11.93, 0.5,
     [[("Beats SPY on every measure, statistically close to equal weight. Beating the market "
        "isn't required - explaining the result and testing it against the baselines is.",
        11.5, MUTED, False, True)]])

card(s3, 0.7, 4.15, 5.9, 2.2, edge=BLUE, edge_w=2)
text(s3, 0.95, 4.33, 5.4, 1.9,
     [[("Why trust it", 15, INK, True)],
      [("•  leakage test on every run", 13, MUTED)],
      [("•  one cached, reproducible final run", 13, MUTED)],
      [("•  limitations stated, including model memory", 13, MUTED)]],
     space=8)

card(s3, 6.73, 4.15, 5.9, 2.2, edge=GREEN, edge_w=2)
text(s3, 6.98, 4.33, 5.4, 1.9,
     [[("What's next ", 15, INK, True), ("(stretch)", 12, GOLD, True)],
      [("Risk management", 13, INK, True), (" — watch the portfolio, detect regime "
        "shifts, feed lessons back to the manager", 12.5, MUTED)],
      [("CrashLab", 13, INK, True), (" — replay the weights through 2008, 2020 and "
        "invented shocks, propose protective changes", 12.5, MUTED)]],
     space=6)

text(s3, 0.7, 6.55, 11.93, 0.5,
     [[("Historical experiment, not financial advice.  Thanks — questions?",
        12, MUTED, False, True)]], align=PP_ALIGN.CENTER)

notes(s3, "~1:00. Portfolio 16.7% vs SPY 11.2% vs equal weight 15.5%, Sharpe 2.37 and the "
          "shallowest drawdown (-5.3%). Honest line: beats SPY in 5/5 uncached runs, beats "
          "equal weight in only 3/5 - say it's statistically close to equal weight, not a "
          "clear win. Top contributors AAPL and XOM. Close on credibility: leakage test, "
          "cached reproducible run, limitations (model memory, 180-day window). Risk "
          "management and CrashLab are built/in progress - frame as what's next.")

out = Path(__file__).resolve().parent / "portfolio-pitch.pptx"
prs.save(str(out))
print(f"saved {out}")
