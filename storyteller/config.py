"""Every tunable number in one place: model, per-role generation settings, judge loop, age bands."""

from dataclasses import dataclass
from typing import Literal

MODEL = "claude-haiku-5-5"  # required by the assignment email; used for every call

Effort = Literal["low", "medium", "high"]


@dataclass(frozen=True)
class RoleConfig:
    """Generation settings for one LLM role. Haiku 5.5 rejects `temperature`, so roles are
    tuned with `effort` (how much the model reasons before answering) instead."""

    max_tokens: int  # includes adaptive-thinking tokens, so leave headroom
    effort: Effort


ROLES: dict[str, RoleConfig] = {
    "intake": RoleConfig(max_tokens=3000, effort="low"),  # classify + safety + extraction
    "planner": RoleConfig(max_tokens=4000, effort="medium"),  # outline with a story arc
    "storyteller": RoleConfig(max_tokens=8000, effort="medium"),  # write and revise
    "judge": RoleConfig(max_tokens=8000, effort="high"),  # careful rubric review
    "baseline": RoleConfig(max_tokens=8000, effort="medium"),  # the original single call
    "pairwise": RoleConfig(max_tokens=4000, effort="medium"),  # eval-only comparison
}

MAX_REVISIONS = 2  # judge-driven rewrites after the first draft; bounds cost and latency
DEFAULT_AGE = 7  # used when neither the CLI nor the request gives an age
MIN_AGE, MAX_AGE = 5, 10


@dataclass(frozen=True)
class AgeBand:
    """What "appropriate for this age" means in numbers. The prompt guidance for each band
    lives in prompts/ages/<key>.md; code checks enforce the numbers below."""

    key: str
    ages: tuple[int, int]  # inclusive
    words: tuple[int, int]  # story length, cues excluded
    grade: tuple[float, float]  # Flesch-Kincaid grade range (stories are heard, so this is loose)
    cues: tuple[int, int]  # how many read-aloud cues
    refrain_required: bool  # must the child's join-in line come back at least twice?

    @property
    def target_words(self) -> int:
        """What prompts aim for: the middle of the range. Models overshoot "between X and Y"."""
        return int(round((self.words[0] + self.words[1]) / 2, -1))


AGE_BANDS = (
    AgeBand("young", (5, 6), words=(300, 600), grade=(0.0, 3.5), cues=(6, 18), refrain_required=True),
    AgeBand("middle", (7, 8), words=(400, 750), grade=(1.0, 5.0), cues=(4, 14), refrain_required=True),
    AgeBand("older", (9, 10), words=(500, 900), grade=(2.0, 7.0), cues=(2, 10), refrain_required=False),
)


def band_for(age: int) -> AgeBand:
    """The band covering `age`, clamped to the supported 5-10 range."""
    age = max(MIN_AGE, min(MAX_AGE, age))
    return next(b for b in AGE_BANDS if b.ages[0] <= age <= b.ages[1])
