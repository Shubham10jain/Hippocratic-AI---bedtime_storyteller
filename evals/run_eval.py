"""Does the pipeline actually beat the original single call? Run: python -m evals.run_eval

For each request in evals/requests.json:
  - story cases: generate a baseline story (the skeleton's single call, same model) and a
    pipeline story, then ask a pairwise judge which is better TWICE with the order swapped.
    Only a preference that survives the swap counts as a win; otherwise it's a tie.
    Both stories are compared with read-aloud cues stripped, so the cues can't sway the judge.
  - gate cases: check that the request is redirected (or, for the injection case, that any
    story produced passed the safety judge).

Writes evals/results.md (summary table) and evals/samples/<id>.md (both stories, for reading).
"""

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from dotenv import load_dotenv

from storyteller.agents import prompt
from storyteller.checks import fk_grade, strip_cues, words
from storyteller.llm import ClaudeClient
from storyteller.pipeline import baseline, tell_story
from storyteller.schemas import Preference

HERE = Path(__file__).parent


def pairwise(llm: ClaudeClient, request: str, age: int, a: str, b: str) -> str:
    user = f"Request: {request}\nListener age: {age}\n\nSTORY A:\n{a}\n\nSTORY B:\n{b}"
    return llm.parse("pairwise", prompt("pairwise"), user, Preference).winner


def run_case(case: dict) -> dict:
    llm = ClaudeClient()
    result = tell_story(lambda hook: ClaudeClient(on_usage=hook), case["request"], age=case["age"], seed=7)
    row = {"id": case["id"], "expect": case["expect"], "status": result.status, "trace": result.trace_path}
    if case["expect"] == "redirect":
        row["ok"] = result.status == "redirect"
        row["message"] = result.message
        return row
    if case["expect"] == "redirect_or_gentle":
        row["ok"] = result.status in ("redirect", "unsafe") or (
            result.status == "story" and not result.session.story.evaluation.unsafe)
        row["message"] = result.message
        if result.status != "story":
            return row
    if result.status != "story":
        row["ok"] = False
        row["message"] = result.message
        return row

    base = baseline(llm, case["request"])
    mine = strip_cues(result.text)
    first = pairwise(llm, case["request"], case["age"], mine, base)  # pipeline is A
    second = pairwise(llm, case["request"], case["age"], base, mine)  # pipeline is B
    if first == "A" and second == "B":
        verdict = "pipeline"
    elif first == "B" and second == "A":
        verdict = "baseline"
    else:
        verdict = "tie"
    ev = result.session.story.evaluation
    row.update(ok=True, winner=verdict, judge_passed=ev.passed, kept_round=result.session.story.round,
               open_issues=[i.name for i in ev.issues],
               words=(len(words(mine)), len(words(base))),
               grade=(round(fk_grade(mine), 1), round(fk_grade(base), 1)),
               pipeline_story=result.text, baseline_story=base)
    return row


def write_reports(rows: list[dict]) -> None:
    (HERE / "samples").mkdir(exist_ok=True)
    stories = [r for r in rows if "winner" in r]
    wins = sum(r["winner"] == "pipeline" for r in stories)
    losses = sum(r["winner"] == "baseline" for r in stories)
    lines = ["# Eval results", "",
             f"Pairwise (position-swapped) vs. the original single call: **{wins} wins, {losses} losses, "
             f"{len(stories) - wins - losses} ties** out of {len(stories)} story requests.", "",
             "| case | expected | status | winner | judge passed | revisions kept | words (pipeline / baseline) | FK grade (pipeline / baseline) |",
             "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        if "winner" in r:
            lines.append(f"| {r['id']} | {r['expect']} | {r['status']} | {r['winner']} | {r['judge_passed']} | "
                         f"{r['kept_round']} | {r['words'][0]} / {r['words'][1]} | {r['grade'][0]} / {r['grade'][1]} |")
            (HERE / "samples" / f"{r['id']}.md").write_text(
                f"# {r['id']}\n\n## Pipeline (read-aloud script)\n\n{r['pipeline_story']}\n\n"
                f"## Baseline (original single call)\n\n{r['baseline_story']}\n", encoding="utf-8")
        else:
            ok = "ok" if r.get("ok") else "FAILED"
            lines.append(f"| {r['id']} | {r['expect']} | {r['status']} ({ok}) | - | - | - | - | - |")
    gate = [r for r in rows if "winner" not in r]
    if gate:
        lines += ["", "Gate messages:", ""] + [f"- **{r['id']}**: {r.get('message')}" for r in gate]
    (HERE / "results.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


def main() -> None:
    load_dotenv()
    cases = json.loads((HERE / "requests.json").read_text())
    only = set(sys.argv[1:])
    if only:
        cases = [c for c in cases if c["id"] in only]
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(run_case, cases))
    write_reports(rows)


if __name__ == "__main__":
    main()
