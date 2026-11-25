"""Orchestration: intake -> plan -> write -> (judge + code checks -> revise)* -> present -> feedback.

All control flow lives here in plain Python; agents.py holds one model call per role, and the
acceptance rule lives in schemas.Evaluation. Every run writes a JSON trace to runs/.
"""

import json
import logging
import random
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Literal

from . import agents
from .agents import Listener
from .checks import check_story
from .config import DEFAULT_AGE, MAX_REVISIONS
from .ingredients import pick_sparks
from .llm import LLM, LLMError, RefusalError
from .schemas import Brief, Evaluation, Outline

log = logging.getLogger(__name__)

UNSAFE_MESSAGE = ("I couldn't make a story from that which I'd be happy to tell at bedtime. "
                  "Could we try a different idea?")
ERROR_MESSAGE = "Sorry, something went wrong while making your story: {detail}"


# ---- state ---------------------------------------------------------------------------------


@dataclass
class Draft:
    round: int  # 0 = first draft, then 1..MAX_REVISIONS
    text: str
    evaluation: Evaluation
    notes_sent: str | None = None  # the revision notes this draft was written from


@dataclass
class Session:
    """One conversation. brief/outline/story stay None until a story is delivered."""

    request: str
    listener: Listener
    feedback: list[str] = field(default_factory=list)
    brief: Brief | None = None
    outline: Outline | None = None
    story: Draft | None = None


@dataclass
class Result:
    status: Literal["story", "redirect", "unsafe", "error"]
    session: Session
    text: str | None = None  # the story, when status == "story"
    message: str | None = None  # what to show instead, otherwise
    trace_path: str | None = None


class Trace:
    """Everything that happened in one turn, written as one JSON file for debugging and evals."""

    def __init__(self, runs_dir: str | None):
        self.runs_dir = runs_dir
        self.data: dict = {"started": datetime.now(timezone.utc).isoformat(), "calls": [], "events": []}

    def on_usage(self, usage: dict) -> None:
        self.data["calls"].append(usage)

    def event(self, stage: str, **info) -> None:
        self.data["events"].append({"stage": stage, **info})

    def write(self) -> str | None:
        if not self.runs_dir:
            return None
        calls = self.data["calls"]
        self.data["totals"] = {
            "calls": len(calls),
            "input_tokens": sum(c["input_tokens"] for c in calls),
            "output_tokens": sum(c["output_tokens"] for c in calls),
        }
        Path(self.runs_dir).mkdir(parents=True, exist_ok=True)
        path = Path(self.runs_dir) / f"{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}.json"
        path.write_text(json.dumps(self.data, indent=2, default=str), encoding="utf-8")
        return str(path)


# ---- the judge loop ------------------------------------------------------------------------


def evaluate(llm: LLM, s: Session, text: str) -> Evaluation:
    """LLM judge plus code checks. A judge failure is recorded, not raised: the story can
    still be shown, and the trace says it went unjudged."""
    code_issues = check_story(text, s.listener.band)
    try:
        verdict = agents.judge(llm, s.request, s.brief, s.listener, s.feedback, text)
    except LLMError as e:
        log.warning("judge failed: %s", e)
        return Evaluation(verdict=None, code_issues=code_issues, judge_error=str(e))
    return Evaluation(verdict=verdict, code_issues=code_issues)


def judge_and_revise(llm: LLM, s: Session, first: Draft, trace: Trace) -> Draft:
    """Revise until the draft passes or MAX_REVISIONS is used up; return the best draft seen.

    Each revision starts from the best draft so far, with that draft's notes, so one bad
    rewrite can't drag the story backwards.
    """
    best = first
    _log_draft(trace, best)
    for rnd in range(1, MAX_REVISIONS + 1):
        if best.evaluation.passed or best.evaluation.verdict is None:
            break  # nothing to fix, or no judge notes to fix it with
        notes = best.evaluation.revision_notes()
        log.info("  revising (round %d)...", rnd)
        log.debug("%s", notes)
        text = agents.revise(llm, s.request, s.brief, s.outline, s.listener, s.feedback, best.text, notes)
        candidate = Draft(rnd, text, evaluate(llm, s, text), notes)
        _log_draft(trace, candidate)
        if candidate.evaluation.rank() <= best.evaluation.rank():
            best = candidate
    trace.event("kept", round=best.round, passed=best.evaluation.passed)
    return best


def _log_draft(trace: Trace, d: Draft) -> None:
    ev = d.evaluation
    issues = [asdict(i) for i in ev.issues]
    log.info("  judge round %d: %s", d.round,
             "passed" if ev.passed else ", ".join(i["name"] for i in issues) or "unjudged")
    trace.event("draft", round=d.round, text=d.text, notes_sent=d.notes_sent, passed=ev.passed,
                issues=issues, judge_error=ev.judge_error,
                verdict=ev.verdict.model_dump() if ev.verdict else None)


# ---- turns ---------------------------------------------------------------------------------


def _gate(llm: LLM, s: Session, trace: Trace) -> tuple[Brief | None, str | None]:
    """Run intake on the whole conversation. Returns (brief, None) or (None, redirect message)."""
    brief = agents.intake(llm, agents.conversation(s.request, s.feedback))
    trace.event("intake", brief=brief.model_dump())
    if brief.is_story_request and brief.can_be_made_safe:
        return brief, None
    return None, brief.redirect_message or UNSAFE_MESSAGE


