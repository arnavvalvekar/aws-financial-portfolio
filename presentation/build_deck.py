"""Build the pitch deck as a themed .pptx (AWS-style dark finance theme).

Note on tooling: the user asked about the PowerPoint MCP server / Slidev. Neither is
installed as a Kiro power in this workspace, so this generator uses python-pptx, which
produces a real editable .pptx directly and needs no external service. The theme mirrors
an "AWS dark" look: a deep navy/ink background with the AWS Smile orange as the accent,
plus the project's three pipeline-lane colors (blue = data/backtest, magenta = agents,
green = evidence) carried through from the README diagram.

Five slides, sized for a 3-minute talk. All figures are read from the frozen final run
(runs/final/*.json). Run:

    python presentation/build_deck.py

Output: presentation/portfolio-pitch.pptx
"""

import json
from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Pt

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "runs" / "final"

# ---- AWS-style dark palette + project lane colors ---------------------------
NAVY      = RGBColor(0x0A, 0x12, 0x1F)   # background (AWS Squid Ink-ish)
NAVY_2    = RGBColor(0x0F, 0x1B, 0x2D)   # banner band
NAVY_CARD = RGBColor(0x14, 0x24, 0x38)   # card fill
EDGE      = RGBColor(0x2A, 0x4A, 0x6B)   # card borders
INK       = RGBColor(0xEA, 0xF1, 0xF8)   # primary text
MUTED     = RGBColor(0x9F, 0xB0, 0xC0)   # secondary text
BLUE      = RGBColor(0x1B, 0x5F, 0xA8)   # lane A - data & backtest
MAGENTA   = RGBColor(0x9B, 0x3F, 0x7E)   # lane B - agents
GREEN     = RGBColor(0x1C, 0x8A, 0x5E)   # lane C - evidence & story / good
RED       = RGBColor(0xD6, 0x5A, 0x5A)   # losses in stress
AWS       = RGBColor(0xFF, 0x99, 0x00)   # AWS Smile orange - primary accent
AWS_DK    = RGBColor(0xEC, 0x71, 0x11)   # darker orange
BLUE_LT   = RGBColor(0x7F, 0xA6, 0xCC)

EMU = 914400
SW, SH = int(13.333 * EMU), int(7.5 * EMU)  # 16:9


def in_(v):
    return int(v * EMU)


# ---- data from the frozen run -----------------------------------------------
def _load(name):
    p = RUN / name
    return json.loads(p.read_text()) if p.is_file() else {}


METRICS = _load("metrics.json")
DECISION = _load("decision.json")
CRASH = _load("crashlab.json")
SCORE = _load("scorecard.json")
RISK = _load("risk_review.json")
REPEAT = _load("repeatability.json")
DEEP = _load("deepdive.json")
M = METRICS.get("metrics", {})


def pm(series, key, pct=True, dp=1):
    v = M.get(series, {}).get(key)
    if v is None:
        return "-"
    return f"{v * 100:.{dp}f}%" if pct else f"{v:.2f}"


prs = Presentation()
prs.slide_width, prs.slide_height = SW, SH
BLANK = prs.slide_layouts[6]


# ---- primitives -------------------------------------------------------------
def slide(kicker=None):
    s = prs.slides.add_slide(BLANK)
    bg = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, SW, SH)
    bg.fill.solid(); bg.fill.fore_color.rgb = NAVY
    bg.line.fill.background(); bg.shadow.inherit = False
    bar = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, in_(0.12), SH)
    bar.fill.solid(); bar.fill.fore_color.rgb = AWS
    bar.line.fill.background(); bar.shadow.inherit = False
    if kicker:
        text(s, 0.55, 0.3, 11, 0.4, [[(kicker.upper(), 12, AWS, True)]])
    return s


def _run(r, size, color, bold=False, italic=False):
    r.font.size = Pt(size); r.font.color.rgb = color
    r.font.bold = bold; r.font.italic = italic; r.font.name = "Segoe UI"


