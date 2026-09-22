import math
import os
import subprocess

import pytest

import math_visual as mv


@pytest.mark.parametrize("value", ["", None, "invalid", "MATH_STYLE", "video"])
def test_validate_visual_style_rejects_invalid(value):
    if value == "":
        # empty string coerces to the default rather than erroring -- only a genuinely
        # unrecognized non-empty value is rejected.
        assert mv.validate_visual_style(value) == mv.DEFAULT_VISUAL_STYLE
        return
    if value is None:
        assert mv.validate_visual_style(value) == mv.DEFAULT_VISUAL_STYLE
        return
    with pytest.raises(mv.MathVisualError):
        mv.validate_visual_style(value)


@pytest.mark.parametrize("value", ["static", "math", "Math", "STATIC"])
def test_validate_visual_style_accepts_known_values_case_insensitively(value):
    assert mv.validate_visual_style(value) in mv.VALID_VISUAL_STYLES


def test_select_visual_is_deterministic_per_seed():
    a = mv.select_visual("ancient-rome")
    b = mv.select_visual("ancient-rome")
    assert a == b


def test_select_visual_family_is_one_of_the_known_families():
    visual = mv.select_visual("some-episode-slug")
    assert visual["family"] in mv.FAMILIES
    assert visual["seed"] == "some-episode-slug"


def test_select_visual_varies_across_many_seeds():
    families = {mv.select_visual(f"episode-{i}")["family"] for i in range(30)}
    # With 3 families and 30 distinct seeds, seeing only one family every time would
    # indicate the seed isn't actually influencing the choice.
    assert len(families) > 1


def test_select_visual_different_seeds_can_differ_within_same_family():
    # Pin two seeds known (empirically, via the fixed hash) to select the same family so
    # we can confirm their *parameters* differ too, not just the family roll.
    results = {mv.select_visual(f"seed-{i}")["family"]: mv.select_visual(f"seed-{i}") for i in range(50)}
    by_family = {}
    for i in range(50):
        v = mv.select_visual(f"seed-{i}")
        by_family.setdefault(v["family"], []).append(v["params"])
    for family, param_list in by_family.items():
        if len(param_list) > 1:
            assert len(set(str(p) for p in param_list)) > 1


# --- Seamless-loop phase math ------------------------------------------------------------
# These test the underlying trigonometric design directly (independent of ffmpeg/geq):
# every animated phase term is built as `cycles * T / loop_seconds` with an integer
# `cycles`, so evaluating the same formula at T=0 and T=loop_seconds must be identical --
# that identity is what guarantees the rendered clip loops without a visible jump.

def test_waves_curve_phase_matches_at_loop_boundary():
    loop = 20.0
    for freq in (2, 3, 4):
        for cycles in (-2, -1, 1, 2):
            for x_frac in (0.1, 0.5, 0.9):
                def y(t, freq=freq, cycles=cycles, x_frac=x_frac):
                    return 0.5 + 0.08 * math.sin(2 * math.pi * (freq * x_frac + cycles * t / loop))
                assert y(0) == pytest.approx(y(loop), abs=1e-9)


def test_fourier_curve_phase_matches_at_loop_boundary():
    loop = 20.0
    for wave_type in ("square", "sawtooth"):
        for harmonics in (4, 5, 6):
            for freq in (1, 2):
                for cycles in (-2, -1, 1, 2):
                    def y(t, wave_type=wave_type, harmonics=harmonics, freq=freq, cycles=cycles):
                        total = 0.0
                        for k in range(1, harmonics + 1):
                            if wave_type == "square":
                                n = 2 * k - 1
                                coef = 4.0 / (math.pi * n)
                            else:
                                n = k
                                coef = (2.0 / math.pi) * ((-1) ** (k + 1)) / n
                            total += coef * math.sin(2 * math.pi * n * (freq * 0.3 + cycles * t / loop))
                        return total
                    assert y(0) == pytest.approx(y(loop), abs=1e-9)


def test_trace_curve_phase_matches_at_loop_boundary():
    loop = 20.0
    for a, b in [(3, 2), (5, 4), (2, 1), (3, 1), (4, 3)]:
        for delta in (0.0, 1.2345, 5.0):
            def pos(t, a=a, b=b, delta=delta):
                x = math.sin(a * 2 * math.pi * t / loop + delta)
                y = math.sin(b * 2 * math.pi * t / loop)
                return x, y
            x0, y0 = pos(0)
            x1, y1 = pos(loop)
            assert x0 == pytest.approx(x1, abs=1e-9)
            assert y0 == pytest.approx(y1, abs=1e-9)


# --- Actual rendering (kept small/fast) --------------------------------------------------

def _ffprobe_duration(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


@pytest.mark.parametrize("family", mv.FAMILIES)
def test_render_loop_produces_valid_video_of_requested_duration(tmp_path, family):
    import random
    rng = random.Random(family)
    params = mv._PARAM_BUILDERS[family](rng)
    visual = {"family": family, "params": params, "seed": family}
    out_path = os.path.join(str(tmp_path), f"{family}.mp4")

    mv.render_loop(visual, resolution="160x90", fps=10, loop_seconds=2.0, out_path=out_path)

    assert os.path.exists(out_path)
    assert os.path.getsize(out_path) > 0
    assert _ffprobe_duration(out_path) == pytest.approx(2.0, abs=0.2)


def test_render_loop_rejects_unknown_family(tmp_path):
    visual = {"family": "not-a-real-family", "params": {}, "seed": "x"}
    with pytest.raises(mv.MathVisualError):
        mv.render_loop(visual, resolution="160x90", fps=10, loop_seconds=1.0, out_path=os.path.join(str(tmp_path), "x.mp4"))
