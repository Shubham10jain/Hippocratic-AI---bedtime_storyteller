from storyteller.checks import check_story, fk_grade, parse_cues, strip_cues
from storyteller.config import band_for
from tests.fakes import SENTENCE, good_story

MIDDLE, YOUNG, OLDER = band_for(7), band_for(5), band_for(10)


def names(issues):
    return {i.name for i in issues}


def test_band_for_clamps_out_of_range_ages():
    assert band_for(3).key == "young"
    assert band_for(12).key == "older"
    assert band_for(8).key == "middle"


def test_parse_cues_reads_simple_and_valued_cues():
    cues = parse_cues("Hi [pause] there [voice: grumpy owl] and [together:  Hush now ]")
    assert [(c.name, c.value) for c in cues] == [("pause", ""), ("voice", "grumpy owl"), ("together", "Hush now")]


def test_strip_cues_keeps_refrain_words_and_cleans_spacing():
    text = "The owl hooted [pause]. [voice: grumpy owl] \"Hoo!\" [together: Hush now] they said."
    assert strip_cues(text) == 'The owl hooted. "Hoo!" Hush now they said.'


def test_good_story_passes_every_code_check():
    assert check_story(good_story(), MIDDLE) == []


def test_short_story_fails_length():
    assert "length" in names(check_story(good_story(sentences=10), MIDDLE))


def test_unknown_cue_is_flagged():
    assert "cue_format" in names(check_story(good_story() + " [dance]", MIDDLE))


def test_refrain_required_for_young_but_optional_for_older():
    story = good_story().replace("[together: Hush now little moon]", "[pause]")
    assert "refrain" in names(check_story(story, YOUNG))
    assert "refrain" not in names(check_story(story, OLDER))


def test_too_many_cues_for_older_listener():
    story = good_story().replace(SENTENCE, SENTENCE + " [pause]", 12)
    assert "cue_count" in names(check_story(story, OLDER))


def test_hard_vocabulary_fails_reading_level_for_young_listener():
    hard = ("The extraordinarily meticulous archaeologist contemplated incomprehensible "
            "philosophical considerations regarding civilization. ") * 40
    issues = check_story(hard + " [together: hush] [together: hush] " + "[pause] " * 6, YOUNG)
    assert "reading_level" in names(issues)


def test_fk_grade_orders_simple_below_complex():
    simple = "The cat sat. The dog ran. We had fun."
    complex_ = "Notwithstanding considerable environmental uncertainty, the committee deliberated extensively."
    assert fk_grade(simple) < fk_grade(complex_)
    assert fk_grade("") == 0.0


def test_length_fix_gives_a_concrete_word_delta():
    long_story = good_story(sentences=70)  # ~980 words, over the 750 limit for age 7-8
    fix = next(i.fix for i in check_story(long_story, MIDDLE) if i.name == "length")
    assert fix.startswith("Cut about") and "allowed 400-750" in fix