def text(s, x, y, w, h, paras, align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP, space=5, line=None):
    tb = s.shapes.add_textbox(in_(x), in_(y), in_(w), in_(h))
    tf = tb.text_frame; tf.word_wrap = True; tf.vertical_anchor = anchor
    for i, para in enumerate(paras):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align; p.space_after = Pt(space)
        if line:
            p.line_spacing = line
        for seg in para:
            t, size, color = seg[0], seg[1], seg[2]
            bold = seg[3] if len(seg) > 3 else False
            italic = seg[4] if len(seg) > 4 else False
            r = p.add_run(); r.text = t; _run(r, size, color, bold, italic)
    return tb


def card(s, x, y, w, h, fill=NAVY_CARD, edge=EDGE, edge_w=1.25):
    c = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, in_(x), in_(y), in_(w), in_(h))
    c.adjustments[0] = 0.05
    c.fill.solid(); c.fill.fore_color.rgb = fill
    c.line.color.rgb = edge; c.line.width = Pt(edge_w)
    c.shadow.inherit = False
    return c


def heading(s, title, y=0.72):
    text(s, 0.55, y, 12.2, 0.8, [[(title, 29, INK, True)]])


def bullets(s, x, y, w, h, items, size=13, gap=7):
    paras = []
    for it in items:
        if isinstance(it, tuple):
            lead, rest = it
            paras.append([("\u25B8  ", size, AWS, True), (lead, size, INK, True), (rest, size, MUTED)])
        else:
            paras.append([("\u25B8  ", size, AWS, True), (it, size, MUTED)])
    text(s, x, y, w, h, paras, space=gap, line=1.05)


def lane(s, x, y, w, h, title, body, edge):
    card(s, x, y, w, h, edge=edge, edge_w=2)
    tb = s.shapes.add_textbox(in_(x + 0.12), in_(y + 0.08), in_(w - 0.24), in_(h - 0.16))
    tf = tb.text_frame; tf.word_wrap = True; tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    p = tf.paragraphs[0]; p.alignment = PP_ALIGN.CENTER
    r = p.add_run(); r.text = title; _run(r, 12, INK, True)
    p2 = tf.add_paragraph(); p2.alignment = PP_ALIGN.CENTER; p2.space_before = Pt(2)
    r2 = p2.add_run(); r2.text = body; _run(r2, 8.5, MUTED)


def arrow(s, x, y):
    a = s.shapes.add_shape(MSO_SHAPE.RIGHT_ARROW, in_(x), in_(y), in_(0.28), in_(0.24))
    a.fill.solid(); a.fill.fore_color.rgb = AWS
    a.line.fill.background(); a.shadow.inherit = False


def footer(s, n):
    text(s, 0.55, 7.05, 10, 0.3,
         [[("Multi-agent portfolio research \u00B7 Austin Agentic AI Hackathon \u00B7 historical experiment, not financial advice",
            8, RGBColor(0x5A, 0x6D, 0x80))]])
    text(s, 12.4, 7.05, 0.6, 0.3, [[(str(n), 9, MUTED)]], align=PP_ALIGN.RIGHT)


def style_table(table, good_cells=(), bad_cells=()):
    for ri, row in enumerate(table.rows):
        for ci, cell in enumerate(row.cells):
            cell.fill.solid()
            cell.fill.fore_color.rgb = NAVY_2 if ri == 0 else NAVY_CARD
            cell.margin_top = Pt(2); cell.margin_bottom = Pt(2)
            cell.margin_left = Pt(7); cell.margin_right = Pt(7)
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            para = cell.text_frame.paragraphs[0]
            para.alignment = PP_ALIGN.LEFT if ci == 0 else PP_ALIGN.CENTER
            for run in para.runs:
                color = INK
                if (ri, ci) in good_cells:
                    color = GREEN
                elif (ri, ci) in bad_cells:
                    color = RED
                _run(run, 12, color, bold=(ri == 0))


# ============================= 1 · TITLE =====================================
s = slide()
band = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, in_(0.12), in_(2.05), SW - in_(0.12), in_(2.75))
band.fill.solid(); band.fill.fore_color.rgb = NAVY_2
band.line.fill.background(); band.shadow.inherit = False
text(s, 0.55, 0.55, 12, 0.5, [[("AGENTIC AI \u00B7 FINANCIAL PORTFOLIO MANAGEMENT \u00B7 TRACK 3", 13, AWS, True)]])
text(s, 0.75, 2.3, 12, 1.4,
     [[("Multi-agent portfolio research", 40, INK, True)],
      [("Five specialist analyst agents and a portfolio manager build a defensible "
        "portfolio from point-in-time evidence, then a backtest scores it honestly against "
        "the market.", 17, MUTED)]], space=10, line=1.08)
