import typing

import pytest

from storyteller.agents import PROMPTS, Listener, prompt, render_context
from storyteller.schemas import Category, Evaluation, Issue
from tests.fakes import brief, verdict


def test_evaluation_passes_only_when_judge_and_code_are_clean():
    assert Evaluation(verdict()).passed
    assert not Evaluation(verdict({"story_arc": "add a try that fails"})).passed
    assert not Evaluation(verdict(), code_issues=[Issue("length", False, "shorten", "code")]).passed
    assert not Evaluation(None, judge_error="boom").passed  # unjudged is never "passed"


def test_rank_puts_unsafe_last_and_unjudged_below_judged():
    unsafe = Evaluation(verdict({"safety": "remove the fight"}))
    hard = Evaluation(verdict({"bedtime_ending": "end calmly"}))
    soft = Evaluation(verdict({"read_aloud": "fewer cues"}))
    clean = Evaluation(verdict())
    unjudged = Evaluation(None)
    assert sorted([unsafe, hard, soft, clean, unjudged], key=Evaluation.rank) == [clean, soft, hard, unjudged, unsafe]


def test_revision_notes_put_safety_then_hard_then_soft():
    ev = Evaluation(verdict({"read_aloud": "R", "safety": "S", "request_fit": "F"}),
                    code_issues=[Issue("length", False, "L", "code")])
    lines = ev.revision_notes().splitlines()
    assert lines[0].startswith("- [safety, must fix]")
    assert lines[1].startswith("- [request_fit, must fix]")
    assert {line.split("]")[0] for line in lines[2:]} == {"- [read_aloud", "- [length"}


def test_failed_check_with_empty_fix_still_produces_a_note():
    ev = Evaluation(verdict({"story_arc": ""}))
    assert "story_arc" in ev.revision_notes()


def test_every_category_has_a_strategy_prompt():
    for category in typing.get_args(Category):
        assert (PROMPTS / "categories" / f"{category}.md").exists(), category


@pytest.mark.parametrize("age", [5, 7, 10])
def test_listener_profile_renders_for_every_band(age):
    text = Listener.build(age, "Maya").profile()
    assert "Maya" in text and "$" not in text


def test_prompt_templates_fail_loudly_on_missing_values():
    with pytest.raises(KeyError):
        prompt("revise_task", target_words=1, max_words=2)  # notes and story missing


def test_context_includes_feedback_with_priority_note():
    text = render_context("a cat story", brief(), ["make it funnier"])
    assert "make it funnier" in text and "priority" in text
