Write real matplotlib code in a fenced block tagged `matplotlib`, with a required
`name` (used for the image filename and the button's target) and an optional `title`
(the button's label, defaults to "Show graph"). `name` only needs to be unique *within
this post* -- two different posts can each use `name="trajectory"` without conflicting,
since each post's graphs are stored under its own slug.

````
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
````

- `plt` is already imported -- don't `import matplotlib.pyplot` yourself.
- Don't call `plt.savefig()` -- that happens automatically after your code runs.
- This doesn't run in the reader's browser; it's Python-only, executed server-side.
- A plain `print(...)` in your code shows up right next to the graph, in a small
  monospace block -- handy for a computed value the graph itself doesn't label, like
  `print(f"time to land: {t_land:.2f} s")`.

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

## Common physics plots

For a constant-acceleration problem, once you have $a$, $t$, and a starting velocity/
position, distance-vs-time and velocity-vs-time are usually the two worth graphing --
distance is the curve (parabolic, since it's $\tfrac12 a t^2$), velocity is the line
(linear, since it's $at$).

**Distance vs. time**

````
```matplotlib name="distance-vs-time" title="Show distance vs. time"
import numpy as np

a = 2.31  # m/s^2
t = np.linspace(0, 14.4, 100)
x = 0.5 * a * t**2

fig, ax = plt.subplots()
ax.plot(t, x)
ax.set_xlabel("Time (s)")
ax.set_ylabel("Distance (m)")
ax.set_title("Distance vs. time")
ax.grid(True)
```
````

**Velocity vs. time**

````
```matplotlib name="velocity-vs-time" title="Show velocity vs. time"
import numpy as np

a = 2.31  # m/s^2
t = np.linspace(0, 14.4, 100)
v = a * t

fig, ax = plt.subplots()
ax.plot(t, v)
ax.set_xlabel("Time (s)")
ax.set_ylabel("Velocity (m/s)")
ax.set_title("Velocity vs. time")
ax.grid(True)
```
````

A few things worth knowing:

- Each block is independent -- two blocks means two separate buttons/popups, not one
  popup with both charts. For one figure with both side by side, use a single block with
  `fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 4))` and plot onto `ax1`/`ax2`.
- `ax.set_xlabel`/`set_ylabel`/`set_title` and `ax.grid(True)` aren't required, but a
  reader clicking into a graph with no context is a lot less useful than one that's
  labeled -- get in the habit of adding them.
- `np.linspace(start, stop, num)` is almost always the right way to build the time axis
  for a smooth curve -- `num=100` (as above) is plenty for a curve this simple; don't
  reach for a Python loop to build the points by hand.

## Marking a specific point (e.g. $x_f$, $v_f$)

A curve alone doesn't call out the value that actually answers the problem -- mark the
point with `ax.scatter`, then label it with `ax.annotate`. Continuing the distance
example above, marking where it ends ($x_f$ at $t_f$):

````
```matplotlib name="distance-with-final-point" title="Show distance with final point"
import numpy as np

a = 2.31
t = np.linspace(0, 14.4, 100)
x = 0.5 * a * t**2

t_f = 14.4
x_f = 0.5 * a * t_f**2

fig, ax = plt.subplots()
ax.plot(t, x)
ax.scatter([t_f], [x_f], color="red", zorder=3)
ax.annotate(
    f"$x_f$ = {x_f:.1f} m",
    xy=(t_f, x_f),
    xytext=(-70, -15),
    textcoords="offset points",
)
ax.set_xlabel("Time (s)")
ax.set_ylabel("Distance (m)")
ax.set_title("Distance vs. time")
ax.grid(True)
```
````

- `ax.scatter([t_f], [x_f], ...)` -- lists, even for one point, since scatter plots a
  *collection* of points. `zorder=3` keeps the dot drawn on top of the line instead of
  possibly under it.
- `ax.annotate(text, xy=(x, y), xytext=(dx, dy), textcoords="offset points")` -- `xy` is
  the point being labeled; `xytext` shifts the *text* away from it by that many points, so
  the label doesn't sit directly on top of the dot. For a label with nothing to offset
  (right next to the point is fine), `ax.text(x, y, text)` is simpler.
- `$x_f$` in a matplotlib string renders through matplotlib's own "mathtext" -- built in,
  no LaTeX install needed, and understands the common cases (`_` for subscript, `^` for
  superscript, Greek letters like `\alpha`) -- but it's a different, smaller renderer than
  the KaTeX this site uses for the surrounding prose, so don't expect every LaTeX command
  to work inside a matplotlib label.