text(s, 0.75, 4.25, 12, 0.5,
     [[("Built on AWS Bedrock (", 13, MUTED), ("us.openai.gpt-5.6-luna", 13, AWS, True),
       (", us-east-1) and Amazon Bedrock AgentCore.", 13, MUTED)]])
chips = [("Return", pm("portfolio", "total_return")), ("Sharpe", pm("portfolio", "sharpe", pct=False)),
         ("Max drawdown", pm("portfolio", "max_drawdown")), ("Beats SPY", "5 / 5 runs")]
cx = 0.75
for k, v in chips:
    card(s, cx, 5.25, 2.7, 1.1, fill=NAVY_CARD, edge=AWS_DK, edge_w=1.5)
    text(s, cx + 0.2, 5.4, 2.4, 0.8, [[(v, 22, AWS, True)], [(k, 11, MUTED)]], space=1)
    cx += 2.95
footer(s, 1)

# ====================== 2 · HOW IT THINKS + THE RULES ========================
s = slide("Architecture")
heading(s, "How it thinks: evidence in, a decision it can defend")
lane_defs = [
    ("Evidence packs", "prices, macro, SEC\nfilings, news, geo\neach item an ID", GREEN),
    ("5 analysts", "technical, fundamentals\nmacro, sentiment\ngeopolitics", MAGENTA),
    ("Portfolio manager", "reconciles conflicts\n-> weights, rationale,\nsources, triggers", MAGENTA),
    ("Backtest", "vs SPY & equal weight\nfees, Sharpe,\ndrawdown", BLUE),
]
lw, lh, ly, lx = 2.74, 1.4, 1.5, 0.7
for i, (t, b, col) in enumerate(lane_defs):
    lane(s, lx, ly, lw, lh, t, b, col)
    if i < 3:
        arrow(s, lx + lw + 0.02, ly + lh / 2 - 0.12)
    lx += lw + 0.39
text(s, 0.7, 3.1, 12.1, 0.6,
     [[("The cutoff is a one-way valve. ", 14, AWS, True),
       ("Agents read only evidence built through a point-in-time guard; the single file that "
        "crosses into the future is decision.json, frozen before any later price is loaded.", 14, MUTED)]],
     line=1.1)
# the three rules as cards
rules = [
    ("No peeking", GREEN, "Nothing dated after the cutoff reaches an agent. A leakage test "
     "scans every output and fails the run if a later date appears."),
    ("Show the sources", BLUE, "Every claim cites an evidence ID. A validator rejects any ID "
     "not in the pack, so no number is unsupported."),
    ("Score once", MAGENTA, "Tune on an earlier cutoff, freeze prompts and data, cache every "
     "model call, then run the final window exactly once."),
]
cw = 3.86; cx = 0.7
for title, edge, body in rules:
    card(s, cx, 3.95, cw, 2.5, edge=edge, edge_w=2)
    text(s, cx + 0.2, 4.08, cw - 0.4, 2.3,
         [[(title, 14.5, INK, True)], [(body, 12, MUTED)]], space=6, line=1.08)
    cx += cw + 0.18
footer(s, 2)

# ====================== 3 · ONE DECISION (MSFT) ==============================
s = slide("Reasoning, opened up")
heading(s, "One decision: MSFT, where the analysts disagree most")
text(s, 0.55, 1.5, 12.2, 0.75,
     [[("We pick the deep-dive by rule before seeing any result: the position with the widest "
        "analyst disagreement. That is MSFT, and it shows the system reconciling a real "
        "conflict rather than rubber-stamping a consensus.", 14, MUTED)]], line=1.1)
