import pytest

import prompts


@pytest.mark.parametrize("value", ["nonsense", "News", "current-events"])
def test_validate_domain_rejects_unknown(value):
    with pytest.raises(prompts.DomainError):
        prompts.validate_domain(value)


@pytest.mark.parametrize("value", ["history", "math", "discovery", "HISTORY", "Math"])
def test_validate_domain_accepts_known_values_case_insensitively(value):
    assert prompts.validate_domain(value) in prompts.DOMAINS


def test_validate_domain_defaults_when_falsy():
    assert prompts.validate_domain(None) == prompts.DEFAULT_DOMAIN
    assert prompts.validate_domain("") == prompts.DEFAULT_DOMAIN


def test_history_domain_prompts_are_unchanged_from_before_the_domain_feature():
    # Regression: introducing the domain registry must not alter the "history" domain's
    # actual rendered prompt text, since existing episodes/cached scripts assume it.
    outline = prompts.build_outline_prompt("Ancient Rome", 5, [], domain="history")
    assert 'Create an outline for a spoken educational history episode about "Ancient Rome"' in outline
    assert "narrative/chronological sequence" in outline
    assert "a specific historical event, person, invention, place, or discovery" in outline

    segment = prompts.build_segment_prompt(
        "Ancient Rome", {"title": "Roman Concrete", "summary": "How it was made."},
        target_seconds=75.0, speed=1.0, sentence_gap_seconds=0.0, domain="history",
    )
    assert "Write a narration segment about this subject for a spoken history program" in segment
    assert "Engaging storytelling style, but historically accurate." in segment
    assert "Distinguish established historical facts from disputed" in segment


def test_math_domain_avoids_symbolic_notation_and_talks_about_math():
    outline = prompts.build_outline_prompt("Prime Numbers", 4, [], domain="math")
    assert "spoken educational math episode" in outline
    assert "mathematical result, concept, proof idea" in outline

    segment = prompts.build_segment_prompt(
        "Prime Numbers", {"title": "Infinitude of primes", "summary": "Euclid's proof."}, domain="math",
    )
    assert "spoken math program" in segment
    assert any("symbolic notation" in r for r in prompts.DOMAINS["math"]["requirements"])


def test_discovery_domain_is_present_tense_not_history_or_news():
    outline_system = prompts.DOMAINS["discovery"]["outline_system"]
    segment_system = prompts.DOMAINS["discovery"]["segment_system"]
    assert "not a history program and not a news program" in outline_system
    assert "present tense" in segment_system
    assert "not a report on recent news events" in segment_system

    segment = prompts.build_segment_prompt(
        "Black Holes", {"title": "Event horizons", "summary": "Where light can't escape."}, domain="discovery",
    )
    assert "spoken discovery program" in segment


def test_all_domains_produce_syntactically_reasonable_prompts():
    for domain in prompts.DOMAINS:
        outline = prompts.build_outline_prompt("Some Topic", 3, [], domain=domain)
        assert "Some Topic" in outline
        assert '"title": "<overall episode title>"' in outline

        segment = prompts.build_segment_prompt(
            "Some Topic", {"title": "A Subject", "summary": "A summary."}, domain=domain,
        )
        assert "A Subject" in segment
        assert "Requirements:" in segment


def test_build_outline_prompt_avoid_list_unaffected_by_domain():
    for domain in prompts.DOMAINS:
        outline = prompts.build_outline_prompt("Topic", 3, ["Already Covered Subject"], domain=domain)
        assert "Already Covered Subject" in outline
        assert "Do not repeat them" in outline
