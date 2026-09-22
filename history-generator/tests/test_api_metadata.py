import api
import math_visual
import prompts


def test_metadata_domains_matches_prompts_registry():
    data = api.get_metadata()
    assert data["domains"] == sorted(prompts.DOMAINS)


def test_metadata_visual_styles_matches_math_visual_registry():
    data = api.get_metadata()
    assert data["visual_styles"] == sorted(math_visual.VALID_VISUAL_STYLES)


def test_metadata_bounds_match_the_validating_modules():
    data = api.get_metadata()
    assert data["bounds"]["pitch_semitones"]["min"] == api.pitch_mod.MIN_SEMITONES
    assert data["bounds"]["pitch_semitones"]["max"] == api.pitch_mod.MAX_SEMITONES
    assert data["bounds"]["segment_gap_seconds"]["max"] == api.video_mod.MAX_GAP_SECONDS
    assert data["bounds"]["sentence_gap_seconds"]["max"] == api.sentence_gap_mod.MAX_SENTENCE_GAP_SECONDS
    assert data["bounds"]["music_level_db"]["min"] == api.music_mod.MIN_LEVEL_DB


def test_metadata_defaults_are_present():
    data = api.get_metadata()
    for key in ("voice", "speed", "duration", "music_mood", "visual_style", "domain"):
        assert key in data["defaults"]
