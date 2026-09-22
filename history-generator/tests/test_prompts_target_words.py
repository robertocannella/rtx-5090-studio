import prompts


def test_estimate_target_words_matches_original_fixed_guidance_at_speed_1():
    # The original hardcoded prompt targeted "150-220 words" (185 midpoint) for "60-90s"
    # (75 midpoint) at implied speed 1.0 -- the formula should reproduce that baseline.
    words = prompts.estimate_target_words(75.0, speed=1.0, sentence_gap_seconds=0.0)
    assert abs(words - 185) <= 2


def test_estimate_target_words_scales_down_with_slower_speed():
    # This is the exact bug from the field report: a 60s target at speed 0.85 produced a
    # 90.8s segment because word count wasn't speed-adjusted. Slower speed must ask for
    # fewer words to hit the same target duration.
    words_normal = prompts.estimate_target_words(60.0, speed=1.0, sentence_gap_seconds=0.0)
    words_slow = prompts.estimate_target_words(60.0, speed=0.85, sentence_gap_seconds=0.0)
    assert words_slow < words_normal


def test_estimate_target_words_scales_up_with_faster_speed():
    words_normal = prompts.estimate_target_words(60.0, speed=1.0, sentence_gap_seconds=0.0)
    words_fast = prompts.estimate_target_words(60.0, speed=1.25, sentence_gap_seconds=0.0)
    assert words_fast > words_normal


def test_estimate_target_words_accounts_for_sentence_gap_overhead():
    # Sentence-gap pauses eat into the real-time budget without adding words, so asking
    # for the same target duration with gaps enabled should request fewer words.
    words_no_gap = prompts.estimate_target_words(75.0, speed=1.0, sentence_gap_seconds=0.0)
    words_with_gap = prompts.estimate_target_words(75.0, speed=1.0, sentence_gap_seconds=0.5)
    assert words_with_gap < words_no_gap


def test_estimate_target_words_never_below_minimum():
    words = prompts.estimate_target_words(1.0, speed=0.25, sentence_gap_seconds=2.0)
    assert words >= prompts.MIN_TARGET_WORDS


def test_build_segment_prompt_mentions_target_and_speed():
    segment = {"title": "Roman Concrete", "summary": "How it was made."}
    prompt = prompts.build_segment_prompt("Ancient Rome", segment, target_seconds=45.0, speed=0.8, sentence_gap_seconds=0.5)
    assert "45 seconds" in prompt
    assert "0.80x" in prompt