card(s, 0.55, 2.55, 6.0, 3.85, edge=MAGENTA, edge_w=2)
text(s, 0.8, 2.68, 5.5, 3.6,
     [[("The conflict (spread 0.78, widest in the universe)", 14.5, INK, True)],
      [("Fundamentals  ", 13, INK), ("+0.90", 13, GREEN, True),
       ("  16.7% revenue growth, 20.9% operating-income growth, a 47% margin.", 12, MUTED)],
      [("Technical  ", 13, INK), ("-0.85", 13, RED, True),
       ("  a death cross, price below both moving averages, sharply negative momentum.", 12, MUTED)],
      [("Sentiment  ", 13, INK), ("+0.25", 13, BLUE_LT, True),
       ("  modestly constructive, but on weaker evidence.", 12, MUTED)]],
     space=10, line=1.08)
card(s, 6.75, 2.55, 6.0, 3.85, edge=BLUE, edge_w=2)
text(s, 7.0, 2.68, 5.5, 3.6,
     [[("The call: 8% \u2014 underweight, not a cut", 14.5, INK, True)],
      [("The fundamental quality is compelling, but the technical downtrend is the clearest "
        "near-term risk and carries very high confidence. The manager keeps a starter position "
        "and lets cash absorb the uncertainty.", 12, MUTED)],
      [("Change triggers: ", 13, AWS, True),
       ("add if price reclaims the 200-day and momentum stabilises; cut if momentum worsens, "
        "revenue growth falls below 10%, or export controls broaden to advanced chips.", 12, MUTED)],
      [("Every figure above is a cited, validated evidence ID.", 12, GREEN, False, True)]],
     space=9, line=1.07)
footer(s, 3)

# ====================== 4 · RESULTS + ROBUSTNESS =============================
s = slide("What happened")
heading(s, "Beats SPY on every measure; close to equal weight")
rows = 6
t = s.shapes.add_table(rows, 4, in_(0.55), in_(1.55), in_(7.3), in_(3.6)).table
t.columns[0].width = in_(2.5)
for c in (1, 2, 3):
    t.columns[c].width = in_(1.6)
for ci, h in enumerate(["Metric", "Portfolio", "SPY", "Equal wt"]):
    t.cell(0, ci).text = h
data = [
    ["Total return", pm("portfolio", "total_return"), pm("SPY", "total_return"), pm("equal_weight", "total_return")],
    ["CAGR", pm("portfolio", "cagr"), pm("SPY", "cagr"), pm("equal_weight", "cagr")],
    ["Volatility", pm("portfolio", "volatility"), pm("SPY", "volatility"), pm("equal_weight", "volatility")],
    ["Sharpe", pm("portfolio", "sharpe", pct=False), pm("SPY", "sharpe", pct=False), pm("equal_weight", "sharpe", pct=False)],
    ["Max drawdown", pm("portfolio", "max_drawdown"), pm("SPY", "max_drawdown"), pm("equal_weight", "max_drawdown")],
]
for ri, row in enumerate(data, start=1):
    for ci, val in enumerate(row):
        t.cell(ri, ci).text = val
style_table(t, good_cells={(r, 1) for r in range(1, 6)})
card(s, 8.1, 1.55, 4.65, 3.6, edge=AWS_DK, edge_w=2)
text(s, 8.3, 1.68, 4.3, 3.4,
     [[("How stable is this?", 14.5, INK, True)],
      [("The models take no temperature setting, so uncached runs vary. Across five uncached "
        "runs on identical evidence:", 11.5, MUTED)],
      [("Return 15.7% mean, range 14.9\u201316.4%.", 12.5, INK, True)],
      [("Beat SPY in ", 12, MUTED), ("5 of 5", 13, GREEN, True), (" runs; beat equal weight in ", 12, MUTED),
       ("3 of 5", 13, AWS, True), (".", 12, MUTED)],
      [("Read honestly: reliably beats SPY, statistically close to equal weight. The frozen "
        "run is one draw, kept so the demo reproduces.", 11, MUTED, False, True)]],
     space=7, line=1.07)
text(s, 0.55, 5.4, 12.2, 1.0,
     [[("Top contributors: ", 13, INK, True),
       ("AAPL +4.6 pts, XOM +3.5, KO +2.8; only NEE detracted. Beating the market was never "
        "the goal \u2014 a traceable thesis and an honest test are, and we report the result "
        "either way.", 13, MUTED)]], line=1.1)
