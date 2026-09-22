# Derived from the original fixed guidance of "150-220 words / 60-90 seconds", which
# implicitly assumed speed 1.0. midpoint(150,220)/midpoint(60,90) = 185/75 words-per-second.
WORDS_PER_SECOND_AT_SPEED_1 = 185 / 75
AVG_WORDS_PER_SENTENCE = 18
MIN_TARGET_WORDS = 40


def estimate_target_words(target_seconds, speed, sentence_gap_seconds=0.0):
    """Words to ask Qwen for so the *synthesized* audio -- word count played back at the
    requested speed, plus any within-segment sentence-gap pauses -- lands near
    target_seconds. Ignoring speed here is exactly what produced a 90.8s segment against
    a 60s target at speed 0.85: the same word count takes longer to speak at a slower
    speed, so fewer words are needed to hit the same target duration.
    """
    speed = max(float(speed), 0.05)
    words_per_second = WORDS_PER_SECOND_AT_SPEED_1 * speed
    if sentence_gap_seconds <= 0:
        return max(MIN_TARGET_WORDS, round(target_seconds * words_per_second))
    # target_seconds == words/words_per_second + (words/AVG_WORDS_PER_SENTENCE - 1) * gap
    # solved for words:
    denom = (1.0 / words_per_second) + (sentence_gap_seconds / AVG_WORDS_PER_SENTENCE)
    words = (target_seconds + sentence_gap_seconds) / denom
    return max(MIN_TARGET_WORDS, round(words))


class DomainError(Exception):
    pass


# The content "genre" -- everything domain-specific in this pipeline lives here, as text.
# None of TTS, duration budgeting, pitch, gaps, music, ambient, or video assembly know or
# care which domain an episode is; they only ever see a topic string and audio settings.
# Adding a new domain means adding an entry here, nothing else.
DOMAINS = {
    "history": {
        "label": "history",
        "outline_system": (
            "You are an editor for an educational spoken-history program. "
            "You output only valid JSON matching the requested schema — no markdown, no commentary."
        ),
        "segment_system": (
            "You write narration scripts for a spoken educational history podcast segment. "
            "Output plain narration text only, meant to be read aloud — no headings, no markdown, "
            "no bullet points, no stage directions, no intro/outro filler."
        ),
        "sequence_guidance": "narrative/chronological sequence",
        "outline_subject_guidance": (
            "a specific historical event, person, invention, place, or discovery — specific enough "
            "for 60-90 seconds of narration, not a broad era"
        ),
        "requirements": [
            "Engaging storytelling style, but historically accurate.",
            "Explain unfamiliar terms rather than assuming the listener knows them.",
            "Mention dates when relevant.",
            "Explain why it mattered.",
            "Include one surprising or memorable detail.",
            "Distinguish established historical facts from disputed, legendary, or speculative "
            "claims — do not present legends as established fact and do not invent quotations.",
            "Avoid repetitive openers like \"Did you know\".",
            "Output narration only, as plain prose, nothing else.",
        ],
        "image_style": "cinematic, photorealistic historical illustration, painterly, accurate period detail",
    },
    "math": {
        "label": "math",
        "outline_system": (
            "You are an editor for an educational spoken-math program. "
            "You output only valid JSON matching the requested schema — no markdown, no commentary."
        ),
        "segment_system": (
            "You write narration scripts for a spoken educational math podcast segment. Output "
            "plain narration text only, meant to be read aloud — no headings, no markdown, no "
            "bullet points, no symbolic notation or equations (this is audio-only: spell numbers, "
            "variables, and formulas out in words), no stage directions, no intro/outro filler."
        ),
        "sequence_guidance": "logical sequence, building from simpler to more advanced ideas",
        "outline_subject_guidance": (
            "a specific mathematical result, concept, proof idea, pattern, or real-world "
            "application — specific enough to explain clearly in 60-90 seconds, not a whole "
            "branch of mathematics"
        ),
        "requirements": [
            "Engaging, intuitive explanation, but mathematically correct.",
            "Explain unfamiliar terms and notation in plain language rather than assuming the "
            "listener knows them.",
            "Walk through the key idea or intuition step by step, not just the final result.",
            "Explain why the result matters or where it's used.",
            "Include one surprising or memorable detail or example.",
            "Since this is audio-only, spell out numbers, symbols, and formulas in words rather "
            "than writing symbolic notation.",
            "Avoid repetitive openers like \"Did you know\".",
            "Output narration only, as plain prose, nothing else.",
        ],
        "image_style": "clean minimalist abstract geometric digital illustration, elegant, no equations or text",
    },
    "discovery": {
        "label": "discovery",
        "outline_system": (
            "You are an editor for an educational spoken-science program about how the world "
            "works right now -- not a history program and not a news program. "
            "You output only valid JSON matching the requested schema — no markdown, no commentary."
        ),
        "segment_system": (
            "You write narration scripts for a spoken educational science-explainer podcast "
            "segment, describing phenomena and how things work in the present tense -- not a "
            "historical account of how something was discovered, and not a report on recent news "
            "events. Output plain narration text only, meant to be read aloud — no headings, no "
            "markdown, no bullet points, no stage directions, no intro/outro filler."
        ),
        "sequence_guidance": "sensible thematic sequence",
        "outline_subject_guidance": (
            "a specific natural phenomenon, scientific concept, or how something works today — "
            "specific enough for 60-90 seconds of narration, not a broad field"
        ),
        "requirements": [
            "Engaging, curious explanatory style, but scientifically accurate and reflecting "
            "current mainstream scientific understanding.",
            "Explain unfamiliar terms rather than assuming the listener knows them.",
            "Describe the phenomenon in the present tense, as something ongoing or true now — "
            "not as a historical discovery narrative and not as breaking news.",
            "Explain why it matters or what it affects.",
            "Include one surprising or memorable detail.",
            "Distinguish well-established science from open questions or active research — do "
            "not present hypotheses as settled fact.",
            "Avoid repetitive openers like \"Did you know\".",
            "Output narration only, as plain prose, nothing else.",
        ],
        "image_style": "photorealistic scientific illustration, natural lighting, detailed",
    },
}