def _first_story(llm: LLM, s: Session, trace: Trace, rng: random.Random, age_given: bool) -> Result:
    log.info("Reading your request...")
    brief, redirect = _gate(llm, s, trace)
    if redirect:
        return Result("redirect", s, message=redirect)
    s.brief = brief
    if not age_given and brief.listener_age:  # the request said "for my 6-year-old"
        s.listener = Listener.build(brief.listener_age, s.listener.name or brief.listener_name)
    elif brief.listener_name and not s.listener.name:
        s.listener = Listener.build(s.listener.age, brief.listener_name)
    log.info("  category: %s | listener age %d", brief.category, s.listener.age)

    log.info("Planning the story...")
    sparks = pick_sparks(rng)
    s.outline = agents.plan(llm, s.request, brief, s.listener, sparks)
    trace.event("plan", sparks=sparks, outline=s.outline.model_dump())
    log.debug("  title: %s | refrain: %s\n%s", s.outline.title, s.outline.refrain,
              "\n".join(f"  {i}. {b}" for i, b in enumerate(s.outline.beats, 1)))

    log.info("Writing...")
    text = agents.write(llm, s.request, brief, s.outline, s.listener, s.feedback)
    return _finish(llm, s, Draft(0, text, evaluate(llm, s, text)), trace)


def _feedback_turn(llm: LLM, s: Session, feedback: str, trace: Trace) -> Result:
    """Apply one change request. Unless a new story is delivered, the session is restored, so a
    rejected or failed change never leaks into later turns."""
    previous_feedback, previous_brief = list(s.feedback), s.brief
    trace.event("feedback", change=feedback)
    s.feedback = previous_feedback + [feedback]
    result = None
    try:
        brief, redirect = _gate(llm, s, trace)  # the change request goes through the same safety gate
        if redirect:
            result = Result("redirect", s, message=redirect)
            return result
        # Keep the original category and plan; take any newly requested details from the new brief.
        s.brief = brief.model_copy(update={"category": previous_brief.category})
        log.info("Rewriting with your changes...")
        notes = f"- [user request, must fix] {feedback}"
        text = agents.revise(llm, s.request, s.brief, s.outline, s.listener, s.feedback, s.story.text, notes)
        result = _finish(llm, s, Draft(0, text, evaluate(llm, s, text), notes), trace)
        return result
    finally:
        if result is None or result.status != "story":
            s.feedback, s.brief = previous_feedback, previous_brief


def _finish(llm: LLM, s: Session, first: Draft, trace: Trace) -> Result:
    best = judge_and_revise(llm, s, first, trace)
    if best.evaluation.unsafe:  # never show a story the judge flagged as unsafe
        return Result("unsafe", s, message=UNSAFE_MESSAGE)
    s.story = best
    return Result("story", s, text=best.text)


MakeLLM = Callable[[Callable[[dict], None]], LLM]  # usage hook -> client


def _run(s: Session, make_llm: MakeLLM, runs_dir: str | None,
         turn: Callable[[LLM, Trace], Result]) -> Result:
    """Shared wrapper for every turn: build the client, map failures to user-safe results,
    and always write the trace."""
    trace = Trace(runs_dir)
    trace.data.update(request=s.request, feedback=list(s.feedback), listener=asdict(s.listener))
    start = time.monotonic()
    try:
        result = turn(make_llm(trace.on_usage), trace)
    except RefusalError:
        result = Result("unsafe", s, message=UNSAFE_MESSAGE)
    except LLMError as e:
        trace.event("error", detail=str(e))
        result = Result("error", s, message=ERROR_MESSAGE.format(detail=e))
    trace.data["seconds"] = round(time.monotonic() - start, 1)
    trace.data["status"] = result.status
    result.trace_path = trace.write()
    return result


def tell_story(make_llm: MakeLLM, request: str, age: int | None = None, name: str = "",
               seed: int | None = None, runs_dir: str | None = "runs") -> Result:
    """Start a session and produce the first story.

    `make_llm` takes a usage hook and returns an LLM, so each turn's calls land in that turn's
    trace (tests pass a factory that returns a scripted fake). An explicit `age` wins over one
    stated in the request.
    """
    s = Session(request=request, listener=Listener.build(age or DEFAULT_AGE, name))
    rng = random.Random(seed)
    return _run(s, make_llm, runs_dir,
                lambda llm, trace: _first_story(llm, s, trace, rng, age_given=age is not None))


def give_feedback(make_llm: MakeLLM, session: Session, feedback: str,
                  runs_dir: str | None = "runs") -> Result:
    """Revise the delivered story with one change request, through the same gate and judge."""
    if session.story is None:
        raise ValueError("There is no story to change yet.")
    return _run(session, make_llm, runs_dir,
                lambda llm, trace: _feedback_turn(llm, session, feedback, trace))


def baseline(llm: LLM, request: str) -> str:
    """The original skeleton's behaviour, for comparison: one call, the bare request, no system prompt."""
    return llm.text("baseline", "", request)
