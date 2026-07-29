# Voice Process Mining — Technical Report

## Overview

Single-file Streamlit app (`main.py`, ~965 lines) for process mining on a bakery production line (OpenEgiz project). Users can input process events via voice recognition (Whisper) or by uploading CSV/XES log files. The app then discovers and visualizes process models (DFG, Petri Net) using pm4py.

**Stack:** Python 3.13, Streamlit, OpenAI Whisper (turbo), pm4py, Graphviz, sounddevice, numpy, scipy, pandas.

**Platform:** Windows 10/11, Streamlit server mode.

---

## Architecture (single file: `main.py`)

```
main.py
├── Lines 1-15:     Imports
├── Lines 18-27:    TMPDIR + render_svg() helper
├── Lines 29-637:   Custom CSS (dark theme, animations, glassmorphism)
├── Lines 639-645:  Hero title
├── Lines 647-659:  Session state init + Whisper model loading
├── Lines 661-778:  Sidebar: voice recording + log upload (CSV/XES)
├── Lines 780-825:  Voice transcription result + event creation
├── Lines 827-867:  Event log stats + dataframe display
└── Lines 869-965:  Process Mining: DFG Frequency, DFG Performance, Petri Net
```

---

## Core Features

### 1. Voice Input (lines 661-698)
- Records audio via `sounddevice` at 16kHz mono float32
- Normalizes amplitude, trims silence (1s padding around speech)
- Saves to `TMPDIR/temp_command.wav`
- Transcribes with `whisper.load_model("turbo")` (cached), Russian language
- Auto-maps Russian keywords to English activity names:
  - замес → `start_mixing`
  - ингредиенты → `add_ingredients`
  - расстой → `proving`
  - печ → `load_oven`
  - вынима/готов → `unload_oven`
  - else → `other_activity`
- User confirms: set batch number + operator name, click "Add Event"

### 2. Log Upload (lines 702-768)
- **XES files:** Saved to temp file, read with `pm4py.read_xes()`, converted to DataFrame. Auto-detects `case:concept:name`, `time:timestamp` columns.
- **CSV files:** Read with pandas. Provides 4 selectboxes for column mapping (Case ID, Activity, Timestamp, Resource). Auto-suggests columns by keyword matching.
- All timestamps normalized to tz-naive UTC via `pd.to_datetime(..., utc=True).dt.tz_localize(None)` — fixes tz-aware/tz-naive mixing errors.

### 3. Event Log (lines 827-867)
- Stored in `st.session_state.event_log` as DataFrame with columns: `case:concept:name`, `concept:name`, `time:timestamp`, `org:resource`, `text`
- Displays 4 stat cards (Events, Cases, Activities, Resources counts)
- Scrollable dataframe (height=300)

### 4. Process Mining (lines 869-965)
- Triggered by "Launch Process Mining" button or auto after log import (`pm_ready` flag)
- Requires minimum 2 events
- Constructs `EventLog` from DataFrame, grouped by `case:concept:name`
- Generates 3 visualizations:
  - **DFG Frequency** — `pm4py.discover_dfg()` + `dfg_gviz.graphviz_visualization(measure="frequency")`
  - **DFG Performance** — same with `measure="performance"` + service times
  - **Petri Net** — `pm4py.discover_petri_net_inductive()` + `pn_visualizer.apply(variant=Variants.WO_DECORATION)`
- All graphs rendered as **SVG** (vector, infinite resolution) into `TMPDIR`
- SVG content read back and injected via `st.markdown(unsafe_allow_html=True)` in styled containers

---

## Rendering Pipeline (critical to understand)

```python
TMPDIR = tempfile.mkdtemp(prefix="pm_graphs_")

def render_svg(gviz_obj, name):
    gviz_obj.render(os.path.join(TMPDIR, name), cleanup=True)
    svg_path = os.path.join(TMPDIR, name + ".svg")
    with open(svg_path, "r", encoding="utf-8") as f:
        return f.read()
```

**Why TMPDIR:** Graphviz `render()` on Windows causes `PermissionError: [Errno 13]` when writing to the project directory (files get locked by the running process or Windows Defender). Using a temp directory avoids this completely.

**Petri Net** uses `pn_visualizer.apply()` (returns graphviz Digraph), then `gviz_pn.attr(format="svg")` before calling `render_svg()`. Do NOT use `pm4py.save_vis_petri_net()` — it doesn't allow SVG format or custom directories.

---

## Design System

### Theme (CSS custom properties, line 34-48)
```
--bg-deep: #05050a          (deepest background)
--bg-primary: #0a0a12       (app background)
--accent-violet: #7c5cfc    (primary accent)
--accent-cyan: #00e5d0      (secondary accent)
--accent-magenta: #f849a2   (tertiary accent)
--accent-amber: #ffb347     (quaternary accent)
--text-primary: #f0f0f8
--text-secondary: #7878a0
--text-muted: #4a4a6a
--glass-bg: rgba(255,255,255,0.025)
--glass-border: rgba(255,255,255,0.06)
```

### Fonts
- **Inter** (300-900) — UI text
- **JetBrains Mono** (400-600) — stat numbers

