"""Show one position's reasoning in plain text, for the demo.

    python show_position.py            # the most contested position in runs/final
    python show_position.py MSFT       # a specific ticker
    python show_position.py MSFT --run runs/dev-xyz
"""

import argparse
import json
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BOLD, DIM, END = "\033[1m", "\033[2m", "\033[0m"
ANALYSTS = ["technical", "fundamentals", "macro", "sentiment", "geopolitics"]


def wrap(text, indent="    "):
    return textwrap.fill(text, width=100, initial_indent=indent, subsequent_indent=indent)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("ticker", nargs="?")
    p.add_argument("--run", default="runs/final")
    a = p.parse_args()
    run = ROOT / a.run
    decision = json.loads((run / "decision.json").read_text())
    agreement = json.loads((run / "disagreement.json").read_text())
    ticker = (a.ticker or agreement["most_contested"][0]).upper()
    pos, spread = decision["positions"][ticker], agreement["by_ticker"][ticker]

    rank = agreement["most_contested"].index(ticker) + 1 if ticker in agreement["most_contested"] else None
    print(f"{BOLD}{ticker}: {decision['weights'][ticker]:.0%} of the portfolio{END}  "
          f"(analyst disagreement {spread['spread']:.2f}" + (f", #{rank} most contested)" if rank else ")"))
    print(f"\n{BOLD}What each analyst said{END}")
    for name in ANALYSTS:
        report = json.loads((run / "analysts" / f"{name}.json").read_text())
        v = next(x for x in report["views"] if x["ticker"] == ticker)
        print(f"  {name:<13} stance {v['stance']:+.2f}  confidence {v['confidence']:.2f}")
        print(wrap(v["thesis"], "      "))
    print(f"\n{BOLD}How the manager weighed them{END}")
    print("  " + ", ".join(f"{k} {v:.0%}" for k, v in sorted(pos["analyst_weighting"].items(), key=lambda kv: -kv[1]) if v))
    print(f"\n{BOLD}Manager's rationale{END}")
    print(wrap(pos["rationale"], "  "))
    print(f"\n{BOLD}Where the analysts conflicted{END}")
    for c in pos["conflicts"]:
        print(wrap("- " + c, "  "))
    print(f"\n{BOLD}What would change the position{END}")
    for t in pos["change_triggers"]:
        print(wrap("- " + t, "  "))
    print(f"\n{DIM}Every claim cites evidence: {len(pos['sources'])} sources, e.g. {pos['sources'][0]}{END}")
    review = run / "risk_review.json"
    if review.exists():
        r = json.loads(review.read_text())
        print(f"{DIM}Risk review of the whole portfolio: {r['verdict']} ({r['mode']}){END}")


if __name__ == "__main__":
    main()
