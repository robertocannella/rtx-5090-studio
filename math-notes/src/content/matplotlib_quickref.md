Write real matplotlib code in a fenced block tagged `matplotlib`, with a required
`name` (used for the image filename and the button's target) and an optional `title`
(the button's label, defaults to "Show graph"). `name` only needs to be unique *within
this post* -- two different posts can each use `name="trajectory"` without conflicting,
since each post's graphs are stored under its own slug.

```matplotlib name="projectile-trajectory" title="Show trajectory"
import numpy as np

t = np.linspace(0, 3.03, 100)
x = 10 * t
y = 45 - 0.5 * 9.8 * t**2

fig, ax = plt.subplots()
ax.plot(x, y)
ax.set_xlabel("Horizontal distance (m)")
ax.set_ylabel("Height (m)")
ax.set_title("Trajectory of the ball")
ax.grid(True)
```

- `plt` is already imported -- don't `import matplotlib.pyplot` yourself.
- Don't call `plt.savefig()` -- that happens automatically after your code runs.
- This doesn't run in the reader's browser; it's Python-only, executed server-side.

## What runs code, and when

Switching a block between Edit and view (or just typing) **never** executes your code --
it only shows the image already saved from a previous save, or a placeholder saying it'll
render after you save. This is deliberate: an in-progress edit can't accidentally
overwrite a working graph or run half-finished code.

Two things actually execute your code:

- **Generate graph** -- the button that appears on a matplotlib block while you're
  editing it. Runs your code right now, into a scratch location the real post never
  reads from, so you can check it works before saving. A broken block shows its error
  right there instead of failing silently.
- **Save** -- executes every matplotlib block for real and writes the PNGs the post will
  actually serve. A mistake (a typo, a `name` reused within the same post, code that never
  calls a plotting function) is reported on the form and the post is not saved.

## Result on the live page

The code block is replaced by a button (labeled by `title`, or "Show graph"); nothing is
visible until a reader clicks it, which opens the image in a popup. The full syntax,
plus everything else about writing a post, is also documented on the public
[LaTeX Guide](/latex-guide/).
