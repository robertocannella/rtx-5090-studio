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
- Add `inline="true"` (after `title`, if there is one) to show the image directly in the
  post instead of behind a "Show graph" button -- see "Showing a graph inline" below.

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

## Showing a graph inline

Add `inline="true"` to show the image directly in the post -- no button, no click needed
to see it at all:

````
```matplotlib name="inline-example" title="Show inline example" inline="true"
import numpy as np

t = np.linspace(0, 10, 100)
x = 3 * t

fig, ax = plt.subplots()
ax.plot(t, x)
ax.set_xlabel("Time (s)")
ax.set_ylabel("Distance (m)")
ax.grid(True)
```
````

The image is still clickable -- clicking it opens the exact same enlarge-in-a-popup view
a non-inline graph's button gives, just without needing that first click to reveal the
graph in the first place. Whatever the code printed still shows right next to it, same as
the button version.

`inline="true"` has to come after `title` if there is one (`name="..." title="..."
inline="true"`) -- same fixed ordering `title` itself already has after `name`. Leave it
off (the default) for a graph you'd rather keep out of the way until a reader asks for
it, e.g. a solution's supporting work that would spoil the answer if shown immediately.

## Animated diagrams

Build a `matplotlib.animation.FuncAnimation` instead of a static plot and it's saved as
an animated GIF instead of a PNG -- useful for showing motion directly (two objects
racing toward each other, a projectile's path tracing out over time) rather than making a
reader infer it from a single still frame. `animation` is already available, the same
convenience `plt` already is -- don't `import matplotlib.animation` yourself:

````
```matplotlib name="catch-up-animation" title="Show animation" inline="true"
import numpy as np

t = np.linspace(0, 3, 40)
x_lead = 5 * t
x_chaser = 0.5 * 4 * t**2

fig, ax = plt.subplots()
lead_dot = ax.scatter(x_lead[0], 0, color="tab:blue", label="Lead skater")
chaser_dot = ax.scatter(x_chaser[0], 0, color="tab:orange", label="Chaser")
ax.set_xlim(0, max(x_lead.max(), x_chaser.max()))
ax.set_ylim(-1, 1)
ax.set_xlabel("Distance (m)")
ax.legend()


def update(frame):
    lead_dot.set_offsets([[x_lead[frame], 0]])
    chaser_dot.set_offsets([[x_chaser[frame], 0]])
    return (lead_dot, chaser_dot)


ani = animation.FuncAnimation(fig=fig, func=update, frames=40, interval=40)
```
````

A few things worth knowing:

- The function you pass as `func` (here, `update`) runs once per frame, moving whatever
  artists (points, lines) it updates -- build those artists once, before `FuncAnimation`,
  and only change their data inside the function, the same `scat.set_offsets(...)`/
  `line.set_xdata(...)`/`set_ydata(...)` pattern you'd use for any matplotlib animation.
- `frames` is how many times `update` gets called; `interval` is the delay between frames
  in milliseconds in the *live* sense FuncAnimation was originally designed for -- saving
  to a GIF translates it into each frame's actual display duration, so a smaller
  `interval` plays back faster.
- Don't call `ani.save(...)` or `plt.savefig(...)` yourself -- same rule as a static plot,
  saving happens automatically after your code runs, and it only needs the animation
  object to exist (assigned to any variable name) to be detected.
- The GIF loops forever by default -- there's no setting to change that currently.
- `inline="true"` works exactly the same way here as for a static plot -- the GIF just
  autoplays directly in the post, no click needed. Non-inline (the default) still works
  too: the GIF sits inside the same click-to-open popup a static graph's button gives.
- Switching a block between a static plot and an animation (or back) across edits cleans
  up the old asset automatically -- there's never a leftover PNG sitting around after a
  block becomes an animation, or vice versa.

## Sketching a diagram of the problem

Not every matplotlib block has to be a graph of data -- `ax` is just as good for
drawing a schematic of the scenario itself: a car and an obstacle on a road, the
positions where a ball is launched and lands, blocks connected by a rope, etc. The
technique is the same for every axis-based plot, just with `ax.axis("off")` instead of
labeled axes, and `ax.scatter`/`ax.annotate`/`ax.text` standing in for a plotted curve.

**A single scene** -- a car, an obstacle 50 m ahead, and a labeled distance between them:

````
```matplotlib name="car-and-obstacle" title="Show diagram" inline="true"
fig, ax = plt.subplots(figsize=(10, 2.5))

# The road
ax.plot([0, 50], [0, 0], linewidth=2)

# The car's starting position
ax.scatter(0, 0, s=100)
ax.text(0, 0.25, "Car sees obstacle", ha="center")

# The obstacle
ax.axvline(50)
ax.text(50, 0.25, "Obstacle", ha="center")

# A labeled double-headed arrow spanning the distance between them
ax.annotate(
    "",
    xy=(50, -0.35),
    xytext=(0, -0.35),
    arrowprops=dict(arrowstyle="<->"),
)
ax.text(25, -0.55, "50 m", ha="center")

ax.set_xlim(-3, 53)
ax.set_ylim(-1, 1)
ax.axis("off")
```
````

**Several key positions along the same line** -- useful for a multi-phase problem
(reacting, then braking, then stopped), where each position gets its own point and label,
and each phase between two positions gets its own labeled span underneath:

````
```matplotlib name="multi-phase-positions" title="Show diagram"
reaction_distance = 10
stopping_position = 43.33
obstacle_position = 50

fig, ax = plt.subplots(figsize=(11, 3))

# The road
ax.plot([0, obstacle_position], [0, 0], linewidth=2)

# Key positions
ax.scatter([0, reaction_distance, stopping_position], [0, 0, 0], s=100, zorder=3)
ax.text(0, 0.18, "Sees obstacle", ha="center")
ax.text(reaction_distance, 0.18, "Brakes applied", ha="center")
ax.text(stopping_position, 0.18, "Car stops", ha="center")

# Phase 1: reacting
ax.annotate(
    "", xy=(reaction_distance, -0.35), xytext=(0, -0.35),
    arrowprops=dict(arrowstyle="<->"),
)
ax.text(reaction_distance / 2, -0.48, "Phase 1", ha="center")

# Phase 2: braking
ax.annotate(
    "", xy=(stopping_position, -0.35), xytext=(reaction_distance, -0.35),
    arrowprops=dict(arrowstyle="<->"),
)
ax.text((reaction_distance + stopping_position) / 2, -0.48, "Phase 2", ha="center")

ax.set_xlim(-3, obstacle_position + 3)
ax.set_ylim(-0.7, 0.4)
ax.axis("off")
```
````

A few things worth knowing:

- `ax.axis("off")` hides the tick marks, axis lines, and labels a data plot needs but a
  schematic doesn't -- without it you'd get a plain x-axis running through the middle of
  the diagram.
- `ax.annotate("", xy=..., xytext=..., arrowprops=dict(arrowstyle="<->"))` draws a
  double-headed arrow from `xytext` to `xy` with no text of its own (the empty string) --
  pair it with a separate `ax.text(...)` centered underneath to label the distance or span
  it measures.
- A wide, short `figsize` (e.g. `(10, 2.5)` or `(11, 3)`) reads much better than the
  square default for a diagram that's fundamentally a single horizontal line -- set it
  explicitly rather than relying on `plt.subplots()`'s default shape.
- `zorder=3` on `ax.scatter(...)` keeps the points drawn on top of the road line instead
  of underneath it.
- `ax.set_xlim`/`set_ylim` need to be set by hand here (there's no data series for
  matplotlib to infer a sensible range from) -- pad a few units past your outermost point
  on each side so labels and arrowheads near the edges don't get clipped.
- These diagrams don't spoil anything the way a solution's supporting work might, so
  `inline="true"` (see above) is usually the right call for one placed alongside the
  problem statement -- readers benefit from seeing the scenario right away, before they've
  worked anything out.

## Vertical and horizontal lines in diagrams

Diagrams lean on straight reference lines all the time -- the moment one object passes
another, the ground, a ball's path as it falls, the height of a cliff. Matplotlib has two
pairs of functions for them, and the difference between the pairs is the single most
common source of lines that come out the wrong length:

| Function | Draws | `ymin`/`ymax` (or `xmin`/`xmax`) are... |
|---|---|---|
| `ax.axvline(x, ymin, ymax)` | one vertical line | **fractions of the axes' height**: 0 = bottom edge, 1 = top edge |
| `ax.vlines(x, ymin, ymax)` | one or more vertical lines | **data coordinates**: the actual y-values |
| `ax.axhline(y, xmin, xmax)` | one horizontal line | fractions of the axes' width: 0 = left edge, 1 = right edge |
| `ax.hlines(y, xmin, xmax)` | one or more horizontal lines | data coordinates: the actual x-values |

With no `ymin`/`ymax` at all, `ax.axvline(x)` spans the full height of the plot, whatever the
y-limits turn out to be. That's what makes it the right tool for a line that should run
edge to edge, like "the moment the car passes" or a ground line (`ax.axhline(0)`).

### Drawing a vertical line between two points

To join two specific points, say from $y = -0.5$ to $y = 0.5$ at $x = 7$, use `vlines`,
which takes the two y-values directly:

```python
ax.vlines(x=7, ymin=-0.5, ymax=0.5)
```

`axvline` *can* do it too, but only by converting each y-value into a fraction of the
axes' height first:

$$
\text{fraction} = \frac{y - y_\text{bottom}}{y_\text{top} - y_\text{bottom}}
$$

With `ax.set_ylim(-1, 1)`, $y = -0.5$ is $\frac{-0.5 - (-1)}{1 - (-1)} = 0.25$ and
$y = 0.5$ is $0.75$, so `ax.axvline(x=3, ymin=0.25, ymax=0.75)` draws the same line. Both
appear side by side here, each joining the same pair of y-values:

````
```matplotlib name="axvline-vs-vlines" title="Show graph"
fig, ax = plt.subplots(figsize=(10, 3))
ax.set_xlim(0, 10)
ax.set_ylim(-1, 1)

# Two points we want to join with a vertical line
ax.scatter([3, 3], [-0.5, 0.5], s=60, zorder=3, color="black")
ax.scatter([7, 7], [-0.5, 0.5], s=60, zorder=3, color="black")

# axvline: ymin/ymax are FRACTIONS of the axes height (0 = bottom, 1 = top),
# so 0.25..0.75 lands on y = -0.5..0.5 only because ylim is (-1, 1)
ax.axvline(x=3, ymin=0.25, ymax=0.75, color="tab:blue", linewidth=3)
ax.text(3, 0.75, "axvline(x=3, ymin=0.25, ymax=0.75)", ha="center")

# vlines: ymin/ymax are DATA coordinates -- the y-values of the two points
ax.vlines(x=7, ymin=-0.5, ymax=0.5, color="tab:orange", linewidth=3)
ax.text(7, 0.75, "vlines(x=7, ymin=-0.5, ymax=0.5)", ha="center")

ax.axhline(0, color="gray", linewidth=0.8)
ax.grid(True, alpha=0.3)
```
````

Things to watch for:

- **`axvline` fractions depend on the y-limits.** Change `ax.set_ylim(...)`, or leave it
  unset and let matplotlib pick limits from the data, and the same `ymin=0.25, ymax=0.75`
  lands somewhere else entirely. Passing y-values to `axvline` by mistake
  (`ymin=-0.5, ymax=0.5`) doesn't raise an error. It draws from below the bottom edge
  (clipped) up to the middle of the plot. Reach for `vlines` whenever you know the
  y-values.
- **Set the limits first** if you do use fractions, so you know what you're converting
  against.
- **Several lines at once:** `vlines` and `hlines` accept lists, e.g.
  `ax.vlines([2, 5, 8], 0, 1)` draws three lines of the same height, and
  `ax.vlines([2, 5], [0, 1], [3, 4])` gives each line its own start and end.
- **Keyword spelling differs slightly:** `axvline` takes `color=` and `linestyle=`, while
  `vlines` takes `colors=` and `linestyles=` (plural, since it can draw many lines).
- **`ax.plot([x, x], [y1, y2])`** is a third way to draw the same segment in data
  coordinates. It's handy when you also want markers on the ends (`marker="o"`).

### A vertical diagram: falling from a height

The same tools work for a vertical scene, such as a ball dropped from the top of a 45 m
building. `vlines` draws the dashed path of the fall between the release point and the
landing point, `axhline` draws the ground across the full width, and a vertical
`ax.annotate(..., arrowstyle="<->")` with a rotated label marks the height:

````
```matplotlib name="falling-from-a-height" title="Show diagram" inline="true"
building_height = 45
ball_x = 3

fig, ax = plt.subplots(figsize=(6, 5))

# Ground and building
ax.axhline(0, color="black", linewidth=2)
ax.add_patch(plt.Rectangle((0, 0), 2, building_height, color="lightgray"))

# Ball at the top, and where it lands
ax.scatter([ball_x, ball_x], [building_height, 0], s=80, zorder=3)
ax.text(ball_x + 0.4, building_height, "Ball released", va="center")
ax.text(ball_x + 0.4, 1.5, "Lands", va="center")

# Dashed path of the fall, drawn between the two points in data coordinates
ax.vlines(ball_x, 0, building_height, colors="gray", linestyles="--")

# Labeled height: a vertical double-headed arrow beside the building
ax.annotate("", xy=(-0.6, building_height), xytext=(-0.6, 0),
            arrowprops=dict(arrowstyle="<->"))
ax.text(-0.9, building_height / 2, r"$h = 45\,\mathrm{m}$", rotation=90, ha="right", va="center")

ax.set_xlim(-2.5, 6)
ax.set_ylim(-3, building_height + 5)
ax.axis("off")
```
````

- `rotation=90` turns the height label to run alongside the vertical arrow, and
  `ha="right", va="center"` anchors it just left of the arrow, halfway up.
- `plt.Rectangle((x, y), width, height)` added with `ax.add_patch(...)` is a quick way to
  draw a building, a block, a ramp's base, and so on. `(x, y)` is its bottom-left corner,
  in data coordinates.
- The figure is taller than it is wide (`figsize=(6, 5)`) because the scene is vertical,
  the opposite of the wide, short `figsize` used for horizontal road diagrams above.

## LaTeX in labels and text

Any string matplotlib draws -- `ax.text`, `ax.set_xlabel`/`set_ylabel`, `ax.set_title`, a
`label=` in a legend -- can contain math between `$...$`, rendered by matplotlib's own
*mathtext* engine (no LaTeX install needed). Everything outside the dollar signs is plain
text, so a label can mix the two:

```python
ax.text(30, 0.35, r'$v_{i,\text{cop}}$ = 0 m/s', ha="center")
ax.text(31, 0.09, r'$a_\text{cop}$ = 8 m/s$^2$', ha="center")
```

- **Always use a raw string (`r'...'`).** Without the `r`, Python reads the backslashes
  itself before matplotlib ever sees them -- `'\text'` becomes a *tab* followed by `ext`,
  and `'\frac'` a form feed followed by `rac`. The raw string passes `\text`, `\frac`, etc.
  through untouched.
- **Subscripts and superscripts** work like LaTeX: `v_f`, `t^2`. Anything longer than one
  character needs braces -- `v_{i,\text{cop}}`, not `v_i,cop` (which would subscript only the
  `i`).
- **`\text{...}` keeps words upright.** Math mode italicizes every letter as if it were a
  variable, so `a_{cop}` reads as *c·o·p*; `a_\text{cop}` (or `a_{\mathrm{cop}}`) shows the
  label as a word. Same for units -- `$\mathrm{m/s^2}$`.
- **Units: inside or outside the math.** `= 8 m/s$^2$` keeps the units as plain text with
  only the exponent in math mode; `$= 8\,\mathrm{m/s^2}$` puts the whole thing in math mode.
  Either is fine -- just be consistent within a diagram.
- **Spaces are ignored inside `$...$`**, as in LaTeX. Use `\,` (thin space) or `\ ` (normal
  space) when you need one, e.g. `$8\,\mathrm{m/s}$`.
- **Inserting computed values -- double the braces.** In an f-string, `{...}` means "insert a
  Python value", so LaTeX's own braces have to be written `{{...}}`. Combine `r` and `f` as
  `rf'...'`:

    ```python
    v_f = 22.22
    ax.text(40, 0.6, rf'$v_{{f,\text{{cop}}}}$ = {v_f:.2f} m/s', ha="center")
    ```

- **Mathtext is a subset of LaTeX.** `\frac`, `\sqrt`, `\Delta`, `\theta`, `\vec{v}`, `\cdot`,
  Greek letters, and sub/superscripts all work; multi-line environments like
  `\begin{aligned}` and packages like `\cancel` don't (the graph fails to render with a
  `ValueError`). Keep those for the post's own `$$...$$` blocks.

