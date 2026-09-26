"""Lets a post use a ```latex fenced block for display math instead of writing
$$ ... $$ by hand -- exactly what this expands to, before the post ever reaches
pymdownx.arithmatex, so KaTeX renders it identically either way. This only saves the
author from remembering/matching a pair of $$ delimiters themselves (and, since a fenced
block's ``` markers are a convention already used for matplotlib graphs, from having to
learn a second syntax for "this is a special block").
"""

import re

FENCE_RE = re.compile(r"```latex\n(?P<body>.*?)\n```", re.DOTALL)


def process(markdown_text):
    return FENCE_RE.sub(lambda m: f"$$\n{m.group('body')}\n$$", markdown_text)
