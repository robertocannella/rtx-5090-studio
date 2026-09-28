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

## Plotting position and velocity together

Distance and velocity above are two separate blocks -- two separate buttons/popups. To
show them together against the same time axis in *one* graph, the usual approach is two
stacked panels sharing an x-axis, not one panel with both lines on it -- position (m) and
velocity (m/s) are different units on very different scales, so overlaying them directly
would make one line look flat next to the other.

````
```matplotlib name="distance-and-velocity" title="Show distance and velocity"
import numpy as np

a = 2.31
t = np.linspace(0, 14.4, 100)
x = 0.5 * a * t**2
v = a * t

fig, (ax1, ax2) = plt.subplots(2, 1, sharex=True, figsize=(6, 6))

ax1.plot(t, x)
ax1.set_ylabel("Distance (m)")
ax1.grid(True)

ax2.plot(t, v)
ax2.set_ylabel("Velocity (m/s)")
ax2.set_xlabel("Time (s)")
ax2.grid(True)

fig.suptitle("Distance and velocity vs. time")
```
````

- `fig, (ax1, ax2) = plt.subplots(2, 1, sharex=True, figsize=(6, 6))` -- `2, 1` means two
  rows, one column (stacked, not side by side -- that would be `1, 2`). `sharex=True`
  locks both panels' time axes to the same range, so a point at $t=10$ lines up
  vertically between the two.
- Each panel is its own independent `Axes` (`ax1`, `ax2`) -- its own `set_ylabel`/`grid`,
  since distance and velocity need different y-axis labels and ranges. Only `set_xlabel`
  on the *bottom* panel (`ax2`) -- both share one x-axis, so labeling it twice would be
  redundant.
- `fig.suptitle(...)` for one title over both panels, instead of `ax.set_title(...)` on
  just one of them -- this is a title for the whole figure, not either individual panel.

If the two quantities share the same units and a comparable scale (two different
distances, say, not distance and velocity), a single overlaid panel usually reads better
than two stacked ones -- just call `ax.plot` twice on the same `ax` and add a legend:

````
```matplotlib name="two-runners" title="Show two runners' positions"
import numpy as np

t = np.linspace(0, 10, 100)
x_a = 3 * t
x_b = 2 * t + 5

fig, ax = plt.subplots()
ax.plot(t, x_a, label="Runner A")
ax.plot(t, x_b, label="Runner B")
ax.set_xlabel("Time (s)")
ax.set_ylabel("Distance (m)")
ax.legend()
ax.grid(True)
```
````

`label="..."` on each `ax.plot` call plus one `ax.legend()` is all it takes -- no need to
track colors by hand, matplotlib assigns each line its own and the legend matches them
automatically.

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

## Labeling several points along a curve

Sometimes one endpoint isn't enough -- a few sample points along the curve, each labeled
with its own coordinates, shows how the value grows over time rather than just where it
ends up. Scatter all of them in one call, then label each one individually in a loop
(each point needs its *own* text, so there's no way around looping for the labels, even
though the dots themselves don't need one):

````
```matplotlib name="distance-with-sample-points" title="Distance with sample points"
import numpy as np

v_i = 10
a = 3
t_f = 2.81

t = np.linspace(0, t_f, 100)
x = v_i * t + 0.5 * a * t**2

t_samples = np.linspace(0, t_f, 3)
x_samples = v_i * t_samples + 0.5 * a * t_samples**2

fig, ax = plt.subplots()
ax.plot(t, x)
ax.scatter(t_samples, x_samples, color="red", zorder=3)
for t_i, x_i in zip(t_samples, x_samples):
    ax.text(t_i + 0.05, x_i, f"({t_i:.2f}, {x_i:.2f})", fontsize=9, verticalalignment="center")
ax.set_xlabel("Time (s)")
ax.set_ylabel("Distance (m)")
ax.set_title("Distance with sample points")
ax.grid(True)
```
````

- `np.linspace(0, t_f, 3)` for `t_samples` -- a separate, *coarser* linspace than the one
  used for the smooth curve (`t`, 100 points) -- pick however many points you want
  labeled; 3 gives the start, middle, and end.
- `ax.scatter(t_samples, x_samples, ...)` marks all of them in a single call -- plain
  arrays this time, not wrapped in an extra `[...]` like the single-point example above,
  since scatter already treats each array as the collection of points to plot.
- `for t_i, x_i in zip(t_samples, x_samples): ax.text(...)` -- `zip` pairs the two arrays
  up point-by-point, so each label gets its *own* point's coordinates; there's no way to
  do this with one `ax.text` call since every label's text is different. `ax.text` (not
  `ax.annotate`) since there's nothing to offset away from here -- just a small `+ 0.05`
  nudge on the x position so the label doesn't sit directly on top of its dot.
- `verticalalignment="center"` keeps each label vertically centered on its point instead
  of sitting noticeably above or below it.
