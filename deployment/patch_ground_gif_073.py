#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRANCH_WORKFLOW = ROOT / ".github/workflows/patch-ground-gif-073.yml"
SELF = Path(__file__).resolve()


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected exactly one replacement target, found {count}: {old[:80]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    ground = ROOT / "tools/climate_analyzer/epw_climate_analyzer/ground_temperature.py"
    app = ROOT / "tools/climate_analyzer/app.py"
    requirements = ROOT / "tools/climate_analyzer/requirements.txt"
    tests = ROOT / "tools/climate_analyzer/tests/test_daylight_ground_0_7_3.py"
    doc = ROOT / "tools/climate_analyzer/CLIMATE_CORE_0_7_3.md"

    replace_once(
        ground,
        "from dataclasses import dataclass\nimport calendar\nimport math\n",
        "from dataclasses import dataclass\nfrom io import BytesIO\nimport calendar\nimport math\n",
    )
    replace_once(
        ground,
        "import plotly.graph_objects as go\n",
        "import plotly.graph_objects as go\nfrom PIL import Image, ImageDraw, ImageFont\n",
    )

    gif_function = r'''

def animated_profile_gif_bytes(
    profile: pd.DataFrame,
    measured: pd.DataFrame | None = None,
    *,
    duration_ms: int = 700,
    width: int = 900,
    height: int = 650,
) -> bytes:
    """Render a fixed-axis, infinitely looping 12-month GIF.

    The raster export is a presentation layer only: it consumes the already
    calculated monthly profile and optional measured shallow-soil points. It
    performs no additional climate or ground-temperature calculation.
    """
    months = [month for month in MONTH_LABELS if month in profile.columns]
    if not months:
        raise ValueError("Ground-temperature GIF requires at least one monthly profile.")
    if int(duration_ms) < 100:
        raise ValueError("GIF frame duration must be at least 100 ms.")
    if int(width) < 400 or int(height) < 300:
        raise ValueError("GIF canvas is too small for labelled axes.")

    depth = profile.index.to_numpy(dtype=float)
    if len(depth) < 2 or not np.isfinite(depth).all():
        raise ValueError("GIF export requires a finite ground-depth profile.")
    calculated_values = profile[months].to_numpy(dtype=float)
    finite = calculated_values[np.isfinite(calculated_values)]
    if finite.size == 0:
        raise ValueError("GIF export requires finite calculated temperatures.")

    observed_values = np.array([], dtype=float)
    if measured is not None and not measured.empty and "temperature_c" in measured.columns:
        observed_values = pd.to_numeric(measured["temperature_c"], errors="coerce").dropna().to_numpy(dtype=float)
    all_t = np.concatenate([finite, observed_values]) if observed_values.size else finite
    t_min = float(np.min(all_t))
    t_max = float(np.max(all_t))
    pad = max(1.0, 0.08 * max(t_max - t_min, 1.0))
    x_min, x_max = t_min - pad, t_max + pad
    z_min, z_max = float(np.min(depth)), float(np.max(depth))
    if z_max <= z_min:
        raise ValueError("GIF export requires a non-zero depth range.")

    left, right, top, bottom = 105, 45, 70, 85
    plot_left, plot_right = left, int(width) - right
    plot_top, plot_bottom = top, int(height) - bottom
    font = ImageFont.load_default()

    def map_x(value: float) -> int:
        return int(round(plot_left + (float(value) - x_min) / (x_max - x_min) * (plot_right - plot_left)))

    def map_y(value: float) -> int:
        return int(round(plot_top + (float(value) - z_min) / (z_max - z_min) * (plot_bottom - plot_top)))

    background = (255, 255, 255)
    grid = (220, 224, 228)
    axis = (55, 60, 65)
    inactive = (220, 223, 226)
    active = (35, 95, 165)
    observed = (170, 55, 55)

    frames: list[Image.Image] = []
    x_ticks = np.linspace(x_min, x_max, 6)
    z_ticks = np.linspace(z_min, z_max, 6)
    for month_index, month in enumerate(months, start=1):
        image = Image.new("RGB", (int(width), int(height)), background)
        draw = ImageDraw.Draw(image)
        draw.text((left, 20), f"Ground-temperature profile — {month}", fill=axis, font=font)

        for tick in x_ticks:
            x = map_x(float(tick))
            draw.line((x, plot_top, x, plot_bottom), fill=grid, width=1)
            draw.text((x - 18, plot_bottom + 12), f"{tick:.1f}", fill=axis, font=font)
        for tick in z_ticks:
            y = map_y(float(tick))
            draw.line((plot_left, y, plot_right, y), fill=grid, width=1)
            draw.text((25, y - 6), f"{tick:.1f}", fill=axis, font=font)

        draw.line((plot_left, plot_top, plot_left, plot_bottom), fill=axis, width=2)
        draw.line((plot_left, plot_bottom, plot_right, plot_bottom), fill=axis, width=2)
        draw.text(((plot_left + plot_right) // 2 - 72, int(height) - 32), "Ground temperature [degC]", fill=axis, font=font)
        draw.text((8, 45), "Depth [m]", fill=axis, font=font)

        # Keep the annual context faintly visible while the active month moves.
        for background_month in months:
            vals = pd.to_numeric(profile[background_month], errors="coerce").to_numpy(dtype=float)
            pts = [(map_x(v), map_y(z)) for v, z in zip(vals, depth) if np.isfinite(v) and np.isfinite(z)]
            if len(pts) >= 2:
                draw.line(pts, fill=inactive, width=1)

        vals = pd.to_numeric(profile[month], errors="coerce").to_numpy(dtype=float)
        pts = [(map_x(v), map_y(z)) for v, z in zip(vals, depth) if np.isfinite(v) and np.isfinite(z)]
        if len(pts) >= 2:
            draw.line(pts, fill=active, width=4)

        if measured is not None and not measured.empty:
            points = measured[measured["month_index"] == month_index]
            for record in points.to_dict("records"):
                try:
                    tx = float(record["temperature_c"])
                    zz = float(record["depth_m"])
                except (KeyError, TypeError, ValueError):
                    continue
                if not (math.isfinite(tx) and math.isfinite(zz)):
                    continue
                x, y = map_x(tx), map_y(zz)
                radius = 5
                draw.ellipse((x - radius, y - radius, x + radius, y + radius), outline=observed, width=3)

        draw.line((plot_right - 210, 35, plot_right - 175, 35), fill=active, width=4)
        draw.text((plot_right - 165, 29), "Calculated", fill=axis, font=font)
        if measured is not None and not measured.empty:
            x0, y0 = plot_right - 85, 35
            draw.ellipse((x0 - 4, y0 - 4, x0 + 4, y0 + 4), outline=observed, width=2)
            draw.text((x0 + 10, 29), "Observed", fill=axis, font=font)
        frames.append(image)

    output = BytesIO()
    frames[0].save(
        output,
        format="GIF",
        save_all=True,
        append_images=frames[1:],
        duration=int(duration_ms),
        loop=0,
        disposal=2,
        optimize=False,
    )
    return output.getvalue()
'''
    replace_once(
        ground,
        "\ndef measured_vs_calculated_table(profile: pd.DataFrame, measured: pd.DataFrame) -> pd.DataFrame:\n",
        gif_function + "\n\ndef measured_vs_calculated_table(profile: pd.DataFrame, measured: pd.DataFrame) -> pd.DataFrame:\n",
    )

    replace_once(
        app,
        "        animated_profile_figure,\n        damping_depth_m,",
        "        animated_profile_figure,\n        animated_profile_gif_bytes,\n        damping_depth_m,",
    )
    replace_once(
        app,
        '        modes.extend(["Monthly profiles vs depth", "Animated monthly profile", "Temperature through year at selected depth"])',
        '        modes.extend(["Monthly profiles vs depth", "Animated monthly profile", "Looping GIF", "Temperature through year at selected depth"])',
    )
    replace_once(
        app,
        '    elif mode == "Animated monthly profile":\n        render_plot(animated_profile_figure(profile, measured if not measured.empty else None), "Interactive loop through January–December. The axes stay fixed while the calculated profile moves with seasonal phase lag and attenuation.")\n        st.caption("GIF export is a presentation/export layer and is intentionally deferred until the interactive animation is qualified.")\n    elif mode == "Temperature through year at selected depth":',
        '    elif mode == "Animated monthly profile":\n        render_plot(animated_profile_figure(profile, measured if not measured.empty else None), "Interactive loop through January–December. The axes stay fixed while the calculated profile moves with seasonal phase lag and attenuation.")\n    elif mode == "Looping GIF":\n        gif_speed = st.slider("Frame duration [ms]", 300, 1500, 700, 100, key="ground_gif_duration")\n        gif_bytes = animated_profile_gif_bytes(profile, measured if not measured.empty else None, duration_ms=int(gif_speed))\n        st.image(gif_bytes, caption="Looping January–December ground-temperature profile")\n        st.download_button(\n            "Download GIF",\n            data=gif_bytes,\n            file_name="ground_temperature_monthly_loop.gif",\n            mime="image/gif",\n            key="ground_temperature_gif_download",\n        )\n        st.caption("The GIF is a visualization of the already calculated monthly profile; it does not perform a separate calculation.")\n    elif mode == "Temperature through year at selected depth":',
    )

    req = requirements.read_text(encoding="utf-8")
    if "pillow==" not in req.lower():
        req = req.rstrip() + "\npillow==12.3.0\n"
        requirements.write_text(req, encoding="utf-8")

    replace_once(
        tests,
        "import unittest\n\nimport numpy as np",
        "import unittest\nfrom io import BytesIO\n\nimport numpy as np",
    )
    replace_once(
        tests,
        "import pandas as pd\n",
        "import pandas as pd\nfrom PIL import Image\n",
    )
    replace_once(
        tests,
        "from epw_climate_analyzer.ground_temperature import AnnualHarmonic, fit_annual_harmonic, monthly_ground_profile\n",
        "from epw_climate_analyzer.ground_temperature import AnnualHarmonic, animated_profile_gif_bytes, fit_annual_harmonic, monthly_ground_profile\n",
    )
    insertion = '''\n    def test_ground_profile_gif_is_infinite_twelve_frame_loop(self) -> None:\n        harmonic = AnnualHarmonic(mean_c=10.5, sin_c=-2.3, cos_c=-10.9, amplitude_c=11.14)\n        profile = monthly_ground_profile(harmonic, np.linspace(0.0, 15.0, 61), 2.0, 2000.0, 1000.0)\n        payload = animated_profile_gif_bytes(profile, duration_ms=500, width=640, height=480)\n        self.assertTrue(payload.startswith((b"GIF87a", b"GIF89a")))\n        image = Image.open(BytesIO(payload))\n        self.assertEqual(image.n_frames, 12)\n        self.assertEqual(int(image.info.get("loop", -1)), 0)\n\n'''
    replace_once(
        tests,
        "    def test_geosphere_ground_fields_are_canonical_and_pages_are_exposed(self) -> None:\n",
        insertion + "    def test_geosphere_ground_fields_are_canonical_and_pages_are_exposed(self) -> None:\n",
    )

    text = doc.read_text(encoding="utf-8")
    text = text.replace(
        "- interactive January → December looping profile animation with Play/Pause and month slider.\n\nGIF export is not part of this qualified increment yet; it remains a presentation/export layer after the interactive route.\n",
        "- interactive January → December looping profile animation with Play/Pause and month slider;\n- generated infinitely looping 12-frame GIF preview and download, with fixed axes and optional measured GeoSphere points.\n\nThe GIF is a pure presentation layer over the already calculated monthly profile; it does not change or repeat the scientific calculation.\n",
    )
    text = text.replace(
        "PR #67 remains Draft and targets `main`. It is not merged.",
        "PR #67 remains Draft and targets `main`. It is not merged. The GIF presentation layer is included after the D/E provider qualification and must pass the subsequent CI requalification before final review.",
    )
    doc.write_text(text, encoding="utf-8")

    # Self-clean after applying the patch so no patch infrastructure remains in the PR.
    if BRANCH_WORKFLOW.exists():
        BRANCH_WORKFLOW.unlink()
    if SELF.exists():
        SELF.unlink()


if __name__ == "__main__":
    main()