A diagram using all of the above:

````
```matplotlib name="latex-labels" title="Show diagram" inline="true"
v_car = 22.22
a_cop = 8

fig, ax = plt.subplots(figsize=(10, 2.5))
ax.plot([-10, 55], [0, 0], linewidth=2)

ax.annotate("", xy=(50, 0.75), xytext=(0, 0.75), arrowprops=dict(arrowstyle="->"))
ax.scatter(0, 0.75, s=60)
ax.text(5, 0.9, rf'$v_{{i,\text{{car}}}} = {v_car:.2f}\,\mathrm{{m/s}}$', ha="center")

ax.annotate("", xy=(50, 0.25), xytext=(25, 0.25), arrowprops=dict(arrowstyle="->"))
ax.scatter(25, 0.25, s=60)
ax.text(30, 0.35, r'$v_{i,\text{cop}}$ = 0 m/s', ha="center")
ax.text(31, 0.09, rf'$a_\text{{cop}}$ = {a_cop} m/s$^2$', ha="center")

ax.text(12, -0.4, r'$\Delta x = v_i t + \frac{1}{2} a t^2$', ha="center")

ax.set_xlim(-10, 55)
ax.set_ylim(-1, 1.1)
ax.axis("off")
```
````

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

Different units (displacement and velocity, say) *can* still share one panel this way --
it's a deliberate simplification, not dimensionally rigorous, and only reads well when
the two happen to land in a comparable numeric range (as in free fall, below). Combine it
with labeling sample points (see "Labeling several points along a curve" below) and each
series gets its own labeled points too -- just loop over each series' own samples
separately:

