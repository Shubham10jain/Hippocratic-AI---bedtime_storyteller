from storyteller.config import MAX_REVISIONS
from storyteller.llm import LLMError, RefusalError
from storyteller.pipeline import give_feedback, tell_story
from tests.fakes import FakeLLM, brief, good_story, outline, verdict

STORY = good_story()


def run(llm: FakeLLM, **kw):
    return tell_story(llm.factory(), "Alice and her cat Bob", runs_dir=None, seed=1, **kw)


def test_story_that_passes_first_time_uses_four_calls():
    llm = FakeLLM({"intake": [brief()], "planner": [outline()], "storyteller": [STORY], "judge": [verdict()]})
    result = run(llm)
    assert result.status == "story" and result.text == STORY
    assert [r for r, _, _ in llm.calls] == ["intake", "planner", "storyteller", "judge"]


def test_failed_draft_is_revised_with_the_judges_fix():
    revised = STORY.replace("smiled", "grinned")
    llm = FakeLLM({"intake": [brief()], "planner": [outline()], "storyteller": [STORY, revised],
                   "judge": [verdict({"story_arc": "Add a first try that fails in paragraph 2."}), verdict()]})
    result = run(llm)
    assert result.text == revised
    revise_prompt = llm.calls[-2][2]
    assert "Add a first try that fails in paragraph 2." in revise_prompt
    assert result.session.story.round == 1


def test_loop_is_bounded_when_the_judge_never_passes():
    failing = verdict({"read_aloud": "fewer cues"})
    llm = FakeLLM({"intake": [brief()], "planner": [outline()],
                   "storyteller": [STORY] * (MAX_REVISIONS + 1), "judge": [failing] * (MAX_REVISIONS + 1)})
    result = run(llm)
    assert result.status == "story"  # soft failures still deliver the best draft
    assert llm.count("storyteller") == MAX_REVISIONS + 1
    assert llm.count("judge") == MAX_REVISIONS + 1


def test_worse_revision_is_discarded():
    worse = STORY.replace("smiled", "frowned")
    llm = FakeLLM({"intake": [brief()], "planner": [outline()], "storyteller": [STORY, worse, worse],
                   "judge": [verdict({"read_aloud": "fewer cues"}),
                             verdict({"bedtime_ending": "end calmly"}),
                             verdict({"bedtime_ending": "end calmly"})]})
    result = run(llm)
    assert result.text == STORY and result.session.story.round == 0


def test_off_topic_request_is_redirected_before_any_writing():
    llm = FakeLLM({"intake": [brief(is_story_request=False, redirect_message="I only tell stories!")]})
    result = run(llm)
    assert result.status == "redirect" and result.message == "I only tell stories!"
    assert llm.count("planner") == 0


def test_story_that_stays_unsafe_is_never_shown():
    unsafe = verdict({"safety": "remove the fight"})
    llm = FakeLLM({"intake": [brief()], "planner": [outline()],
                   "storyteller": [STORY] * (MAX_REVISIONS + 1), "judge": [unsafe] * (MAX_REVISIONS + 1)})
    result = run(llm)
    assert result.status == "unsafe" and result.text is None and result.session.story is None


def test_judge_failure_still_delivers_the_story_without_revising():
    llm = FakeLLM({"intake": [brief()], "planner": [outline()], "storyteller": [STORY],
                   "judge": [LLMError("judge down")]})
    result = run(llm)
    assert result.status == "story" and llm.count("storyteller") == 1
    assert result.session.story.evaluation.judge_error == "judge down"


def test_refusal_becomes_a_friendly_message():
    result = run(FakeLLM({"intake": [RefusalError("no")]}))
    assert result.status == "unsafe" and "bedtime" in result.message


def test_writer_failure_becomes_an_error_result():
    llm = FakeLLM({"intake": [brief()], "planner": [outline()], "storyteller": [LLMError("ran out of room")]})
    result = run(llm)
    assert result.status == "error" and "ran out of room" in result.message


def test_invalid_outline_is_retried_once():
    llm = FakeLLM({"intake": [brief()], "planner": [outline(beats=2), outline()],
                   "storyteller": [STORY], "judge": [verdict()]})
    assert run(llm).status == "story" and llm.count("planner") == 2


def test_age_in_request_is_used_unless_cli_age_given():
    # The middle-band fixture story fails the young band's cue count, so allow revisions.
    script = lambda: {"intake": [brief(listener_age=5, listener_name="Maya")], "planner": [outline()],
                      "storyteller": [STORY] * 3, "judge": [verdict()] * 3}
    from_request = run(FakeLLM(script()))
    assert from_request.session.listener.age == 5 and from_request.session.listener.name == "Maya"
    from_cli = run(FakeLLM(script()), age=9)
    assert from_cli.session.listener.band.key == "older"


def test_feedback_revises_the_delivered_story():
    llm = FakeLLM({"intake": [brief(), brief()], "planner": [outline()],
                   "storyteller": [STORY, STORY + " The end."], "judge": [verdict(), verdict()]})
    first = run(llm)
    second = give_feedback(llm.factory(), first.session, "make Bob sillier", runs_dir=None)
    assert second.status == "story" and second.text.endswith("The end.")
    assert second.session.feedback == ["make Bob sillier"]
    assert "[user request, must fix] make Bob sillier" in llm.calls[-2][2]


def test_failed_feedback_turn_restores_the_session():
    llm = FakeLLM({"intake": [brief(), brief(category="silly")], "planner": [outline()],
                   "storyteller": [STORY, LLMError("ran out of room")], "judge": [verdict()]})
    first = run(llm)
    second = give_feedback(llm.factory(), first.session, "add a dragon", runs_dir=None)
    assert second.status == "error"
    assert second.session.feedback == [] and second.session.story.text == STORY


def test_rejected_feedback_is_not_recorded_and_story_is_kept():
    llm = FakeLLM({"intake": [brief(), brief(can_be_made_safe=False, redirect_message="Let's keep it gentle.")],
                   "planner": [outline()], "storyteller": [STORY], "judge": [verdict()]})
    first = run(llm)
    second = give_feedback(llm.factory(), first.session, "make it gory", runs_dir=None)
    assert second.status == "redirect" and second.session.feedback == []
    assert second.session.story.text == STORY
