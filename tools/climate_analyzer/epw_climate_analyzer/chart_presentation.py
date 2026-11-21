"""Global presentation settings for every Plotly chart in Climate Analyzer.

Scientific chart builders own data, traces and scientific semantics. This module
owns only presentation: chart canvas, font sizing and browser image-export
settings. The Streamlit ``plotly_chart`` entrypoint is wrapped once so existing
and future charts inherit the same presentation contract without page-specific
patches.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Mapping, MutableMapping


CANVAS_AUTO = "Auto"
CANVAS_WIDE = "16:9 — Wide"
CANVAS_PRESENTATION = "4:3 — Presentation"
CANVAS_SQUARE = "1:1 — Square"
CANVAS_PORTRAIT = "3:4 — Portrait"
CANVAS_CUSTOM = "Custom"

CANVAS_OPTIONS = (
    CANVAS_AUTO,
    CANVAS_WIDE,
    CANVAS_PRESENTATION,
    CANVAS_SQUARE,
    CANVAS_PORTRAIT,
    CANVAS_CUSTOM,
)

# Dimensions define the deterministic presentation/export canvas. The display
# width control scales these dimensions; changing the browser width no longer
# needs to be used as a chart-composition tool.
CANVAS_DIMENSIONS: dict[str, tuple[int, int]] = {
    CANVAS_WIDE: (1280, 720),
    CANVAS_PRESENTATION: (1200, 900),
    CANVAS_SQUARE: (900, 900),
    CANVAS_PORTRAIT: (900, 1200),
}

BACKGROUND_WHITE = "White"
BACKGROUND_TRANSPARENT = "Transparent"
BACKGROUND_OPTIONS = (BACKGROUND_WHITE, BACKGROUND_TRANSPARENT)
DEFAULT_BACKGROUND = BACKGROUND_WHITE
TRANSPARENT_COLOR = "rgba(0,0,0,0)"

DEFAULT_CANVAS = CANVAS_AUTO
DEFAULT_WIDTH_PERCENT = 100
DEFAULT_FONT_SIZE = 18
DEFAULT_EXPORT_SCALE = 2
DEFAULT_CUSTOM_WIDTH = 1200
DEFAULT_CUSTOM_HEIGHT = 800

KEY_CANVAS = "chart_presentation_canvas"
KEY_WIDTH = "chart_presentation_width_percent"
KEY_FONT = "chart_presentation_font_size"
KEY_BACKGROUND = "chart_presentation_background"
KEY_EXPORT_SCALE = "chart_presentation_export_scale"
KEY_CUSTOM_WIDTH = "chart_presentation_custom_width"
KEY_CUSTOM_HEIGHT = "chart_presentation_custom_height"
EXTRA_DEFAULTS = {"show_title": True, "show_legend": True, "show_grid": True,
                  "line_scale": 1.0, "export_format": "PNG", "north_rotation": 0,
                  "axis_title": "", "axis_min": 0.0, "axis_max": 100.0}

def _key(name):
    return "chart_presentation_" + name


@dataclass(frozen=True)
class ChartPresentationSettings:
    canvas: str = DEFAULT_CANVAS
    width_percent: int = DEFAULT_WIDTH_PERCENT
    font_size: int = DEFAULT_FONT_SIZE
    export_scale: int = DEFAULT_EXPORT_SCALE
    custom_width: int = DEFAULT_CUSTOM_WIDTH
    custom_height: int = DEFAULT_CUSTOM_HEIGHT
    background: str = DEFAULT_BACKGROUND
    show_title: bool = True
    show_legend: bool = True
    show_grid: bool = True
    line_scale: float = 1.0
    export_format: str = "PNG"
    north_rotation: int = 0
    axis_title: str = ""
    axis_min: float = 0.0
    axis_max: float = 100.0

    @property
    def transparent(self) -> bool:
        return self.background == BACKGROUND_TRANSPARENT

    @property
    def is_auto(self) -> bool:
        return self.canvas == CANVAS_AUTO

    def base_dimensions(self) -> tuple[int, int] | None:
        if self.canvas == CANVAS_AUTO:
            return None
        if self.canvas == CANVAS_CUSTOM:
            return max(320, int(self.custom_width)), max(240, int(self.custom_height))
        return CANVAS_DIMENSIONS[self.canvas]

    def display_dimensions(self) -> tuple[int, int] | None:
        base = self.base_dimensions()
        if base is None:
            return None
        factor = max(0.5, min(1.0, float(self.width_percent) / 100.0))
        return max(320, round(base[0] * factor)), max(240, round(base[1] * factor))

    def export_dimensions(self) -> tuple[int, int] | None:
        """Return the unscaled target canvas used by Plotly image export."""
        return self.base_dimensions()


def settings_from_state(state: Mapping[str, Any]) -> ChartPresentationSettings:
    canvas = str(state.get(KEY_CANVAS, DEFAULT_CANVAS))
    if canvas not in CANVAS_OPTIONS:
        canvas = DEFAULT_CANVAS
    background = state.get(KEY_BACKGROUND, DEFAULT_BACKGROUND)
    if background not in BACKGROUND_OPTIONS:
        background = DEFAULT_BACKGROUND
    return ChartPresentationSettings(
        canvas=canvas,
        background=background,
        width_percent=int(state.get(KEY_WIDTH, DEFAULT_WIDTH_PERCENT)),
        font_size=int(state.get(KEY_FONT, DEFAULT_FONT_SIZE)),
        export_scale=int(state.get(KEY_EXPORT_SCALE, DEFAULT_EXPORT_SCALE)),
        custom_width=int(state.get(KEY_CUSTOM_WIDTH, DEFAULT_CUSTOM_WIDTH)),
        custom_height=int(state.get(KEY_CUSTOM_HEIGHT, DEFAULT_CUSTOM_HEIGHT)),
        **{name: state.get(_key(name), default) for name, default in EXTRA_DEFAULTS.items()},
    )


def reset_state(state: MutableMapping[str, Any]) -> None:
    state[KEY_CANVAS] = DEFAULT_CANVAS
    state[KEY_WIDTH] = DEFAULT_WIDTH_PERCENT
    state[KEY_FONT] = DEFAULT_FONT_SIZE
    state[KEY_BACKGROUND] = DEFAULT_BACKGROUND
    state[KEY_EXPORT_SCALE] = DEFAULT_EXPORT_SCALE
    state[KEY_CUSTOM_WIDTH] = DEFAULT_CUSTOM_WIDTH
    state[KEY_CUSTOM_HEIGHT] = DEFAULT_CUSTOM_HEIGHT
    for name, default in EXTRA_DEFAULTS.items():
        state[_key(name)] = default
    state[_key("underlay_enabled")] = False


def ensure_default_state(state: MutableMapping[str, Any]) -> None:
    """Seed widget state once so controls never fight explicit widget defaults."""
    state.setdefault(KEY_CANVAS, DEFAULT_CANVAS)
    state.setdefault(KEY_WIDTH, DEFAULT_WIDTH_PERCENT)
    state.setdefault(KEY_FONT, DEFAULT_FONT_SIZE)
    state.setdefault(KEY_BACKGROUND, DEFAULT_BACKGROUND)
    state.setdefault(KEY_EXPORT_SCALE, DEFAULT_EXPORT_SCALE)
    state.setdefault(KEY_CUSTOM_WIDTH, DEFAULT_CUSTOM_WIDTH)
    state.setdefault(KEY_CUSTOM_HEIGHT, DEFAULT_CUSTOM_HEIGHT)
    for name, default in EXTRA_DEFAULTS.items():
        state.setdefault(_key(name), default)


def _set_font_size(font: Any, size: int) -> None:
    if font is None:
        return
    try:
        font.size = size
    except Exception:
        pass


def _set_axis_font(axis: Any, size: int) -> None:
    if axis is None:
        return
    _set_font_size(getattr(axis, "tickfont", None), size)
    title = getattr(axis, "title", None)
    _set_font_size(getattr(title, "font", None), size)


def _set_colorbar_font(colorbar: Any, size: int) -> None:
    if colorbar is None:
        return
    _set_font_size(getattr(colorbar, "tickfont", None), size)
    title = getattr(colorbar, "title", None)
    _set_font_size(getattr(title, "font", None), size)


def _space_bottom_legends(fig: Any, settings: ChartPresentationSettings, size: int) -> None:
    """Separate below-plot horizontal legends from scientific axis labels.

    Explicitly anchored in-plot/side legends are left alone. Moving a legend
    from negative paper coordinates to the bottom of its container decouples
    its position from changes in the plot-area height. Reserve rows in pixels
    for the active font and a conservative responsive-width estimate.
    """
    layout = fig.layout
    if layout.showlegend is False:
        return
    props = getattr(layout, "_props", {}) or {}
    bottom = []
    for key in props:
        if not str(key).startswith("legend"):
            continue
        legend = getattr(layout, key, None)
        if legend is None or legend.orientation != "h" or getattr(legend, "visible", None) is False:
            continue
        y = legend.y
        is_bottom = (legend.yref == "container" and y is not None and y <= 0.10
                     or legend.yref != "container" and y is not None
                     and (y < 0 or (y == 0 and legend.yanchor == "top")))
        if is_bottom:
            bottom.append((key, legend))
    # Multiple independently positioned bottom legends are intentional;
    # avoid collapsing their distinct positions into one.
    if len(bottom) != 1:
        return
    key, legend = bottom[0]
    traces = [t for t in fig.data
              if getattr(t, "showlegend", None) is not False
              and getattr(t, "visible", None) is not False
              and (getattr(t, "legend", None) or "legend") == key]
    if not traces:
        return

    tick_lines = 1
    titled = False
    for name in props:
        if not str(name).startswith("xaxis"):
            continue
        axis = getattr(layout, name, None)
        if axis is None or axis.visible is False or axis.side == "top":
            continue
        axis.automargin = True
        if axis.title.text:
            axis.title.standoff = max(int(axis.title.standoff or 0), 14, size)
            titled = True
        if axis.ticktext is not None:
            tick_lines = max(tick_lines, max((str(t).count("<br>") + 1 for t in axis.ticktext), default=1))
    dimensions = settings.display_dimensions()
    width = dimensions[0] if dimensions else int(layout.width or 850)
    height = dimensions[1] if dimensions else int(layout.height or 450)
    margin = layout.margin
    usable_width = max(160, width - int(margin.l or 65) - int(margin.r or 35))
    title = legend.title.text or ""
    widths = [min(usable_width, 42 + math.ceil(len(str(t.name or "")) * size * 0.60))
              for t in traces]
    if title:
        widths.insert(0, min(usable_width, 25 + math.ceil(len(title) * size * 0.60)))
    rows, occupied = 1, 0
    for item in widths:
        if occupied and occupied + item > usable_width:
            rows += 1
            occupied = 0
        occupied += item
    axis_room = tick_lines * (size + 6) + (2 * size + 14 if titled else 8)
    legend_room = rows * (size + 12) + 18
    # Very dense legends must not consume the entire fixed canvas. Plotly's
    # legend overflow handling remains available for those cases.
    reserve = min(axis_room + legend_room, max(axis_room + size + 12, int(height * 0.46)))
    margin.b = max(int(margin.b or 0), int(reserve))
    legend.yref = "container"
    legend.y = 0.01
    legend.yanchor = "bottom"


def _apply_background(layout: Any, color: str, traces=()) -> None:
    """Change only canvas and subplot backgrounds, not analytical fills.

    Discover both explicit layout subplots and implicit trace references, so
    bare polar/3D figures and multiple subplot figures inherit the same setting.
    """
    layout.paper_bgcolor = color
    layout.plot_bgcolor = color
    names = set(getattr(layout, "_props", {}) or {})
    names.add("legend")
    for trace in traces:
        props = getattr(trace, "_props", {}) or {}
        kind = getattr(trace, "type", "")
        if kind in {"scatterpolar", "scatterpolargl", "barpolar"}:
            names.add(props.get("subplot") or "polar")
        elif kind in {"scatter3d", "mesh3d", "surface", "cone", "streamtube",
                      "volume", "isosurface"}:
            names.add(props.get("scene") or "scene")
        elif kind in {"scatterternary"}:
            names.add(props.get("subplot") or "ternary")
        if props.get("legend"):
            names.add(props["legend"])
        # Only modify existing colourbars; no new scales on ordinary traces.
        if isinstance(props.get("marker"), Mapping) and "colorbar" in props["marker"]:
            trace.marker.colorbar.bgcolor = color
        if "colorbar" in props:
            trace.colorbar.bgcolor = color
    for name in sorted(names):
        item = getattr(layout, name, None)
        if item is None:
            continue
        if name.startswith(("polar", "ternary", "scene", "legend", "geo")):
            if hasattr(item, "bgcolor"):
                item.bgcolor = color
            if name.startswith("scene"):
                for axis_name in ("xaxis", "yaxis", "zaxis"):
                    getattr(item, axis_name).backgroundcolor = color
        elif name.startswith("coloraxis"):
            item.colorbar.bgcolor = color


def _apply_extra_presentation(fig: Any, settings: ChartPresentationSettings) -> None:
    """Opt-in styling; scientific axes, geometry and data are not transformed."""
    layout = fig.layout
    if not settings.show_title:
        layout.title.text = ""
    if not settings.show_legend:
        layout.showlegend = False
    names = set(getattr(layout, "_props", {}) or {})
    names.update(("xaxis", "yaxis"))
    meta = layout.meta if isinstance(layout.meta, dict) else {}
    target = "" if meta.get("fixed_physical_axis_relationship") else settings.axis_title.strip()
    bounds_valid = (math.isfinite(settings.axis_min) and math.isfinite(settings.axis_max)
                    and settings.axis_min < settings.axis_max)
    for name in sorted(names):
        item = getattr(layout, name, None)
        if item is None:
            continue
        if name.startswith(("xaxis", "yaxis")):
            if not settings.show_grid:
                item.showgrid = False
            # Only an explicitly matching numeric axis is eligible. Exclude
            # date, categorical, log and aspect-constrained physical axes.
            if (target and bounds_valid and item.title.text == target
                and item.type in (None, "linear") and not item.scaleanchor
                and not item.matches and item.autorange != "reversed"
                and not any(getattr(getattr(layout,n,None),"scaleanchor",None)
                            in (name.replace("axis",""),) for n in names
                            if n.startswith(("xaxis","yaxis")))):
                # Implicit axis type can be categorical or date. Inspect the
                # actual coordinates routed to this axis before setting range.
                coord = name[0]
                axisref = name.replace("axis", "")
                traces = [tr for tr in fig.data if
                          (getattr(tr, coord+"axis",None) or coord) == axisref
                          and getattr(tr,coord,None) is not None]
                samples = [v for tr in traces for v in list(getattr(tr,coord))[:8] if v is not None]
                from numbers import Real
                if samples and all(isinstance(v,Real) for v in samples):
                    item.range = [settings.axis_min, settings.axis_max]
                    item.autorange = False
        elif name.startswith("polar"):
            if not settings.show_grid:
                item.angularaxis.showgrid = False
                item.radialaxis.showgrid = False
            meta = layout.meta if isinstance(layout.meta, dict) else {}
            # Compass rotations change presentation only. Monthly roses and
            # other non-directional polars retain their calendar reference.
            if settings.north_rotation and meta.get("compass_polar") is True:
                item.angularaxis.rotation = ((item.angularaxis.rotation
                    if item.angularaxis.rotation is not None else 90)
                    - settings.north_rotation) % 360
        elif name.startswith("scene") and not settings.show_grid:
            for axis in (item.xaxis,item.yaxis,item.zaxis):
                axis.showgrid=False
    if settings.line_scale != 1.0:
        for trace in fig.data:
            props = getattr(trace, "_props", {}) or {}
            if trace.type not in {"scatter","scattergl","scatterpolar","scatterpolargl","scatter3d"}:
                continue
            if "lines" not in (getattr(trace,"mode",None) or "lines"):
                continue
            # Retain explicit relative widths, including solar-path halos.
            line = trace.line
            if line.width != 0:
                line.width = max(0.1, min(30., float(line.width if line.width is not None else 2.) * settings.line_scale))


def apply_chart_presentation(fig: Any, settings: ChartPresentationSettings) -> Any:
    """Apply presentation-only layout changes to a Plotly figure in place."""
    if fig is None or not hasattr(fig, "layout"):
        return fig

    size = max(8, min(26, int(settings.font_size)))
    try:
        fig.update_layout(font=dict(size=size))
    except Exception:
        return fig

    layout = fig.layout
    background = TRANSPARENT_COLOR if settings.transparent else "white"
    _apply_background(layout, background, fig.data)
    for frame in getattr(fig, "frames", ()) or ():
        if getattr(frame, "layout", None) is not None and frame.layout.to_plotly_json():
            _apply_background(frame.layout, background, frame.data)
    try:
        _set_font_size(layout.title.font, size + 3)
    except Exception:
        pass
    try:
        _set_font_size(layout.hoverlabel.font, size)
    except Exception:
        pass

    # Cover ordinary and secondary legends, Cartesian subplots, polar wind
    # roses, 3D scenes and shared Plotly color axes. Most inherit the base layout
    # font, but explicit tick/title fonts need to be updated as well.
    for name in getattr(layout, "_props", {}):
        name_text = str(name)
        item = getattr(layout, name, None)
        if item is None:
            continue
        if name_text.startswith("legend"):
            _set_font_size(getattr(item, "font", None), size)
            title = getattr(item, "title", None)
            _set_font_size(getattr(title, "font", None), size)
        elif name_text.startswith("xaxis") or name_text.startswith("yaxis"):
            _set_axis_font(item, size)
        elif name_text.startswith("polar"):
            _set_axis_font(getattr(item, "angularaxis", None), size)
            _set_axis_font(getattr(item, "radialaxis", None), size)
        elif name_text.startswith("scene"):
            _set_axis_font(getattr(item, "xaxis", None), size)
            _set_axis_font(getattr(item, "yaxis", None), size)
            _set_axis_font(getattr(item, "zaxis", None), size)
        elif name_text.startswith("coloraxis"):
            _set_colorbar_font(getattr(item, "colorbar", None), size)

    for annotation in getattr(layout, "annotations", ()) or ():
        _set_font_size(getattr(annotation, "font", None), size)

    # Trace-local labels and colorbars can override the layout font. Crucially,
    # only touch colorbars that already exist in the serialized trace props.
    # Accessing ``trace.marker.colorbar`` on an ordinary Scatter lazily creates
    # a colorbar object in Plotly and can make a phantom scale appear next to
    # otherwise categorical line/marker charts.
    for trace in getattr(fig, "data", ()) or ():
        for font_name in ("textfont", "insidetextfont", "outsidetextfont"):
            _set_font_size(getattr(trace, font_name, None), size)

        trace_props = getattr(trace, "_props", {}) or {}
        marker_props = trace_props.get("marker") if isinstance(trace_props, Mapping) else None
        if isinstance(marker_props, Mapping) and "colorbar" in marker_props:
            marker = getattr(trace, "marker", None)
            _set_colorbar_font(getattr(marker, "colorbar", None), size)
        if isinstance(trace_props, Mapping) and "colorbar" in trace_props:
            _set_colorbar_font(getattr(trace, "colorbar", None), size)

    _apply_extra_presentation(fig, settings)
    _space_bottom_legends(fig, settings, size)

    dimensions = settings.display_dimensions()
    if dimensions is None:
        # Auto deliberately preserves the chart builder's responsive geometry.
        return fig

    width, height = dimensions
    try:
        fig.update_layout(width=width, height=height, autosize=False)
    except Exception:
        pass
    return fig


def merge_plotly_config(
    config: Mapping[str, Any] | None,
    settings: ChartPresentationSettings,
) -> dict[str, Any]:
    """Merge global image-export settings without discarding chart-local config."""
    merged = dict(config or {})
    export_options = dict(merged.get("toImageButtonOptions") or {})
    export_options.setdefault("format", "png")
    if settings.export_format == "SVG":
        export_options["format"] = "svg"
    if settings.transparent and export_options["format"] not in ("png", "svg"):
        export_options["format"] = "png"
    export_options["scale"] = max(1, min(3, int(settings.export_scale)))
    dimensions = settings.export_dimensions()
    if dimensions is not None:
        export_options["width"], export_options["height"] = dimensions
    merged["toImageButtonOptions"] = export_options
    return merged


def render_presentation_sidebar(st: Any) -> None:
    """Render the single global presentation control surface for this rerun."""
    ensure_default_state(st.session_state)
    with st.sidebar.expander("Presentation", expanded=False):
        st.selectbox(
            "Canvas",
            CANVAS_OPTIONS,
            key=KEY_CANVAS,
            help="Auto keeps the responsive chart geometry. Presets use a deterministic canvas independent of browser width.",
        )
        auto_canvas = st.session_state.get(KEY_CANVAS, DEFAULT_CANVAS) == CANVAS_AUTO
        st.slider(
            "Display width [%]",
            min_value=50,
            max_value=100,
            step=5,
            key=KEY_WIDTH,
            disabled=auto_canvas,
            help="Scales a preset/custom canvas for on-screen display. Export keeps the full canvas size.",
        )
        if auto_canvas:
            st.caption("Auto keeps the current responsive chart size. Choose a canvas preset or Custom to control proportions and display width.")
        st.slider(
            "Chart font size [pt]",
            min_value=8,
            max_value=26,
            step=1,
            key=KEY_FONT,
        )
        st.selectbox(
            "Chart background", BACKGROUND_OPTIONS, key=KEY_BACKGROUND,
            help="Applies globally to all charts and image exports. Transparent PNG preserves the alpha channel for architectural overlays.",
        )
        st.checkbox("Show chart title", key=_key("show_title"))
        st.checkbox("Show legend", key=_key("show_legend"))
        st.checkbox("Show grid", key=_key("show_grid"))
        st.slider("Line thickness multiplier", 0.5, 3.0, step=0.25, key=_key("line_scale"))
        st.selectbox("Image export format", ["PNG", "SVG"],key=_key("export_format"),
                     help="WebGL traces are rasterized inside SVG. PNG retains the full rendered scene.")
        st.slider("Compass rotation [deg clockwise]", -180,180,step=5,key=_key("north_rotation"),
                  help="Only compass-based polar diagrams. Physical azimuth and north labels rotate together.")
        st.text_input("Manual numeric axis title (exact match)",key=_key("axis_title"),
                      help="Empty = automatic. Enter the exact axis title to limit the range override to matching numeric axes.")
        if st.session_state[_key("axis_title")]:
            st.number_input("Axis minimum",key=_key("axis_min"))
            st.number_input("Axis maximum",key=_key("axis_max"))
            if st.session_state[_key("axis_min")] >= st.session_state[_key("axis_max")]:
                st.warning("Axis minimum must be below maximum; range override ignored.")
        st.select_slider(
            "Export scale",
            options=(1, 2, 3),
            key=KEY_EXPORT_SCALE,
            format_func=lambda value: f"{value}×",
            help="Resolution multiplier used by Plotly's Download plot as PNG action.",
        )
        if st.session_state.get(KEY_CANVAS, DEFAULT_CANVAS) == CANVAS_CUSTOM:
            c1, c2 = st.columns(2)
            c1.number_input(
                "Width [px]",
                min_value=320,
                max_value=3840,
                step=20,
                key=KEY_CUSTOM_WIDTH,
            )
            c2.number_input(
                "Height [px]",
                min_value=240,
                max_value=3840,
                step=20,
                key=KEY_CUSTOM_HEIGHT,
            )
        st.checkbox("Architectural reference image",value=False,key=_key("underlay_enabled"),
                    help="Only 2D compass polar charts; image remains local to this session.")
        if st.session_state.get(_key("underlay_enabled")):
            st.file_uploader("Reference plan / image",type=["png","jpg","jpeg","webp"],key=_key("underlay_file"))
            st.slider("Reference image scale",.25,2.,1.,.05,key=_key("underlay_scale"))
            st.slider("Reference horizontal offset",-.75,.75,0.,.025,key=_key("underlay_x"))
            st.slider("Reference vertical offset",-.75,.75,0.,.025,key=_key("underlay_y"))
            st.slider("Reference rotation [° clockwise]",-180,180,0,5,key=_key("underlay_rotation"))
            st.slider("Reference opacity",.1,1.,.75,.05,key=_key("underlay_opacity"))
            st.caption("Position, scale and rotate the plan relative to the compass chart. This is an illustration, not georeferencing.")
        st.button(
            "Reset chart appearance",
            key="chart_presentation_reset",
            on_click=reset_state,
            args=(st.session_state,),
            use_container_width=True,
        )


def install_global_chart_presentation(st: Any | None = None) -> None:
    """Install one global Plotly renderer and render its sidebar controls.

    The wrapper sits at the shared ``st.plotly_chart`` boundary. Consequently
    every existing and future Plotly chart inherits presentation settings without
    modifying scientific chart builders or adding local per-chart switches.
    """
    if st is None:
        import streamlit as st  # type: ignore[no-redef]

    render_presentation_sidebar(st)

    original_attr = "_climate_analyzer_original_plotly_chart"
    if not hasattr(st, original_attr):
        setattr(st, original_attr, st.plotly_chart)
    original = getattr(st, original_attr)

    capture_index = 0

    def global_plotly_chart(fig: Any, *args: Any, **kwargs: Any) -> Any:
        nonlocal capture_index
        capture_index += 1
        settings = settings_from_state(st.session_state)
        apply_chart_presentation(fig, settings)
        meta=fig.layout.meta if isinstance(fig.layout.meta,dict) else {}
        upload=st.session_state.get(_key("underlay_file"))
        if st.session_state.get(_key("underlay_enabled"),False) and upload is not None and meta.get("compass_polar"):
            from .architectural_underlay import prepare_underlay,apply_underlay
            try:
                source=prepare_underlay(upload.getvalue(),st.session_state.get(_key("underlay_rotation"),0))
                apply_underlay(fig,source,scale=st.session_state.get(_key("underlay_scale"),1.),
                    x=st.session_state.get(_key("underlay_x"),0.),y=st.session_state.get(_key("underlay_y"),0.),
                    opacity=st.session_state.get(_key("underlay_opacity"),.75))
            except (ValueError,OSError) as exc:
                st.warning(f"Reference image unavailable: {exc}")
        kwargs["config"] = merge_plotly_config(kwargs.get("config"), settings)
        if settings.transparent:
            # Streamlit theme defaults must not substitute an opaque canvas.
            kwargs["theme"] = None
        if not settings.is_auto:
            # A preset/custom canvas is intentionally deterministic.
            kwargs["use_container_width"] = False
        result=original(fig, *args, **kwargs)
        if st.session_state.get("_p6_report_context"):
            from .p6_report import capture_control
            capture_control(st,fig,kwargs.get("key") or capture_index)
        return result

    global_plotly_chart.__name__ = "global_plotly_chart"
    setattr(st, "plotly_chart", global_plotly_chart)