````
```matplotlib name="freefall-displacement-and-velocity" title="Show displacement and velocity"
import numpy as np

g = 9.8
t_f = 3.19
t = np.linspace(0, t_f, 100)
y = -0.5 * g * t**2
v = -g * t

t_samples = np.linspace(0, t_f, 3)
y_samples = -0.5 * g * t_samples**2
v_samples = -g * t_samples

fig, ax = plt.subplots(figsize=(8, 6))

ax.plot(t, y, label="Displacement")
ax.scatter(t_samples, y_samples)

ax.plot(t, v, label="Velocity")
ax.scatter(t_samples, v_samples)

for time, position in zip(t_samples, y_samples):
    ax.annotate(
        f"({time:.1f}, {position:.1f})",
        (time, position),
        xytext=(5, 5),
        textcoords="offset points",
    )

for time, velocity in zip(t_samples, v_samples):
    ax.annotate(
        f"({time:.1f}, {velocity:.1f})",
        (time, velocity),
        xytext=(5, -15),
        textcoords="offset points",
    )

ax.set_xlabel("Time (s)")
ax.set_ylabel("Displacement (m) / Velocity (m/s)")
ax.set_title("Free fall: displacement and velocity vs. time")

ax.axhline(0, color="gray", linewidth=0.8)
ax.grid(True)
ax.legend()
```
````

- Two separate `for` loops, one per series -- `y_samples` and `v_samples` each need their
  own labels at their own points, same reasoning as looping once per series in "Labeling
  several points" below, just done twice here.
- `xytext=(5, 5)` for displacement's labels and `xytext=(5, -15)` for velocity's -- offset
  in *different* directions so the two series' labels don't land on top of each other
  where the curves happen to cross or run close together.
- `ax.axhline(0, color="gray", linewidth=0.8)` draws a thin horizontal reference line at
  $y=0$ -- useful here since both series (falling below the start point, speeding up in
  the negative direction) cross or hug zero, giving the reader a baseline to read values
  against. Set explicitly to a neutral gray, not left to the default color cycle, so it
  reads as a reference line rather than a third data series.
- One shared `ax.set_ylabel("Displacement (m) / Velocity (m/s)")` naming both units --
  there's no way to give two truly independent, correctly-labeled y-axes without either
  stacked panels (above) or a twin axis (`ax.twinx()`, not covered in this quick
  reference, for a single panel with two independently-scaled y-axes).

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
