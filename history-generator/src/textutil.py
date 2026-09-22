import re


def sanitize_narration(text):
    """Strip markdown emphasis/headings and stray formatting from model output
    intended to be read aloud by TTS, not rendered."""
    text = text.strip()
    # Drop code fences / stray language hints some models add despite instructions.
    text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
    text = re.sub(r"\n?```$", "", text)
    # Markdown emphasis/heading/list markers.
    text = re.sub(r"[*_`#]+", "", text)
    text = re.sub(r"^\s*[-•]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
