"""The LLM roles. Each function is exactly one model call with its own system prompt.

    intake   request            -> Brief    (classify, safety gate, extract)
    plan     brief + listener   -> Outline  (six-beat arc, refrain)
    write    outline            -> story    (read-aloud script)
    revise   story + notes      -> story
    judge    story              -> Verdict  (sees the request, never the writer's prompt or outline)

Agents are stateless; pipeline.py decides when each one runs.
"""

from dataclasses import dataclass
from functools import cache
from pathlib import Path
from string import Template

from .config import AgeBand, band_for
from .llm import LLM, LLMError
from .schemas import Brief, Outline, Verdict

PROMPTS = Path(__file__).parent / "prompts"


@cache
def _template(name: str) -> Template:
    return Template((PROMPTS / f"{name}.md").read_text(encoding="utf-8"))


def prompt(name: str, **values) -> str:
    """Load prompts/<name>.md and fill its $placeholders. A missing value raises KeyError,
    so a typo in a template fails loudly instead of sending "$story" to the model."""
    return _template(name).substitute(**values).strip()


# ---- shared context ------------------------------------------------------------------------


@dataclass(frozen=True)
class Listener:
    age: int
    name: str
    band: AgeBand

    @classmethod
    def build(cls, age: int, name: str = "") -> "Listener":
        return cls(age=age, name=name.strip(), band=band_for(age))

    def profile(self) -> str:
        b = self.band
        return prompt(f"ages/{b.key}", age=self.age,
                      name_part=f", for a child named {self.name}" if self.name else "",
                      min_cues=b.cues[0], max_cues=b.cues[1],
                      min_words=b.words[0], max_words=b.words[1], target_words=b.target_words)


def render_context(request: str, brief: Brief, feedback: list[str]) -> str:
    """What was asked for, as every downstream role sees it. Empty fields are left out."""
    lines = [f'Request, word for word: "{request}"']
    if brief.characters:
        lines.append("Characters: " + "; ".join(brief.characters))
    if brief.setting:
        lines.append(f"Setting: {brief.setting}")
    if brief.must_include:
        lines.append("Must include: " + "; ".join(brief.must_include))
    if brief.softened:
        lines.append(f"Tell gently: {brief.softened}")
    if feedback:
        lines.append("Changes asked for after hearing the story (newest last). These take priority "
                     "over every other rule except safety:")
        lines += [f"  {i}. {f}" for i, f in enumerate(feedback, 1)]
    return "\n".join(lines)


def conversation(request: str, feedback: list[str]) -> str:
    """The text intake reads: the request, plus any change requests made since."""
    if not feedback:
        return request
    return "\n".join([f"Original request: {request}", "Changes asked for since:"]
                     + [f"- {f}" for f in feedback])


# ---- the roles -----------------------------------------------------------------------------


def intake(llm: LLM, text: str) -> Brief:
    return llm.parse("intake", prompt("intake"), text, Brief)


def plan(llm: LLM, request: str, brief: Brief, listener: Listener, sparks: list[str]) -> Outline:
    user = "\n\n".join([
        "## What the parent asked for\n" + render_context(request, brief, []),
        "## Listener profile\n" + listener.profile(),
        f"## Story strategy: {brief.category}\n" + prompt(f"categories/{brief.category}"),
        "## Optional sparks\nIf they fit naturally, you may use one or two of these to make the "
        "world specific. Ignore any that clash with the request.\n" + "\n".join(f"- {s}" for s in sparks),
    ])
    outline = llm.parse("planner", prompt("planner"), user, Outline)
    problems = validate_outline(outline)
    if problems:  # schema-valid but unusable: retry once with the problem spelled out
        outline = llm.parse("planner", prompt("planner"),
                            user + "\n\n## Fix this\nYour last plan had problems: " + "; ".join(problems), Outline)
        if validate_outline(outline):
            raise LLMError("The planner couldn't produce a usable outline.")
    return outline


def validate_outline(o: Outline) -> list[str]:
    problems = []
    if not 5 <= len(o.beats) <= 8:
        problems.append(f"expected six beats, got {len(o.beats)}")
    if not o.title.strip():
        problems.append("empty title")
    if not 2 <= len(o.refrain.split()) <= 10:
        problems.append("the refrain must be 3-8 words")
    return problems


def _story_task(request: str, brief: Brief, outline: Outline, listener: Listener,
                feedback: list[str], task: str) -> str:
    return prompt("story_task",
                  context=render_context(request, brief, feedback),
                  listener=listener.profile(),
                  category=brief.category,
                  strategy=prompt(f"categories/{brief.category}"),
                  title=outline.title, heart=outline.heart, refrain=outline.refrain,
                  beats="\n".join(f"{i}. {b}" for i, b in enumerate(outline.beats, 1)),
                  task=task)


def write(llm: LLM, request: str, brief: Brief, outline: Outline, listener: Listener,
          feedback: list[str]) -> str:
    task = prompt("write_task", target_words=listener.band.target_words, max_words=listener.band.words[1])
    return llm.text("storyteller", prompt("storyteller"),
                    _story_task(request, brief, outline, listener, feedback, task))


def revise(llm: LLM, request: str, brief: Brief, outline: Outline, listener: Listener,
           feedback: list[str], story: str, notes: str) -> str:
    task = prompt("revise_task", target_words=listener.band.target_words, max_words=listener.band.words[1],
                  notes=notes, story=story)
    return llm.text("storyteller", prompt("storyteller"),
                    _story_task(request, brief, outline, listener, feedback, task))


def judge(llm: LLM, request: str, brief: Brief, listener: Listener, feedback: list[str],
          story: str) -> Verdict:
    system = prompt("judge", context=render_context(request, brief, feedback), listener=listener.profile())
    return llm.parse("judge", system, f"STORY:\n{story}", Verdict)