### Animations (all pure CSS)
| Name | Effect | Duration |
|------|--------|----------|
| `meshDrift` | Background hue-rotate + scale | 12s |
| `heroGradient` | Title gradient position shift | 5s |
| `lineExpand` | Underline width 0→120px | 1.5s (delay 0.5s) |
| `cardIn` | Cards fade-in from below with scale | 0.5-0.6s |
| `gentleFloat` | Icons float up/down | 3s |
| `pFloat` | Particles float bottom→top | 12-20s per particle |
| `orbDrift` | Glow orbs drift position | 20s |
| `graphIn` | Graph containers scale-in | 0.8s |

### Decorative Elements (HTML injected)
- 10 floating particles (`.p` divs) with staggered delays/colors
- 2 glow orbs (`.glow-orb.v` violet, `.glow-orb.c` cyan) with blur(80px)
- Gradient dividers between sidebar sections

### Component Styling
- **Glassmorphism cards** — backdrop-filter blur, gradient top-border, hover lift
- **Stat cards** — 4-column grid, gradient numbers, animated icons, bottom gradient bar on hover
- **Buttons** — gradient background, sweep shine on hover, glow shadow
- **File uploader** — dashed violet border, hover glow
- **Graph containers** — white background (for SVG readability), gradient border via CSS mask, hover lift
- **Section headers** — title + badge + gradient line

---

## Known Gotchas & Solutions

| Problem | Solution | Location |
|---------|----------|----------|
| `PermissionError: [Errno 13] Permission denied` on graphviz render | Render to `tempfile.mkdtemp()` not project dir | Line 19-27 |
| `ImportError: cannot import 'graphviz_visualization' from pm4py.visualization.petri_net.util` | Use `pm4py.visualization.petri_net.visualizer.apply()` instead | Line 959-960 |
| `'UploadedFile' object has no attribute 'decode'` on XES upload | Save UploadedFile to temp file first, then `pm4py.read_xes(tmp_path)` | Line 708-711 |
| `ValueError: Cannot mix tz-aware with tz-naive values` in timestamps | `pd.to_datetime(..., utc=True).dt.tz_localize(None)` | Lines 755, 878 |
| Sidebar collapse button hidden | Don't use `header { display: none }` — it hides the toggle. Use specific `data-testid` selectors | Lines 84-101 |
| Slider visual artifacts | Don't override `width`/`height`/`border-radius` on slider thumb — use `[data-baseweb="thumb"]` and `[role="slider"]` | Lines 103-118 |
| Poor image quality | Use `image_format="svg"` instead of `"png"` | Lines 915, 938, 961 |

---

## Session State Keys

| Key | Type | Purpose |
|-----|------|---------|
| `event_log` | DataFrame | Main event log (5 columns) |
| `pm_ready` | bool | Auto-trigger PM after log import |
| `transcription` | str/None | Latest Whisper transcription result |

---

## pm4py API Usage

```python
# DFG discovery
dfg, start_activities, end_activities = pm4py.discover_dfg(log)

# DFG visualization (frequency)
gviz = dfg_gviz.graphviz_visualization(
    activities_count, dfg,
    image_format="svg",
    measure="frequency",  # or "performance"
    start_activities=sa, end_activities=ea,
    font_size="14", bgcolor="white", rankdir="LR",
    enable_graph_title=True, graph_title="DFG - Frequency"
)

# Performance service times
serv_time = serv_time_get.apply(log)

# Petri Net
from pm4py.visualization.petri_net import visualizer as pn_visualizer
net, im, fm = pm4py.discover_petri_net_inductive(log)
gviz = pn_visualizer.apply(net, im, fm, variant=pn_visualizer.Variants.WO_DECORATION)
gviz.attr(format="svg")
```

**Important:** Do NOT use `pm4py.save_vis_petri_net()` for custom rendering. Use `pn_visualizer.apply()` which returns a graphviz Digraph.

---

## Dependencies

```
streamlit
pandas
openai-whisper
pm4py
sounddevice
numpy
scipy
graphviz
```

Graphviz system binary must be installed and on PATH (`dot` command).

---

## File Structure

```
Process-Mining/
├── main.py              # Entire application (965 lines)
├── REPORT.md            # This file
├── dfg_freq.png         # (legacy, now using SVG in TMPDIR)
├── dfg_perf.png         # (legacy)
├── petri_net.png        # (legacy)
└── temp_command.wav     # (runtime, in TMPDIR now)
```

---

## Future Development Notes

- The entire app is a single file. If expanding, extract CSS to `style.css`, helper functions to `utils.py`, and PM logic to `mining.py`.
- Activity mapping (lines 784-789) is hardcoded for bakery. Would need a config file or NLP for general use.
- No authentication/authorization.
- No database — event log lives in `st.session_state` (lost on server restart). Consider adding SQLite or file persistence.
- The `whisper.load_model("turbo")` is cached with `@st.cache_resource` — loads once per server session.
- SVG graphs have white backgrounds (line 458: `background: rgba(255,255,255,0.97)`) for readability against dark theme.
