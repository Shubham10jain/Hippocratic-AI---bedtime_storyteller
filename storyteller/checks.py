"""Deterministic checks on a story: read-aloud cues, length and reading level for the child's age.

These run alongside the LLM judge. They are cheap, never flaky, and they catch the things a model
grading its own family's writing is worst at noticing (length drift, vocabulary creep).

Cue syntax (taught in prompts/storyteller.md):
    [pause] [whisper] [softly] [slowly] [yawn]   performance cues for the parent
    [voice: grumpy owl]                          how to voice the next line of dialogue
    [sound: whoosh]                              a sound the parent makes
    [together: Hush now, little moon]            the refrain; the child says it along
"""

import re
from dataclasses import dataclass

from .config import AgeBand
from .schemas import Issue

SIMPLE_CUES = {"pause", "whisper", "softly", "slowly", "yawn"}
VALUED_CUES = {"voice", "sound", "together"}
CUE_RE = re.compile(r"\[\s*([a-zA-Z]+)\s*(?::\s*([^\]]*?))?\s*\]")


@dataclass(frozen=True)
class Cue:
    name: str
    value: str  # "" for simple cues


def parse_cues(text: str) -> list[Cue]:
    return [Cue(m.group(1).lower(), (m.group(2) or "").strip()) for m in CUE_RE.finditer(text)]


def strip_cues(text: str) -> str:
    """Plain story text: refrain cues keep their words, every other cue is removed."""

    def repl(m: re.Match) -> str:
        return (m.group(2) or "").strip() if m.group(1).lower() == "together" else ""

    plain = CUE_RE.sub(repl, text)
    plain = re.sub(r"[ \t]+([,.!?;:])", r"\1", plain)  # "word [pause]." -> "word."
    plain = re.sub(r"[ \t]{2,}", " ", plain)
    return "\n".join(line.strip() for line in plain.splitlines()).strip()


# ---- readability (Flesch-Kincaid grade, stdlib only) ---------------------------------------

_WORD_RE = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?")
_SENTENCE_RE = re.compile(r"[.!?]+")


def words(text: str) -> list[str]:
    return _WORD_RE.findall(text)


def count_syllables(word: str) -> int:
    """Vowel-group heuristic; good enough for a range check, not for linguistics."""
    w = word.lower()
    if len(w) <= 3:
        return 1
    w = re.sub(r"(?:[^laeiouy]es|ed|[^laeiouy]e)$", "", w)
    w = re.sub(r"^y", "", w)
    return max(1, len(re.findall(r"[aeiouy]{1,2}", w)))


def fk_grade(text: str) -> float:
    ws = words(text)
    if not ws:
        return 0.0
    sentences = max(1, len([s for s in _SENTENCE_RE.split(text) if words(s)]))
    syllables = sum(count_syllables(w) for w in ws)
    return 0.39 * (len(ws) / sentences) + 11.8 * (syllables / len(ws)) - 15.59


# ---- the checks ----------------------------------------------------------------------------


def check_story(text: str, band: AgeBand) -> list[Issue]:
    """Every code-detectable problem with `text` for a listener in `band`. Empty list = clean."""
    issues: list[Issue] = []
    cues = parse_cues(text)
    plain = strip_cues(text)
    n_words = len(words(plain))

    lo, hi = band.words
    if not lo <= n_words <= hi:
        # Models can't count, so give a concrete delta toward the middle, not just the limit.
        delta = abs(n_words - band.target_words)
        action = f"Cut about {delta} words" if n_words > hi else f"Add about {delta} words"
        how = ("by trimming description and repeated beats, not the ending" if n_words > hi
               else "by adding sensory detail and dialogue to the middle beats")
        issues.append(Issue("length", False,
                            f"{action} {how} (now {n_words}; allowed {lo}-{hi}).", "code"))

    grade = fk_grade(plain)
    g_lo, g_hi = band.grade
    if grade > g_hi:
        issues.append(Issue("reading_level", False,
                            f"Language is too hard for this age (grade {grade:.1f}, target <= {g_hi}). "
                            "Use shorter sentences and simpler, everyday words.", "code"))
    elif grade < g_lo:
        issues.append(Issue("reading_level", False,
                            f"Language is too babyish for this age (grade {grade:.1f}, target >= {g_lo}). "
                            "Vary sentence length and use a few richer words.", "code"))

    unknown = sorted({c.name for c in cues if c.name not in SIMPLE_CUES | VALUED_CUES})
    if unknown:
        issues.append(Issue("cue_format", False,
                            f"Remove or replace unknown cues {unknown}; use only the cues listed in the rules.", "code"))

    c_lo, c_hi = band.cues
    if not c_lo <= len(cues) <= c_hi:
        direction = "Use fewer" if len(cues) > c_hi else "Add more"
        issues.append(Issue("cue_count", False,
                            f"{direction} read-aloud cues: {c_lo}-{c_hi} for this age (now {len(cues)}).", "code"))

    refrains = [c for c in cues if c.name == "together" and c.value]
    if band.refrain_required and len(refrains) < 2:
        issues.append(Issue("refrain", False,
                            "Bring the refrain back with [together: ...] at least twice, including near the end.",
                            "code"))
    return issues
