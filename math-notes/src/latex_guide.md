# LaTeX Guide

This site renders real LaTeX math via [KaTeX](https://katex.org/), rendered
in your browser -- not a plugin drawing tiny images. Anywhere in a post or
page, you can write:

- **Inline math**, wrapped in single dollar signs: `$x^2 + y^2 = r^2$`
  renders in the middle of a sentence like $x^2 + y^2 = r^2$.
- **Display math**, wrapped in double dollar signs on their own lines,
  centered on its own line:

```
$$
\int_0^\infty e^{-x^2}\,dx = \frac{\sqrt{\pi}}{2}
$$
```

renders as:

$$
\int_0^\infty e^{-x^2}\,dx = \frac{\sqrt{\pi}}{2}
$$

## Superscript (exponents)

Use `^` for a superscript. A single character doesn't need braces; anything
longer than one character does, or only the first character ends up raised:

```
$x^2$
$x^{10}$
$e^{-x^2}$
```

$x^2$ &nbsp;&nbsp; $x^{10}$ &nbsp;&nbsp; $e^{-x^2}$

Without the braces, `x^10` renders as $x^10$ -- only the `1` is raised, and
the `0` sits back on the normal line. This is the single most common LaTeX
typo, so when in doubt, use braces even for a single character.

## Subscript

Use `_` the same way, for subscripts:

```
$x_0$
$v_{0x}$
$a_{n+1}$
```

$x_0$ &nbsp;&nbsp; $v_{0x}$ &nbsp;&nbsp; $a_{n+1}$

## Combining both

Superscript and subscript can be combined on the same symbol, in either
order:

```
$x_i^2$
$v_{0x}^{2}$
```

$x_i^2$ &nbsp;&nbsp; $v_{0x}^{2}$

## Fractions

`\frac{numerator}{denominator}`:

```
$\frac{1}{2}$
$\frac{a+b}{c-d}$
$\frac{d}{dx}\left(\frac{1}{x}\right)$
```

$\frac{1}{2}$ &nbsp;&nbsp; $\frac{a+b}{c-d}$ &nbsp;&nbsp; $\frac{d}{dx}\left(\frac{1}{x}\right)$

Note `\left(` / `\right)` in that last one -- plain `(` `)` don't resize to
fit whatever's inside them, but `\left(`/`\right)` grow automatically to
wrap a tall fraction cleanly. Use them any time parentheses wrap something
taller than a single line of text.

## Square roots and other roots

`\sqrt{...}` for a square root, `\sqrt[n]{...}` for an nth root (the `[n]`
goes *before* the braces):

```
$\sqrt{2}$
$\sqrt{x^2 + y^2}$
$\sqrt[3]{8}$
$\sqrt[n]{x}$
```

$\sqrt{2}$ &nbsp;&nbsp; $\sqrt{x^2 + y^2}$ &nbsp;&nbsp; $\sqrt[3]{8}$ &nbsp;&nbsp; $\sqrt[n]{x}$

## Putting it together

A real example combining all four -- the quadratic formula:

```
$$
x = \frac{-b \pm \sqrt{b^2 - 4ac}}{2a}
$$
```

$$
x = \frac{-b \pm \sqrt{b^2 - 4ac}}{2a}
$$

## Greek letters, operators, and other symbols

| What you want | You write | Renders as |
|---|---|---|
| Greek letters | `\alpha`, `\theta`, `\pi`, `\Delta`, `\Sigma` | $\alpha$, $\theta$, $\pi$, $\Delta$, $\Sigma$ |
| Sum | `\sum_{i=1}^{n} i` | $\sum_{i=1}^{n} i$ |
| Product | `\prod_{i=1}^{n} i` | $\prod_{i=1}^{n} i$ |
| Integral | `\int_a^b f(x)\,dx` | $\int_a^b f(x)\,dx$ |
| Limit | `\lim_{x \to 0}` | $\lim_{x \to 0}$ |
| Derivative | `\frac{dy}{dx}`, `f'(x)` | $\frac{dy}{dx}$, $f'(x)$ |
| Times / dot | `a \times b`, `a \cdot b` | $a \times b$, $a \cdot b$ |
| Implies | `\implies` | $\implies$ |
| Not equal | `\neq` | $\neq$ |
| Approximately | `\approx` | $\approx$ |
| Less/greater or equal | `\leq`, `\geq` | $\leq$, $\geq$ |
| Infinity | `\infty` | $\infty$ |
| Vector | `\vec{v}` | $\vec{v}$ |
| Plus/minus | `\pm` | $\pm$ |
| Degree | `90^\circ` | $90^\circ$ |

Anything valid in KaTeX works here -- this table is just the handful that
come up most often in these notes, not a complete reference. The full
[KaTeX supported-functions list](https://katex.org/docs/supported.html) has
everything else (matrices, cases, accents, and more).

## The word-problem layout

Posts here state a problem, then hide the worked solution behind a
click, so you can attempt it first. That's two nested Markdown blocks, not
a special math feature:

```
!!! question "Problem"
    A ball is launched horizontally from a building that is 45 meters
    tall, with an initial horizontal velocity of 10 m/s.

??? success "Solution"
    Step-by-step work goes here, including math:

    $$
    t = \sqrt{\frac{2y_0}{g}}
    $$
```

- `!!!` is a regular, always-visible admonition box.
- `???` is the same thing but **collapsed by default** -- the reader clicks
  to expand it. Use `???` for the solution, `!!!` for the problem statement
  itself.
- The quoted text after the type (`"Problem"`, `"Solution"`) is the box's
  title; the type keyword (`question`, `success`) controls its color/icon.
  `question` (blue) and `success` (green) are used consistently across this
  site's posts, but `note`, `warning`, `danger`, and others also work.
- Content inside either block must be indented four spaces, including
  blank lines between paragraphs and any math blocks -- this is exactly the
  same indentation rule as a code block or a nested list item in Markdown.

See [Welcome](/blog/welcome/) or [Projectile motion: horizontal launch](/blog/projectile-motion-horizontal-launch/)
for two complete worked examples of this pattern together with LaTeX.

## Adding a graph

Write real matplotlib code in a fenced block tagged `matplotlib`, with a
required `name` (used for the image filename and the button's target) and
an optional `title` (the button's label, defaults to "Show graph"):

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

This doesn't run in your browser -- matplotlib is Python-only. `render_plots.py`
runs once, when you save the post (create or edit it), *before* the rest of the
post's Markdown is rendered: it finds every fenced block like this, executes
the code (`plt` is already imported and available -- don't `import
matplotlib.pyplot` yourself, and don't call `plt.savefig()` either, that part
happens automatically after your code runs), saves the resulting figure as a
PNG, and replaces the code block with a button. Nothing is visible until a
reader clicks it -- clicking opens the image in a popup; clicking the
&times;, the backdrop, or pressing Escape closes it.

Because this runs when you save the post, a mistake in the plotting code (a
typo, a name reused by two different graphs, code that never actually calls
a plotting function) fails the save with a clear error message pointing at
which block broke, rather than silently publishing a broken page.
