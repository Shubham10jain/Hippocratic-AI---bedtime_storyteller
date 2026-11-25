"""Renders docs/architecture.png in a hand-drawn style. Dev-only: pip install matplotlib.

    python docs/draw_architecture.py
"""

import logging
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Circle, FancyBboxPatch  # noqa: E402

logging.getLogger("matplotlib.font_manager").setLevel(logging.ERROR)
OUT = Path(__file__).parent / "architecture.png"
INK = "#222222"
LLM = "#6a4c93"  # purple edge = LLM call
CODE = "#2e7d32"  # green edge = plain Python


def box(ax, x, y, w, h, title, bullets=(), edge=INK, title_size=13):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.05,rounding_size=0.25",
                                fill=False, ec=edge, lw=1.8))
    ax.text(x + w / 2, y + h - 0.35, title, ha="center", va="top", fontsize=title_size, color=INK)
    top = y + h - (1.4 if "\n" in title else 0.95)
    for i, b in enumerate(bullets):
        ax.text(x + 0.25, top - i * 0.42, f"- {b}", ha="left", va="top", fontsize=9.5, color=INK)


def circle(ax, cx, cy, r, title, edge=INK, size=12):
    ax.add_patch(Circle((cx, cy), r, fill=False, ec=edge, lw=1.8))
    ax.text(cx, cy, title, ha="center", va="center", fontsize=size, color=INK)


def note(ax, x, y, lines, size=9.5, title=None):
    if title:
        ax.text(x, y, title, ha="left", va="top", fontsize=size + 1, color=INK)
        y -= 0.45
    for i, line in enumerate(lines):
        ax.text(x, y - i * 0.38, f"- {line}", ha="left", va="top", fontsize=size, color=INK)


def arrow(ax, start, end, label="", rad=0.0, style="-", lpos=None, lsize=9.5, color=INK, lw=1.4):
    ax.annotate("", xy=end, xytext=start,
                arrowprops=dict(arrowstyle="-|>", color=color, lw=lw, linestyle=style,
                                connectionstyle=f"arc3,rad={rad}", shrinkA=2, shrinkB=2))
    if label:
        lx, ly = lpos or ((start[0] + end[0]) / 2, (start[1] + end[1]) / 2 + 0.25)
        ax.text(lx, ly, label, ha="center", va="center", fontsize=lsize, color=INK)