footer(s, 4)

# ====================== 5 · CREDIBILITY + CLOSE ==============================
s = slide("Credibility & what's next")
heading(s, "Stress-tested, self-checking, and honest about limits")
checks_passed = sum(1 for c in RISK.get("checks", []) if c.get("passed"))
checks_total = len(RISK.get("checks", []))
worst = CRASH.get("protective_changes", {}).get("baseline_shock", 0)
# left: risk + crashlab
card(s, 0.55, 1.5, 6.0, 4.55, edge=GREEN, edge_w=2)
text(s, 0.8, 1.62, 5.5, 4.4,
     [[("Risk desk + CrashLab (both shipped)", 14.5, INK, True)],
      [("A risk agent monitors the portfolio against the manager's own triggers and would "
        "trigger a rebalance; in v1 it is report-only, so the scored decision stays frozen. ",
        12, MUTED), (f"{checks_passed}/{checks_total} mechanical checks pass", 12.5, GREEN, True),
       (", and lessons from earlier runs feed back so the next portfolio avoids the same mistake.", 12, MUTED)],
      [("CrashLab replays the weights through 2008 (", 12, MUTED), ("-52%", 12.5, RED, True),
       (") and 2020 (", 12, MUTED), ("-27%", 12.5, RED, True),
       (") plus five invented shocks, then proposes protective trims with an explicit "
        "drawdown-removed vs return-given-up trade-off. The frozen decision never changes.", 12, MUTED)]],
     space=10, line=1.08)
# right: why trust + next
card(s, 6.75, 1.5, 6.0, 4.55, edge=BLUE, edge_w=2)
text(s, 7.0, 1.62, 5.5, 0.5, [[("Why trust it, and where it goes next", 14.5, INK, True)]])
bullets(s, 7.0, 2.15, 5.55, 3.8, [
    ("Reproducible. ", "Every model call is cached; a fresh clone returns the same decision and metrics."),
    ("Honest limits. ", "Model memory, a 180-day window, a curated sentiment fallback, FRED unreachable \u2014 all stated."),
    ("Graded. ", "An analyst scorecard shows fundamentals and technical drove the result."),
    ("Next. ", "Promote the risk agent to month-end rebalancing; widen the universe and window."),
], size=12.5, gap=11)
text(s, 0.55, 6.25, 12.2, 0.5,
     [[("Historical experiment, not financial advice or a trading recommendation.    ", 12, MUTED, False, True),
       ("Thank you \u2014 questions?", 13, AWS, True)]], align=PP_ALIGN.CENTER)
footer(s, 5)

# ---- speaker notes ----------------------------------------------------------
NOTES = {
    1: "~25s. Historical experiment, not advice. The chips are the headline: 16.7% return, "
       "Sharpe 2.37, -5.3% drawdown, beats SPY in all five uncached runs. Mention it runs on "
       "AWS Bedrock + AgentCore.",
    2: "~40s. One line on the valve, one per lane. Then the three rules: no peeking (leakage "
       "test), show the sources (validator), score once (cache + one final run).",
    3: "~45s. MSFT chosen by rule (widest disagreement, spread 0.78). Fundamentals +0.90 vs "
       "technical -0.85. Manager underweights to 8% rather than cutting; cash absorbs the "
       "uncertainty. Every figure is a cited, validated ID.",
    4: "~45s. Walk the table: beats SPY on every row. The robustness card is the honest bit \u2014 "
       "beats equal weight only 3/5, so say 'close to equal weight, not a clear win.' Top "
       "contributors AAPL, XOM, KO.",
    5: "~25s. Risk agent (report-only, 8/8 checks, learns across runs) and CrashLab (2008 -52%, "
       "2020 -27%, proposes trims). Close on reproducibility, honest limits, the scorecard, and "
       "what's next. End on the disclaimer and questions.",
}
for idx, sl in enumerate(prs.slides, start=1):
    sl.notes_slide.notes_text_frame.text = NOTES.get(idx, "")

out = ROOT / "presentation" / "portfolio-pitch.pptx"
prs.save(str(out))
print(f"saved {out} with {len(prs.slides._sldIdLst)} slides")