DEFAULT_DOMAIN = "history"

# Kept as module-level names for backward compatibility with anything referencing the
# original (history-only) constants directly.
OUTLINE_SYSTEM = DOMAINS[DEFAULT_DOMAIN]["outline_system"]
SEGMENT_SYSTEM = DOMAINS[DEFAULT_DOMAIN]["segment_system"]


def validate_domain(value):
    v = str(value or DEFAULT_DOMAIN).strip().lower()
    if v not in DOMAINS:
        raise DomainError(f"domain must be one of {sorted(DOMAINS)}, got {value!r}")
    return v


def build_outline_prompt(topic, count, existing_titles=None, domain=DEFAULT_DOMAIN):
    d = DOMAINS[domain]
    existing_titles = existing_titles or []
    avoid = ""
    if existing_titles:
        titles_list = "\n".join(f"- {t}" for t in existing_titles)
        avoid = (
            "\n\nThe following subjects are already covered in this episode. "
            "Do not repeat them or pick closely overlapping subjects:\n" + titles_list
        )
    return (
        f'Create an outline for a spoken educational {d["label"]} episode about "{topic}". '
        f"Propose exactly {count} distinct, non-repetitive segment subjects, ordered in a sensible "
        f"{d['sequence_guidance']}. Each segment should be {d['outline_subject_guidance']}.\n\n"
        f"Return a JSON object of the form:\n"
        f'{{"title": "<overall episode title>", "segments": [{{"number": <int>, "title": "<segment title>", '
        f'"summary": "<1-2 sentence summary to guide the narration writer>"}}]}}'
        + avoid
    )


def build_segment_prompt(
    topic, segment, target_seconds=75.0, speed=1.0, sentence_gap_seconds=0.0, domain=DEFAULT_DOMAIN,
):
    d = DOMAINS[domain]
    target_words = estimate_target_words(target_seconds, speed, sentence_gap_seconds)
    word_low = max(MIN_TARGET_WORDS, round(target_words * 0.85))
    word_high = round(target_words * 1.15)
    requirements = "\n".join(f"- {r}" for r in d["requirements"])
    return (
        f"Episode topic: {topic}\n"
        f"Segment subject: {segment['title']}\n"
        f"Guidance: {segment.get('summary', '')}\n\n"
        f"Write a narration segment about this subject for a spoken {d['label']} program, targeting "
        f"approximately {target_seconds:.0f} seconds of spoken audio at the narrator's actual "
        f"playback speed ({speed:.2f}x normal) -- aim for roughly {word_low}-{word_high} words. "
        "Requirements:\n"
        f"{requirements}"
    )


def build_image_prompts_tool(count):
    return {
        "type": "function",
        "function": {
            "name": "propose_image_prompts",
            "description": (
                "Propose short visual scene descriptions to illustrate a narration segment "
                "with AI-generated images."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "prompts": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": count,
                        "maxItems": count,
                        "description": (
                            f"Exactly {count} distinct visual scene descriptions, one per image, "
                            "covering different moments or aspects of the segment, in the same "
                            "order the narration unfolds."
                        ),
                    },
                },
                "required": ["prompts"],
            },
        },
    }


def build_image_prompts_system(domain=DEFAULT_DOMAIN):
    d = DOMAINS[domain]
    return (
        f"You are a visual art director for an educational {d['label']} video. Given a narration "
        "segment's script, propose short, vivid, concrete visual scene descriptions suitable for "
        "an AI image generator -- one distinct scene per requested image, in the same order the "
        "narration unfolds. Each description must be self-contained (no pronouns referring to "
        "other images) and concrete (real subjects, setting, composition, lighting) -- and must "
        "never ask for any text, writing, numbers, labels, diagrams, or charts to appear in the "
        f"image, since none of that renders reliably. Visual style: {d['image_style']}. "
        "You must call propose_image_prompts."
    )


def build_image_prompts_user(segment_title, segment_summary, script_text):
    return (
        f"Segment title: {segment_title}\n"
        f"Segment summary: {segment_summary}\n\n"
        f"Narration script for this segment:\n{script_text}\n\n"
        "Propose the requested number of visual scenes illustrating this narration, in order."
    )
