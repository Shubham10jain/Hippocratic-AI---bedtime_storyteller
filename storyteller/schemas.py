"""Structured outputs exchanged with the model, plus the acceptance rule (decided in code).

Brief, Outline, Verdict and Preference are sent to the API as structured-output schemas, so the
field order matters: evidence/reasoning fields come first so the model reasons before it commits.
"""

from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field

Category = Literal["cozy", "adventure", "silly", "friendship", "comfort"]


# ---- schemas the model fills in ------------------------------------------------------------


class Brief(BaseModel):
    """Intake: is this a story request we can tell safely, and what exactly was asked for?"""

    reasoning: str = Field(description="One or two sentences on what the person is asking for and any safety concern.")
    is_story_request: bool
    can_be_made_safe: bool
    redirect_message: str = Field(description='A kind one-sentence reply if either check above is false, else "".')
    category: Category
    characters: list[str] = Field(description='Characters the person named, each with a short role, e.g. "Bob (Alice\'s cat)". Empty if none.')
    setting: str = Field(description='The place they named, or "" if none.')
    must_include: list[str] = Field(description="Specific things they asked for that the story must contain.")
    softened: str = Field(description='What must be told more gently for ages 5-10, or "" if nothing.')
    listener_name: str = Field(description='The child the story is for, if named (not a character), else "".')
    listener_age: int = Field(description="The child's age if the request states it, else 0.")


class Outline(BaseModel):
    """Planner: a story arc the storyteller follows beat by beat."""

    title: str
    heart: str = Field(description="The gentle feeling or idea the child is left with, in one sentence.")
    refrain: str = Field(description="A short, rhythmic line (3-8 words) that returns through the story for the child to say along.")
    beats: list[str] = Field(description="Six beats in order, one or two sentences each.")


class Check(BaseModel):
    """The judge's verdict on one rubric criterion."""

    evidence: str = Field(description="A short quote or specific reference from the story. Write this first.")
    passed: bool
    fix: str = Field(description='If failed: one concrete instruction saying WHERE and WHAT to change. If passed: "".')


class Verdict(BaseModel):
    """Judge: one Check per rubric criterion. Pass/fail is computed in code, not by the judge."""

    safety: Check
    bedtime_ending: Check
    request_fit: Check
    consistency: Check
    story_arc: Check
    age_fit: Check
    read_aloud: Check


class Preference(BaseModel):
    """Eval-only pairwise comparison of two stories for the same request."""

    reasoning: str
    winner: Literal["A", "B", "tie"]


# ---- types only our code uses --------------------------------------------------------------

HARD_CRITERIA = ("safety", "bedtime_ending", "request_fit", "consistency")  # must pass to accept a draft
SOFT_CRITERIA = ("story_arc", "age_fit", "read_aloud")  # failing triggers revision only


@dataclass(frozen=True)
class Issue:
    """One thing wrong with a draft, from the judge or from a code check."""

    name: str
    hard: bool
    fix: str
    source: Literal["judge", "code"]


@dataclass
class Evaluation:
    """Everything known about one draft's quality. `verdict` is None if the judge call failed."""

    verdict: Verdict | None
    code_issues: list[Issue] = field(default_factory=list)
    judge_error: str | None = None

    @property
    def issues(self) -> list[Issue]:
        judged = []
        if self.verdict is not None:
            for name in HARD_CRITERIA + SOFT_CRITERIA:
                check: Check = getattr(self.verdict, name)
                if not check.passed:
                    fix = check.fix or f"Improve {name}: {check.evidence}"
                    judged.append(Issue(name, name in HARD_CRITERIA, fix, "judge"))
        return judged + self.code_issues

    @property
    def unsafe(self) -> bool:
        return self.verdict is not None and not self.verdict.safety.passed

    @property
    def passed(self) -> bool:
        """Accepted when the judge ran and nothing failed (code checks included)."""
        return self.verdict is not None and not self.issues

    def rank(self) -> tuple[bool, bool, int, int]:
        """Sort key, lower is better: unsafe first, then unjudged, then hard and soft counts."""
        issues = self.issues
        return (self.unsafe, self.verdict is None,
                sum(i.hard for i in issues), sum(not i.hard for i in issues))

    def revision_notes(self) -> str:
        """Bullet list for the storyteller: safety first, then other hard issues, then soft."""
        order = sorted(self.issues, key=lambda i: (i.name != "safety", not i.hard))
        return "\n".join(
            f"- [{i.name}{', must fix' if i.hard else ''}] {i.fix}" for i in order)
