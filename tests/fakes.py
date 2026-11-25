"""Scripted stand-in for the model plus builders for test data. Tests never touch the network."""

from typing import Any

from storyteller.schemas import Brief, Check, Outline, Verdict


class FakeLLM:
    """Replies are scripted per role, in order. A reply may be a value, an exception (raised),
    or a callable(system, user) computing the value."""

    def __init__(self, script: dict[str, list[Any]]):
        self.script = {role: list(items) for role, items in script.items()}
        self.calls: list[tuple[str, str, str]] = []  # (role, system, user)

    def _next(self, role: str, system: str, user: str) -> Any:
        self.calls.append((role, system, user))
        queue = self.script.get(role)
        assert queue, f"FakeLLM: no scripted reply left for role {role!r}"
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item(system, user) if callable(item) else item

    def text(self, role, system, user):
        return self._next(role, system, user)

    def parse(self, role, system, user, schema):
        return self._next(role, system, user)

    def count(self, role: str) -> int:
        return sum(1 for r, _, _ in self.calls if r == role)

    def factory(self):
        """What pipeline.tell_story expects: usage hook -> LLM."""
        return lambda hook: self


def brief(**overrides) -> Brief:
    data = dict(reasoning="A story about Alice and her cat Bob.", is_story_request=True,
                can_be_made_safe=True, redirect_message="", category="friendship",
                characters=["Alice (a girl)", "Bob (Alice's cat)"], setting="", must_include=[],
                softened="", listener_name="", listener_age=0)
    data.update(overrides)
    return Brief(**data)


def outline(beats: int = 6) -> Outline:
    return Outline(title="Bob and the Moon", heart="Friends keep each other company.",
                   refrain="Hush now little moon", beats=[f"Beat {i}" for i in range(1, beats + 1)])


def verdict(fail: dict[str, str] | None = None) -> Verdict:
    """A verdict where every criterion passes except those in `fail` (name -> fix)."""
    fail = fail or {}
    checks = {name: Check(evidence="quote", passed=name not in fail, fix=fail.get(name, ""))
              for name in Verdict.model_fields}
    return Verdict(**checks)


SENTENCE = "Bob the cat looked out at the quiet garden and smiled at the moon."


def good_story(sentences: int = 40) -> str:
    """A story that passes every code check for the middle (7-8) band: ~560 words, grade ~3,
    five cues including the refrain twice."""
    body = [SENTENCE] * sentences
    n = sentences
    body[n // 8] += " [pause]"
    body[n // 4] = "[together: Hush now little moon] " + body[n // 4]
    body[n // 2] += " [whisper]"
    body[3 * n // 4] += " [pause]"
    body[-1] = "[together: Hush now little moon] " + body[-1]
    return "Bob and the Moon\n\n" + " ".join(body)