def main() -> None:
    with plt.xkcd(scale=0.6, length=120, randomness=2):
        fig, ax = plt.subplots(figsize=(24, 13.5), dpi=110)
        ax.set_xlim(0, 24)
        ax.set_ylim(-0.7, 13.5)
        ax.axis("off")

        # ---- user -------------------------------------------------------------------------
        box(ax, 0.3, 6.6, 2.9, 2.6, "User (CLI)")
        box(ax, 0.55, 6.85, 2.4, 1.6, "", title_size=1)
        note(ax, 0.75, 8.2, ["request", "--age, --name", "feedback loop"])

        # ---- orchestrator -----------------------------------------------------------------
        box(ax, 4.3, 4.4, 3.0, 6.0, "Pipeline\n(orchestrator)",
            ["routes the steps", "judge loop (max 2)", "keep best draft", "failure ->", "  friendly message"],
            edge=CODE)

        # ---- LLM roles --------------------------------------------------------------------
        box(ax, 8.9, 9.0, 3.4, 2.0, "Intake (LLM)", ["classify category", "safety gate", "extract brief"], edge=LLM)
        box(ax, 8.9, 6.1, 3.4, 2.0, "Planner (LLM)", ["6-beat story arc", "refrain + heart", "uses 3 random sparks"], edge=LLM)
        box(ax, 13.9, 9.0, 3.6, 2.0, "Storyteller (LLM)", ["write read-aloud script", "revise drafts", "[pause] [voice:] [together:]"], edge=LLM)
        box(ax, 13.9, 5.6, 3.6, 2.1, "Judge (LLM)", ["7 criteria", "evidence -> pass/fail -> fix", "never sees the outline"], edge=LLM)
        box(ax, 13.9, 1.9, 3.6, 2.8, "Code Checks", ["length (words to cut/add)", "reading level (FK)", "cue format + count", "refrain >= 2"], edge=CODE)

        # ---- stores / services ------------------------------------------------------------
        circle(ax, 20.2, 10.1, 1.25, "Claude\nHaiku 5.5", edge=LLM)
        note(ax, 21.6, 11.0, ["every LLM call", "effort per role", "structured outputs", "refusal / max_tokens", "  checks"])
        circle(ax, 20.2, 5.4, 1.25, "Prompts\n(*.md)")
        note(ax, 21.6, 6.6, ["intake.md", "planner.md", "storyteller.md", "judge.md", "revise_task.md",
                             "categories/ (5)", "ages/ (3)"], title="prompts/")
        circle(ax, 5.8, 1.7, 1.1, "Trace\nruns/*.json", size=11)
        circle(ax, 1.75, 2.6, 1.3, "Listener\nProfile", edge=CODE)
        note(ax, 0.3, 0.95, ["age -> young / middle / older", "target words, reading grade",
                             "cue count, refrain needed?"], size=9)

        # ---- schemas (like a DB table listing) --------------------------------------------
        note(ax, 8.9, 4.55, ["safety          (hard)", "bedtime_ending (hard)", "request_fit     (hard)",
                            "consistency    (hard)", "story_arc       (soft)", "age_fit           (soft)",
                            "read_aloud     (soft)"], size=9, title="Verdict")
        note(ax, 11.6, 4.55, ["title", "heart", "refrain", "beats[6]"], size=9, title="Outline")
        note(ax, 11.6, 2.45, ["category", "characters", "is safe?", "listener_age"], size=9, title="Brief")

        # ---- arrows -----------------------------------------------------------------------
        arrow(ax, (3.2, 8.6), (4.3, 8.6), "request", lpos=(3.75, 8.9))
        arrow(ax, (3.2, 7.4), (4.3, 7.4), style="--")
        ax.text(3.75, 7.1, "change\nrequest", ha="center", va="top", fontsize=9)
        arrow(ax, (4.6, 4.4), (1.9, 6.6), "story / redirect /\nsafe message", rad=-0.35, lpos=(2.2, 5.1))

        arrow(ax, (7.3, 10.0), (8.9, 10.0), "request")
        arrow(ax, (8.9, 9.3), (7.3, 8.9), "brief", rad=0.15, lpos=(8.1, 8.75))
        arrow(ax, (7.3, 7.1), (8.9, 7.1), "brief + profile", lpos=(8.1, 7.4))
        arrow(ax, (12.3, 7.4), (13.9, 9.6), "outline", lpos=(12.75, 8.75))
        arrow(ax, (15.7, 9.0), (15.7, 7.7), "draft", lpos=(16.15, 8.35))
        arrow(ax, (15.0, 5.6), (15.0, 4.7), "same draft", lpos=(15.95, 5.15))

        # the judge loop: the heart of the design
        arrow(ax, (17.5, 6.4), (17.5, 9.5), "fail -> revision notes\n(safety > hard > soft)\nmax 2 rounds",
              rad=0.55, lpos=(18.45, 7.75), lw=2.6, color=LLM)
        # big top arc: orchestrator drives the writer
        arrow(ax, (5.8, 10.4), (15.7, 11.0), "write / revise (best draft so far + notes)",
              rad=-0.22, lpos=(10.7, 12.55), lw=1.6)
        # results back to the orchestrator
        arrow(ax, (13.9, 5.9), (7.3, 5.4), "verdict + code issues  ->  passed?  keep best?  safe?",
              lpos=(10.6, 5.25), lsize=9)
        arrow(ax, (13.9, 3.6), (13.9, 5.6), "", rad=-0.6, style=":")

        arrow(ax, (17.5, 10.4), (18.95, 10.4), "llm.py", style="--", lpos=(18.2, 10.75))
        arrow(ax, (18.95, 5.3), (17.5, 6.2), "loaded\nper role", style=":", lpos=(18.3, 5.0))
        arrow(ax, (5.8, 4.4), (5.8, 2.8), "log every draft,\nverdict, tokens", style=":", lpos=(6.95, 3.6))
        arrow(ax, (2.9, 3.4), (4.3, 5.0), "age profile", style=":", lpos=(3.15, 4.45))

        # ---- legend + title ---------------------------------------------------------------
        ax.text(17.0, 0.95, "purple = LLM call (Claude Haiku 5.5)    green = plain Python", fontsize=10, color=INK)
        ax.text(17.0, 0.45, "clean run: 4 calls / ~30 s    2 revisions: 8 calls / ~70 s", fontsize=10, color=INK)
        ax.text(12.0, -0.45, "Final Design", ha="center", fontsize=16, color=INK)

        fig.savefig(OUT, bbox_inches="tight", facecolor="white")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
