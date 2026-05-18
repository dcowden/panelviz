"""Static interactive viewer export."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from panelviz.components import PinSide
from panelviz.parser import UnitsConfig
from panelviz.routing import RoutedWire, WireRouter
from panelviz.visualization import (
    ApproximateTextMeasurer,
    ComponentVisualConfig,
    PinBox,
    plan_component_sheet_layout,
)


VIEWER_FILES = ("viewer.html", "viewer.css", "viewer.js", "panel-data.json")


def write_static_viewer(
    router: WireRouter,
    path: str | Path,
    units: UnitsConfig | None = None,
    columns: int | None = None,
    config: ComponentVisualConfig | None = None,
) -> list[Path]:
    """Write a no-build static SVG.js viewer bundle."""

    output_dir = Path(path)
    output_dir.mkdir(parents=True, exist_ok=True)
    data = viewer_data(router, units=units, columns=columns, config=config)

    files = {
        "viewer.html": _viewer_html(),
        "viewer.css": _viewer_css(),
        "viewer.js": _viewer_js(),
        "panel-data.json": json.dumps(data, indent=2),
    }
    written = []
    for name, contents in files.items():
        target = output_dir / name
        target.write_text(contents, encoding="utf-8")
        written.append(target)
    return written


def viewer_data(
    router: WireRouter,
    units: UnitsConfig | None = None,
    columns: int | None = None,
    config: ComponentVisualConfig | None = None,
) -> dict[str, Any]:
    """Build the JSON view model used by the static interactive viewer."""

    render_units = units or UnitsConfig()
    visual_config = config or ComponentVisualConfig()
    components = list(router.components.values())
    sheet = plan_component_sheet_layout(
        components,
        render_units,
        columns,
        visual_config,
        ApproximateTextMeasurer(),
    )
    margin = visual_config.wiring_label_margin_pt
    component_data = []
    anchors: dict[str, _Anchor] = {}

    for layout in sheet.layouts:
        component_x, component_y = sheet.positions[layout.component_name]
        x = component_x + margin + layout.margin_pt
        y = component_y + margin + layout.margin_pt
        pins = []
        for box in layout.pin_boxes:
            anchor = _pin_anchor(box, x, y)
            node = f"{layout.component_name}.{box.pin}"
            anchors[node] = anchor
            pins.append(
                {
                    "node": node,
                    "pin": box.pin,
                    "side": box.side.value,
                    "x": box.x,
                    "y": box.y,
                    "width": box.width,
                    "height": box.height,
                    "anchor": {"x": anchor.x, "y": anchor.y},
                }
            )

        component_data.append(
            {
                "name": layout.component_name,
                "type": router.components[layout.component_name].type.value,
                "x": x,
                "y": y,
                "width": layout.width_pt,
                "height": layout.height_pt,
                "center": {
                    "x": layout.center_x,
                    "y": layout.center_y,
                    "width": layout.center_width,
                    "height": layout.center_height,
                },
                "font": {
                    "pin": layout.typography.pin_font_size_pt,
                    "name": layout.typography.component_name_font_size_pt,
                },
                "pins": pins,
            }
        )

    endpoint_slots = _endpoint_slots(router.routed_wires)
    wires = [_wire_view(wire, anchors, router, visual_config, endpoint_slots) for wire in router.routed_wires]
    return {
        "canvas": {
            "width": sheet.width_pt + margin * 2,
            "height": sheet.height_pt + margin * 2,
        },
        "styles": {
            "default": router.visualization.default_net_style.model_dump(),
            "nets": {name: style.model_dump() for name, style in router.visualization.net_styles.items()},
        },
        "components": component_data,
        "wires": wires,
        "diagnostics": _diagnostics(router),
    }


@dataclass(frozen=True)
class _Anchor:
    x: float
    y: float
    side: PinSide


@dataclass(frozen=True)
class _EndpointSlot:
    index: int
    count: int


def _pin_anchor(box: PinBox, offset_x: float, offset_y: float) -> _Anchor:
    if box.side == PinSide.LEFT:
        return _Anchor(offset_x + box.x, offset_y + box.y + box.height / 2, box.side)
    if box.side == PinSide.RIGHT:
        return _Anchor(offset_x + box.x + box.width, offset_y + box.y + box.height / 2, box.side)
    if box.side == PinSide.TOP:
        return _Anchor(offset_x + box.x + box.width / 2, offset_y + box.y, box.side)
    return _Anchor(offset_x + box.x + box.width / 2, offset_y + box.y + box.height, box.side)


def _wire_view(
    wire: RoutedWire,
    anchors: dict[str, _Anchor],
    router: WireRouter,
    config: ComponentVisualConfig,
    endpoint_slots: dict[tuple[int, str], _EndpointSlot],
) -> dict[str, Any]:
    from_anchor = anchors[str(wire.from_pin)]
    to_anchor = anchors[str(wire.to_pin)]
    style_model = router.visualization.style_for_net(wire.net_name or "")
    style = style_model.model_dump()
    style["line_weight"] = _wire_line_weight(style_model.line_weight, wire.awg)
    return {
        "index": wire.index,
        "label": wire.wire_label or f"wire-{wire.index}",
        "net": wire.net_name or "",
        "awg": wire.awg,
        "from": str(wire.from_pin),
        "to": str(wire.to_pin),
        "from_component": wire.from_pin.component,
        "from_pin": wire.from_pin.pin,
        "to_component": wire.to_pin.component,
        "to_pin": wire.to_pin.pin,
        "style": style,
        "endpoints": [
            _endpoint_view(
                str(wire.from_pin),
                wire.from_pin.component,
                wire.from_pin.pin,
                wire.wire_label or f"wire-{wire.index}",
                from_anchor,
                config,
                endpoint_slots[(wire.index, "from")],
            ),
            _endpoint_view(
                str(wire.to_pin),
                wire.to_pin.component,
                wire.to_pin.pin,
                wire.wire_label or f"wire-{wire.index}",
                to_anchor,
                config,
                endpoint_slots[(wire.index, "to")],
            ),
        ],
    }


def _endpoint_view(
    node: str,
    component: str,
    pin: str,
    wire_label: str,
    anchor: _Anchor,
    config: ComponentVisualConfig,
    slot: _EndpointSlot,
) -> dict[str, Any]:
    dx, dy = _side_vector(anchor.side)
    fan_x, fan_y = _fan_offset(anchor.side, slot, 20.0)
    stub = {
        "x": anchor.x + dx * config.wire_stub_pt + fan_x,
        "y": anchor.y + dy * config.wire_stub_pt + fan_y,
    }
    label_width = max(44.0, len(wire_label) * 7.2 + 12)
    label_height = 17.0
    label_offset = config.wire_label_gap_pt + label_width / 2
    label_position = {
        "x": stub["x"] + dx * label_offset,
        "y": stub["y"] + dy * label_offset,
        "width": label_width,
        "height": label_height,
        "rotation": 0,
        "side": anchor.side.value,
        "slot": slot.index,
        "slot_count": slot.count,
    }
    if anchor.side in {PinSide.TOP, PinSide.BOTTOM}:
        label_position["rotation"] = 90

    return {
        "node": node,
        "component": component,
        "pin": pin,
        "side": anchor.side.value,
        "anchor": {"x": anchor.x, "y": anchor.y},
        "stub": stub,
        "stub_length": config.wire_stub_pt,
        "label_gap": config.wire_label_gap_pt,
        "label": label_position,
    }


def _wire_line_weight(base_weight: float, awg: int | None) -> float:
    if awg is None:
        return base_weight
    weight = base_weight + max(0, 20 - awg) * 0.12
    if awg <= 12:
        weight *= 2
    return max(base_weight, weight)


def _side_vector(side: PinSide) -> tuple[float, float]:
    if side == PinSide.LEFT:
        return -1.0, 0.0
    if side == PinSide.RIGHT:
        return 1.0, 0.0
    if side == PinSide.TOP:
        return 0.0, -1.0
    return 0.0, 1.0


def _fan_offset(side: PinSide, slot: _EndpointSlot, spacing: float) -> tuple[float, float]:
    if slot.count <= 1:
        return 0.0, 0.0
    offset = (slot.index - (slot.count - 1) / 2) * spacing
    if side in {PinSide.LEFT, PinSide.RIGHT}:
        return 0.0, offset
    return offset, 0.0


def _endpoint_slots(wires: list[RoutedWire]) -> dict[tuple[int, str], _EndpointSlot]:
    endpoints = []
    for wire in wires:
        endpoints.append(((wire.index, "from"), str(wire.from_pin)))
        endpoints.append(((wire.index, "to"), str(wire.to_pin)))

    counts = Counter(node for _, node in endpoints)
    seen: defaultdict[str, int] = defaultdict(int)
    slots: dict[tuple[int, str], _EndpointSlot] = {}
    for key, node in endpoints:
        slots[key] = _EndpointSlot(index=seen[node], count=counts[node])
        seen[node] += 1
    return slots


def _diagnostics(router: WireRouter) -> dict[str, list[dict[str, Any]]]:
    unconnected = []
    multi_connected = []
    isolated_components = []
    for component_name, component in router.components.items():
        statuses = router.pin_statuses(component_name)
        routed_count = sum(status.connection_count for status in statuses)
        if routed_count == 0:
            isolated_components.append({"component": component_name, "type": component.type.value})
        for status in statuses:
            node = str(status.pin)
            if not status.is_routed and not status.is_no_connect:
                unconnected.append({"node": node, "component": status.pin.component, "pin": status.pin.pin})
            if status.connection_count > 1:
                multi_connected.append(
                    {
                        "node": node,
                        "component": status.pin.component,
                        "pin": status.pin.pin,
                        "connections": status.connection_count,
                    }
                )
    return {
        "unconnected_pins": unconnected,
        "multi_connected_pins": multi_connected,
        "isolated_components": isolated_components,
    }


def _viewer_html() -> str:
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>PanelViz Viewer</title>
  <link rel="stylesheet" href="viewer.css">
  <script src="https://cdn.jsdelivr.net/npm/@svgdotjs/svg.js@3.2.4/dist/svg.min.js"></script>
</head>
<body>
  <main class="app-shell">
    <header class="toolbar">
      <div>
        <h1>PanelViz</h1>
        <p id="status">Loading panel...</p>
      </div>
      <div class="help-strip">
        <span>Drag canvas: pan</span>
        <span>Wheel: zoom</span>
        <span>Right-click canvas: clear</span>
        <span>Right-click component: rotate</span>
      </div>
      <div class="diagnostic-actions" role="group" aria-label="Diagnostic highlighting">
        <button id="show-unconnected" type="button">Unconnected</button>
        <button id="show-multiconnected" type="button">Multi-connected</button>
        <button id="show-isolated" type="button">No Connections</button>
      </div>
      <div class="controls" role="group" aria-label="Highlight mode">
        <label><input type="radio" name="highlight-mode" value="wire" checked> Wire</label>
        <label><input type="radio" name="highlight-mode" value="net"> Net</label>
        <button id="toggle-wire-table" type="button">Hide Wires</button>
        <button id="clear-selection" type="button">Clear</button>
      </div>
    </header>
    <section class="workspace">
      <section id="canvas-host" aria-label="Interactive PanelViz wiring canvas"></section>
      <div id="wire-table-resizer" aria-hidden="true"></div>
      <aside class="wire-table-panel" aria-label="Wire list">
        <div class="wire-table-header">
          <h2>Wire List</h2>
          <div class="wire-table-actions">
            <button id="toggle-wire-columns" type="button">Split Columns</button>
          </div>
        </div>
        <div class="wire-table-scroll">
          <table class="wire-table">
            <thead id="wire-table-head"></thead>
            <tbody id="wire-table-body"></tbody>
          </table>
        </div>
      </aside>
    </section>
  </main>
  <script src="viewer.js"></script>
</body>
</html>
"""


def _viewer_css() -> str:
    return """html, body {
  height: 100%;
  margin: 0;
  font-family: Inter, Segoe UI, Arial, sans-serif;
  color: #0f172a;
  background: #e5e7eb;
}
.app-shell {
  height: 100%;
  display: grid;
  grid-template-rows: auto 1fr;
}
.workspace {
  min-height: 0;
  display: grid;
  grid-template-columns: minmax(0, 1fr) 6px var(--wire-table-width, 420px);
}
.workspace.table-collapsed {
  grid-template-columns: minmax(0, 1fr) 0 0;
}
.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  padding: 12px 16px;
  border-bottom: 1px solid #cbd5e1;
  background: #ffffff;
}
.help-strip {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  color: #475569;
  font-size: 11px;
}
.help-strip span {
  padding: 2px 6px;
  border: 1px solid #cbd5e1;
  border-radius: 4px;
  background: #f8fafc;
}
h1 {
  margin: 0;
  font-size: 18px;
}
p {
  margin: 2px 0 0;
  color: #64748b;
  font-size: 12px;
}
.controls {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 13px;
}
.diagnostic-actions,
.wire-table-actions {
  display: flex;
  align-items: center;
  gap: 6px;
}
button {
  border: 1px solid #94a3b8;
  background: #f8fafc;
  color: #0f172a;
  padding: 5px 9px;
  border-radius: 4px;
}
#canvas-host {
  min-height: 0;
  overflow: auto;
  background:
    linear-gradient(#f8fafc 1px, transparent 1px),
    linear-gradient(90deg, #f8fafc 1px, transparent 1px),
    #eef2f7;
  background-size: 24px 24px;
}
#canvas-host.panning {
  cursor: grabbing;
}
#wire-table-resizer {
  min-height: 0;
  cursor: col-resize;
  background: #dbe3ee;
}
#wire-table-resizer:hover {
  background: #94a3b8;
}
.table-collapsed #wire-table-resizer,
.table-collapsed .wire-table-panel {
  display: none;
}
.wire-table-panel {
  min-width: 0;
  min-height: 0;
  display: grid;
  grid-template-rows: auto 1fr;
  border-left: 1px solid #cbd5e1;
  background: #ffffff;
}
.wire-table-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 10px 12px;
  border-bottom: 1px solid #e2e8f0;
}
h2 {
  margin: 0;
  font-size: 14px;
}
.wire-table-scroll {
  overflow: auto;
}
.wire-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}
.wire-table th,
.wire-table td {
  padding: 6px 8px;
  border-bottom: 1px solid #e2e8f0;
  text-align: left;
  white-space: nowrap;
}
.wire-table th {
  position: sticky;
  top: 0;
  z-index: 1;
  background: #f8fafc;
  color: #475569;
  font-weight: 800;
}
.wire-table thead tr:nth-child(2) th {
  top: 29px;
}
.wire-table th button {
  width: 100%;
  border: 0;
  padding: 0;
  background: transparent;
  color: inherit;
  font: inherit;
  text-align: inherit;
  cursor: pointer;
}
.wire-table th button::after {
  content: attr(data-sort-marker);
  padding-left: 4px;
}
.wire-table-row {
  border-left: 4px solid var(--net-color, #475569);
  cursor: pointer;
}
.wire-table-row:hover {
  background: #f8fafc;
}
.wire-table-row.dimmed {
  opacity: 0.3;
}
.wire-table-row.selected {
  background: color-mix(in srgb, var(--net-color, #475569) 12%, white);
}
.wire-chip {
  display: inline-block;
  min-width: 58px;
  padding: 2px 6px;
  border: 1px solid var(--net-color, #475569);
  border-radius: 4px;
  background: color-mix(in srgb, var(--net-color, #475569) 10%, white);
  font-weight: 800;
}
svg {
  display: block;
  min-width: 100%;
  min-height: 100%;
}
.component {
  cursor: grab;
}
.component.dragging {
  cursor: grabbing;
}
.component.selected .component-body {
  stroke-width: 2.4;
}
.component-body {
  fill: #ffffff;
  stroke: #1f2937;
  stroke-width: 1.8;
  filter: drop-shadow(0 3px 6px rgb(15 23 42 / 0.14));
}
.component-outline-overlay {
  fill: none;
  stroke: #1f2937;
  stroke-width: 1.8;
  pointer-events: none;
}
.component-center {
  fill: #ffffff;
}
.component-name {
  text-anchor: middle;
  dominant-baseline: middle;
  fill: #0f172a;
  font-weight: 800;
  pointer-events: none;
}
.component-type {
  text-anchor: middle;
  dominant-baseline: middle;
  fill: #64748b;
  font-weight: 700;
  pointer-events: none;
}
.pin-box {
  fill: #f8fafc;
  stroke: #94a3b8;
  stroke-width: 0.75;
  cursor: pointer;
}
.pin-label {
  text-anchor: middle;
  dominant-baseline: middle;
  fill: #0f172a;
  pointer-events: none;
}
.wire-stub {
  fill: none;
  stroke: var(--net-color, #475569);
  stroke-width: var(--net-weight, 1.6);
  stroke-dasharray: var(--net-dasharray, none);
  stroke-linecap: round;
}
.wire-dot {
  fill: var(--net-color, #475569);
  stroke: #ffffff;
  stroke-width: 1.2;
}
.wire-label-bg {
  fill: #ffffff;
  stroke: var(--net-color, #475569);
  stroke-width: 0.8;
}
.wire-label-text {
  text-anchor: middle;
  dominant-baseline: middle;
  font-size: 11px;
  font-weight: 800;
  fill: #0f172a;
  pointer-events: none;
}
.wire-label-group {
  cursor: pointer;
}
.dimmed {
  opacity: 0.18;
}
.selected .wire-stub,
.selected.wire-stub {
  stroke-width: var(--net-selected-weight, 4);
}
.selected .wire-dot,
.selected.wire-dot {
  stroke: var(--net-color, #475569);
  stroke-width: 3;
}
.selected .wire-label-bg,
.selected.wire-label-bg,
.selected.pin-box,
.diagnostic-selected.pin-box {
  stroke: var(--net-color, #475569);
  stroke-width: 2.4;
  fill: color-mix(in srgb, var(--net-color, #475569) 12%, white);
}
.diagnostic-selected.pin-box {
  --net-color: #dc2626;
}
.diagnostic-selected.component .component-body,
.diagnostic-selected.component .component-outline-overlay {
  stroke: #dc2626;
  stroke-width: 2.8;
}
"""


def _viewer_js() -> str:
    return """const NS = 'http://www.w3.org/2000/svg';

const state = {
  mode: 'wire',
  selectedWire: null,
  selectedNet: null,
  selectedWires: [],
  selectedNets: [],
  selectedNode: null,
  selectedComponent: null,
  viewBox: null,
  canvas: null,
  data: null,
  components: new Map(),
  tableMode: 'combined',
  sortKey: 'index',
  sortDirection: 'asc',
  diagnosticNodes: [],
  diagnosticComponents: [],
};

const host = document.getElementById('canvas-host');
const workspace = document.querySelector('.workspace');
const statusEl = document.getElementById('status');
const wireTableHead = document.getElementById('wire-table-head');
const wireTableBody = document.getElementById('wire-table-body');
const toggleWireColumnsButton = document.getElementById('toggle-wire-columns');
const toggleWireTableButton = document.getElementById('toggle-wire-table');
const wireTableResizer = document.getElementById('wire-table-resizer');

document.querySelectorAll('input[name="highlight-mode"]').forEach((input) => {
  input.addEventListener('change', () => {
    state.mode = input.value;
    if (state.selectedComponent) {
      selectComponent(state.selectedComponent);
    } else if (state.selectedNode) {
      selectPin(state.selectedNode);
    } else {
      applyHighlight();
    }
  });
});

document.getElementById('clear-selection').addEventListener('click', () => {
  clearSelectionState();
  applyHighlight();
});

document.getElementById('show-unconnected').addEventListener('click', () => {
  selectDiagnosticNodes(state.data.diagnostics.unconnected_pins.map((item) => item.node));
});

document.getElementById('show-multiconnected').addEventListener('click', () => {
  selectDiagnosticNodes(state.data.diagnostics.multi_connected_pins.map((item) => item.node));
});

document.getElementById('show-isolated').addEventListener('click', () => {
  clearSelectionState();
  state.diagnosticComponents = state.data.diagnostics.isolated_components.map((item) => item.component);
  applyHighlight();
});

toggleWireColumnsButton.addEventListener('click', () => {
  state.tableMode = state.tableMode === 'combined' ? 'split' : 'combined';
  toggleWireColumnsButton.textContent = state.tableMode === 'combined' ? 'Split Columns' : 'Combined Columns';
  renderWireTable(state.data.wires);
  applyHighlight();
});

toggleWireTableButton.addEventListener('click', () => {
  workspace.classList.toggle('table-collapsed');
  toggleWireTableButton.textContent = workspace.classList.contains('table-collapsed') ? 'Show Wires' : 'Hide Wires';
});

fetch('panel-data.json')
  .then((response) => response.json())
  .then((data) => render(data))
  .catch((error) => {
    statusEl.textContent = `Could not load panel-data.json: ${error}`;
  });

function render(data) {
  host.textContent = '';
  state.data = data;
  state.components = new Map(data.components.map((component) => [component.name, {
    ...component,
    baseX: component.x,
    baseY: component.y,
    rotation: 0,
  }]));
  state.canvas = data.canvas;
  state.viewBox = { x: 0, y: 0, width: data.canvas.width, height: data.canvas.height };
  const svg = createCanvas(data.canvas);

  const componentsLayer = el('g', { class: 'components-layer' });
  svg.appendChild(componentsLayer);

  data.components.forEach((component) => renderComponent(componentsLayer, component));
  data.wires.forEach((wire) => renderWireEndpointGroups(wire));
  renderWireTable(data.wires);

  enableDrag(svg);
  enablePan(svg);
  enableZoom(svg);
  enableContextMenu(svg);
  enableTableResize();
  statusEl.textContent = `${data.components.length} components, ${data.wires.length} wires. SVG.js ${window.SVG ? 'loaded' : 'fallback renderer active'}.`;
}

function createCanvas(canvas) {
  if (window.SVG) {
    const draw = SVG().addTo(host).viewbox(0, 0, canvas.width, canvas.height).attr({
      role: 'img',
      'aria-label': 'PanelViz interactive wiring viewer',
    });
    return draw.node;
  }
  const svg = el('svg', {
    viewBox: `0 0 ${canvas.width} ${canvas.height}`,
    role: 'img',
    'aria-label': 'PanelViz interactive wiring viewer',
  });
  host.appendChild(svg);
  return svg;
}

function renderComponent(layer, component) {
  const storedComponent = state.components.get(component.name);
  const group = el('g', {
    class: 'component',
    'data-component': component.name,
  });
  group.dataset.x = component.x;
  group.dataset.y = component.y;
  group.dataset.rotation = 0;

  const body = el('rect', {
    class: 'component-body component-drag-surface',
    x: 0,
    y: 0,
    width: component.width,
    height: component.height,
    rx: 6,
    ry: 6,
  });
  bindComponentSelectTarget(body, group, component.name);
  group.appendChild(body);

  const center = el('rect', {
    class: 'component-center component-drag-surface',
    x: component.center.x,
    y: component.center.y,
    width: component.center.width,
    height: component.center.height,
  });
  bindComponentSelectTarget(center, group, component.name);
  group.appendChild(center);
  const centerX = component.center.x + component.center.width / 2;
  const centerY = component.center.y + component.center.height / 2;
  const fittedNameSize = fitTextSize(component.name, component.font.name, component.center.width - 8, 7);
  const typeFontSize = fitTextSize(component.type, Math.max(6, fittedNameSize * 0.58), component.center.width - 8, 5.5);
  group.appendChild(textEl(component.name, {
    class: 'component-name',
    'data-text-role': 'name',
    'data-center-x': centerX,
    'data-center-y': centerY,
    x: centerX,
    y: centerY - typeFontSize * 0.55,
    'font-size': fittedNameSize,
  }));
  group.appendChild(textEl(component.type, {
    class: 'component-type',
    'data-text-role': 'type',
    'data-center-x': centerX,
    'data-center-y': centerY,
    x: centerX,
    y: centerY + fittedNameSize * 0.75,
    'font-size': typeFontSize,
  }));

  component.pins.forEach((pin) => {
    const pinBox = el('rect', {
      class: 'pin-box',
      'data-node': pin.node,
      'data-component': component.name,
      x: pin.x,
      y: pin.y,
      width: pin.width,
      height: pin.height,
    });
    pinBox.addEventListener('click', (event) => {
      event.stopPropagation();
      selectPin(pin.node);
    });
    group.appendChild(pinBox);
    group.appendChild(textEl(pin.pin, {
      class: 'pin-label',
      x: pin.x + pin.width / 2,
      y: pin.y + pin.height / 2,
      'font-size': component.font.pin,
    }));
  });
  group.appendChild(el('rect', {
    class: 'component-outline-overlay',
    x: 0,
    y: 0,
    width: component.width,
    height: component.height,
    rx: 6,
    ry: 6,
  }));
  group.appendChild(el('g', {
    class: 'component-endpoint-layer',
    'data-component': component.name,
  }));
  updateComponentTransform(group, storedComponent);
  layer.appendChild(group);
}

function bindComponentSelectTarget(target, group, componentName) {
  target.addEventListener('click', (event) => {
    if (group.dataset.ignoreClick === 'true') {
      group.dataset.ignoreClick = 'false';
      return;
    }
    event.stopPropagation();
    selectComponent(componentName);
  });
}

function renderWireTable(wires) {
  renderWireTableHeader();
  wireTableBody.textContent = '';
  sortedWires(wires).forEach((wire) => {
    const row = document.createElement('tr');
    row.className = 'wire-table-row';
    row.dataset.wire = String(wire.index);
    row.dataset.net = wire.net;
    setNetStyle(row, wire.style);
    row.innerHTML = state.tableMode === 'combined'
      ? `
        <td><span class="wire-chip">${escapeHtml(wire.label)}</span></td>
        <td>${escapeHtml(wire.from)}</td>
        <td>${escapeHtml(wire.to)}</td>
        <td>${escapeHtml(wire.net)}</td>
        <td>${escapeHtml(wire.awg)}</td>
      `
      : `
        <td><span class="wire-chip">${escapeHtml(wire.label)}</span></td>
        <td>${escapeHtml(wire.from_component)}</td>
        <td>${escapeHtml(wire.from_pin)}</td>
        <td>${escapeHtml(wire.to_component)}</td>
        <td>${escapeHtml(wire.to_pin)}</td>
        <td>${escapeHtml(wire.net)}</td>
        <td>${escapeHtml(wire.awg)}</td>
      `;
    row.addEventListener('click', () => {
      selectWire(String(wire.index), wire.net);
      applyHighlight();
    });
    wireTableBody.appendChild(row);
  });
}

function renderWireTableHeader() {
  const marker = (key) => state.sortKey === key ? (state.sortDirection === 'asc' ? '^' : 'v') : '';
  if (state.tableMode === 'combined') {
    wireTableHead.innerHTML = `
      <tr>
        ${sortableHeader('Wire', 'label', marker('label'))}
        ${sortableHeader('From', 'from', marker('from'))}
        ${sortableHeader('To', 'to', marker('to'))}
        ${sortableHeader('Net', 'net', marker('net'))}
        ${sortableHeader('AWG', 'awg', marker('awg'))}
      </tr>
    `;
  } else {
    wireTableHead.innerHTML = `
      <tr>
        <th rowspan="2">${sortButton('Wire', 'label', marker('label'))}</th>
        <th colspan="2">From</th>
        <th colspan="2">To</th>
        <th rowspan="2">${sortButton('Net', 'net', marker('net'))}</th>
        <th rowspan="2">${sortButton('AWG', 'awg', marker('awg'))}</th>
      </tr>
      <tr>
        ${sortableHeader('Component', 'from_component', marker('from_component'))}
        ${sortableHeader('Terminal', 'from_pin', marker('from_pin'))}
        ${sortableHeader('Component', 'to_component', marker('to_component'))}
        ${sortableHeader('Terminal', 'to_pin', marker('to_pin'))}
      </tr>
    `;
  }
  wireTableHead.querySelectorAll('button[data-sort-key]').forEach((button) => {
    button.addEventListener('click', () => sortWireTable(button.dataset.sortKey));
  });
}

function sortableHeader(label, key, marker) {
  return `<th>${sortButton(label, key, marker)}</th>`;
}

function sortButton(label, key, marker) {
  return `<button type="button" data-sort-key="${key}" data-sort-marker="${marker}">${label}</button>`;
}

function sortWireTable(key) {
  if (state.sortKey === key) {
    state.sortDirection = state.sortDirection === 'asc' ? 'desc' : 'asc';
  } else {
    state.sortKey = key;
    state.sortDirection = 'asc';
  }
  renderWireTable(state.data.wires);
  applyHighlight();
}

function sortedWires(wires) {
  const direction = state.sortDirection === 'asc' ? 1 : -1;
  return [...wires].sort((left, right) => {
    const leftValue = wireSortValue(left, state.sortKey);
    const rightValue = wireSortValue(right, state.sortKey);
    if (leftValue < rightValue) return -1 * direction;
    if (leftValue > rightValue) return 1 * direction;
    return left.index - right.index;
  });
}

function wireSortValue(wire, key) {
  if (key === 'index') return wire.index;
  if (key === 'awg') return Number(wire.awg || 0);
  return String(wire[key] || '').toLowerCase();
}

function renderWireEndpointGroups(wire) {
  wire.endpoints.forEach((endpoint) => {
    const component = state.components.get(endpoint.component);
    const endpointLayer = document.querySelector(`.component-endpoint-layer[data-component="${cssEscape(endpoint.component)}"]`);
    if (!component || !endpointLayer) return;
    const localEndpoint = endpointToLocal(endpoint, component);
    const group = el('g', {
      class: 'wire-endpoint-group',
      'data-wire': wire.index,
      'data-net': wire.net,
      'data-node': endpoint.node,
      'data-component': endpoint.component,
    });
    group.dataset.tx = 0;
    group.dataset.ty = 0;
    group.dataset.baseTx = 0;
    group.dataset.baseTy = 0;
    group.dataset.anchorX = localEndpoint.anchor.x;
    group.dataset.anchorY = localEndpoint.anchor.y;
    group.dataset.side = endpoint.side;
    group.dataset.stubLength = endpoint.stub_length;
    group.dataset.labelGap = endpoint.label_gap;
    group.dataset.labelWidth = endpoint.label.width || Math.max(44, wire.label.length * 7.2 + 12);
    group.dataset.labelHeight = endpoint.label.height || 17;
    group.dataset.slot = endpoint.label.slot || 0;
    group.dataset.slotCount = endpoint.label.slot_count || 1;
    setNetStyle(group, wire.style);

    group.appendChild(el('path', {
      class: 'wire-stub',
      d: `M ${localEndpoint.anchor.x} ${localEndpoint.anchor.y} L ${localEndpoint.stub.x} ${localEndpoint.stub.y}`,
    }));
    group.appendChild(el('circle', {
      class: 'wire-dot',
      cx: localEndpoint.anchor.x,
      cy: localEndpoint.anchor.y,
      r: 3,
    }));

    group.dataset.labelX = localEndpoint.label.x;
    group.dataset.labelY = localEndpoint.label.y;
    const label = renderWireLabel(wire, localEndpoint);
    group.appendChild(label);
    endpointLayer.appendChild(group);
  });
}

function endpointToLocal(endpoint, component) {
  return {
    ...endpoint,
    anchor: {
      x: endpoint.anchor.x - component.baseX,
      y: endpoint.anchor.y - component.baseY,
    },
    stub: {
      x: endpoint.stub.x - component.baseX,
      y: endpoint.stub.y - component.baseY,
    },
    label: {
      ...endpoint.label,
      x: endpoint.label.x - component.baseX,
      y: endpoint.label.y - component.baseY,
      rotation: labelLocalRotation(endpoint.side, component.rotation || 0),
    },
  };
}

function renderWireLabel(wire, endpoint) {
  const label = el('g', {
    class: 'wire-label-group',
    'data-wire': wire.index,
    'data-net': wire.net,
    'data-node': endpoint.node,
    'data-component': endpoint.component,
  });
  const width = endpoint.label.width || Math.max(44, wire.label.length * 7.2 + 12);
  const height = endpoint.label.height || 17;
  const transform = endpoint.label.rotation
    ? `rotate(${endpoint.label.rotation} ${endpoint.label.x} ${endpoint.label.y})`
    : '';
  if (transform) {
    label.setAttribute('transform', transform);
  }
  label.appendChild(el('rect', {
    class: 'wire-label-bg',
    x: endpoint.label.x - width / 2,
    y: endpoint.label.y - height / 2,
    width,
    height,
    rx: 4,
    ry: 4,
  }));
  label.appendChild(textEl(wire.label, {
    class: 'wire-label-text',
    x: endpoint.label.x,
    y: endpoint.label.y,
  }));
  label.addEventListener('click', (event) => {
    event.stopPropagation();
    selectWire(String(wire.index), wire.net);
    applyHighlight();
  });
  return label;
}

function enableDrag(svg) {
  let active = null;
  svg.addEventListener('pointerdown', (event) => {
    const dragSurface = event.target.closest('.component-drag-surface');
    if (!dragSurface) return;
    const component = dragSurface.closest('.component');
    if (!component) return;
    const start = pointerToSvg(svg, event);
    active = {
      element: component,
      component: state.components.get(component.dataset.component),
      name: component.dataset.component,
      startX: start.x,
      startY: start.y,
      x: Number(component.dataset.x),
      y: Number(component.dataset.y),
      moved: false,
    };
    component.classList.add('dragging');
    component.setPointerCapture(event.pointerId);
  });
  svg.addEventListener('pointermove', (event) => {
    if (!active) return;
    const current = pointerToSvg(svg, event);
    const dx = current.x - active.startX;
    const dy = current.y - active.startY;
    if (Math.abs(dx) > 2 || Math.abs(dy) > 2) {
      active.moved = true;
    }
    const x = active.x + dx;
    const y = active.y + dy;
    active.element.dataset.x = x;
    active.element.dataset.y = y;
    active.component.x = x;
    active.component.y = y;
    updateComponentTransform(active.element, active.component);
  });
  svg.addEventListener('pointerup', () => endDrag(true));
  svg.addEventListener('pointercancel', () => endDrag(false));

  function endDrag(selectAfterDrag) {
    if (!active) return;
    active.component.x = Number(active.element.dataset.x);
    active.component.y = Number(active.element.dataset.y);
    if (active.moved) {
      active.element.dataset.ignoreClick = 'true';
    }
    active.element.classList.remove('dragging');
    if (selectAfterDrag) {
      selectComponent(active.name);
    }
    active = null;
  }
}

function enablePan(svg) {
  let activePan = null;
  svg.addEventListener('pointerdown', (event) => {
    if (event.button !== 0 || event.target.closest('.component') || event.target.closest('.wire-label-group')) return;
    activePan = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      viewBox: { ...state.viewBox },
    };
    host.classList.add('panning');
    svg.setPointerCapture(event.pointerId);
  });
  svg.addEventListener('pointermove', (event) => {
    if (!activePan) return;
    const rect = svg.getBoundingClientRect();
    const dx = ((event.clientX - activePan.startX) / Math.max(rect.width, 1)) * activePan.viewBox.width;
    const dy = ((event.clientY - activePan.startY) / Math.max(rect.height, 1)) * activePan.viewBox.height;
    state.viewBox = {
      ...activePan.viewBox,
      x: activePan.viewBox.x - dx,
      y: activePan.viewBox.y - dy,
    };
    setViewBox(svg);
  });
  svg.addEventListener('pointerup', () => endPan());
  svg.addEventListener('pointercancel', () => endPan());

  function endPan() {
    if (!activePan) return;
    host.classList.remove('panning');
    activePan = null;
  }
}

function enableZoom(svg) {
  svg.addEventListener('wheel', (event) => {
    event.preventDefault();
    if (!state.viewBox || !state.canvas) return;
    const pointer = pointerToSvg(svg, event);
    const zoomFactor = event.deltaY > 0 ? 1.12 : 0.89;
    const nextWidth = clamp(state.viewBox.width * zoomFactor, state.canvas.width / 8, state.canvas.width * 3);
    const nextHeight = clamp(state.viewBox.height * zoomFactor, state.canvas.height / 8, state.canvas.height * 3);
    const ratioX = (pointer.x - state.viewBox.x) / state.viewBox.width;
    const ratioY = (pointer.y - state.viewBox.y) / state.viewBox.height;
    state.viewBox = {
      x: pointer.x - ratioX * nextWidth,
      y: pointer.y - ratioY * nextHeight,
      width: nextWidth,
      height: nextHeight,
    };
    setViewBox(svg);
  }, { passive: false });
}

function enableTableResize() {
  if (wireTableResizer.dataset.bound === 'true') return;
  wireTableResizer.dataset.bound = 'true';
  let activeResize = null;
  wireTableResizer.addEventListener('pointerdown', (event) => {
    event.preventDefault();
    activeResize = {
      startX: event.clientX,
      width: Number.parseFloat(workspace.style.getPropertyValue('--wire-table-width'))
        || document.querySelector('.wire-table-panel').getBoundingClientRect().width
        || 420,
    };
    wireTableResizer.setPointerCapture(event.pointerId);
  });
  window.addEventListener('pointermove', (event) => {
    if (!activeResize) return;
    const nextWidth = clamp(activeResize.width - (event.clientX - activeResize.startX), 280, 900);
    workspace.style.setProperty('--wire-table-width', `${nextWidth}px`);
  });
  window.addEventListener('pointerup', () => {
    activeResize = null;
  });
  window.addEventListener('pointercancel', () => {
    activeResize = null;
  });
}

function enableContextMenu(svg) {
  svg.addEventListener('contextmenu', (event) => {
    event.preventDefault();
    const componentGroup = event.target.closest('.component');
    if (componentGroup) {
      rotateComponent(componentGroup.dataset.component);
      return;
    }
    clearSelectionState();
    applyHighlight();
  });
  host.addEventListener('contextmenu', (event) => {
    if (event.target.closest('svg')) return;
    event.preventDefault();
    clearSelectionState();
    applyHighlight();
  });
}

function rotateComponent(componentName) {
  const component = state.components.get(componentName);
  const group = document.querySelector(`.component[data-component="${cssEscape(componentName)}"]`);
  if (!component || !group) return;
  component.rotation = (Number(component.rotation || 0) + 90) % 360;
  group.dataset.rotation = component.rotation;
  group.dataset.ignoreClick = 'true';
  updateComponentTransform(group, component);
  updateComponentEndpoints(component);
}

function updateComponentTransform(group, component) {
  group.setAttribute(
    'transform',
    `translate(${component.x} ${component.y}) rotate(${component.rotation || 0} ${component.width / 2} ${component.height / 2})`,
  );
  group.dataset.x = component.x;
  group.dataset.y = component.y;
  group.dataset.rotation = component.rotation || 0;
  updateReadableComponentText(group, component.rotation || 0);
}

function updateReadableComponentText(group, rotation) {
  const normalized = ((rotation % 360) + 360) % 360;
  group.querySelectorAll('.pin-label,.component-name,.component-type').forEach((text) => {
    let x = Number(text.getAttribute('x'));
    let y = Number(text.getAttribute('y'));
    const role = text.dataset.textRole;
    if (role === 'name' || role === 'type') {
      const centerX = Number(text.dataset.centerX);
      const centerY = Number(text.dataset.centerY);
      const offset = role === 'name' ? -Number(text.getAttribute('font-size')) * 0.45 : Number(text.getAttribute('font-size')) * 1.15;
      const localOffset = inverseRotateVector(0, offset, normalized);
      x = centerX + localOffset.x;
      y = centerY + localOffset.y;
      text.setAttribute('x', x);
      text.setAttribute('y', y);
    }
    text.setAttribute('transform', `rotate(${-rotation} ${x} ${y})`);
  });
}

function inverseRotateVector(x, y, rotation) {
  if (rotation === 90) return { x: y, y: -x };
  if (rotation === 180) return { x: -x, y: -y };
  if (rotation === 270) return { x: -y, y: x };
  return { x, y };
}

function updateComponentEndpoints(component) {
  document.querySelectorAll(`.wire-endpoint-group[data-component="${cssEscape(component.name)}"]`).forEach((group) => {
    const side = rotateSide(group.dataset.side, component.rotation || 0);
    const label = {
      x: Number(group.dataset.labelX),
      y: Number(group.dataset.labelY),
      width: Number(group.dataset.labelWidth),
      height: Number(group.dataset.labelHeight),
      rotation: labelLocalRotation(side, component.rotation || 0),
    };
    setEndpointLabelGeometry(group, label);
  });
}

function setEndpointLabelGeometry(group, label) {
  const labelGroup = group.querySelector('.wire-label-group');
  const labelRect = group.querySelector('.wire-label-bg');
  const labelText = group.querySelector('.wire-label-text');
  if (label.rotation) {
    labelGroup.setAttribute('transform', `rotate(${label.rotation} ${label.x} ${label.y})`);
  } else {
    labelGroup.removeAttribute('transform');
  }
  labelRect.setAttribute('x', label.x - label.width / 2);
  labelRect.setAttribute('y', label.y - label.height / 2);
  labelRect.setAttribute('width', label.width);
  labelRect.setAttribute('height', label.height);
  labelText.setAttribute('x', label.x);
  labelText.setAttribute('y', label.y);
}

function rotatePoint(point, center, rotation) {
  const normalized = ((rotation % 360) + 360) % 360;
  const dx = point.x - center.x;
  const dy = point.y - center.y;
  if (normalized === 90) return { x: center.x - dy, y: center.y + dx };
  if (normalized === 180) return { x: center.x - dx, y: center.y - dy };
  if (normalized === 270) return { x: center.x + dy, y: center.y - dx };
  return { x: point.x, y: point.y };
}

function rotateSide(side, rotation) {
  const order = ['top', 'right', 'bottom', 'left'];
  const turns = (((rotation / 90) % 4) + 4) % 4;
  const index = order.indexOf(side);
  return order[(index + turns) % order.length] || side;
}

function sideVector(side) {
  if (side === 'left') return { x: -1, y: 0 };
  if (side === 'right') return { x: 1, y: 0 };
  if (side === 'top') return { x: 0, y: -1 };
  return { x: 0, y: 1 };
}

function fanOffset(side, slot, slotCount, spacing) {
  if (slotCount <= 1) return { x: 0, y: 0 };
  const offset = (slot - (slotCount - 1) / 2) * spacing;
  if (side === 'left' || side === 'right') return { x: 0, y: offset };
  return { x: offset, y: 0 };
}

function labelRotation(side) {
  return side === 'top' || side === 'bottom' ? 90 : 0;
}

function labelLocalRotation(screenSide, componentRotation) {
  return normalizeRotation(labelRotation(screenSide) - componentRotation);
}

function normalizeRotation(rotation) {
  let normalized = ((rotation % 360) + 360) % 360;
  if (normalized > 180) normalized -= 360;
  return normalized;
}

function pointerToSvg(svg, event) {
  const rect = svg.getBoundingClientRect();
  const viewBox = state.viewBox || {
    x: 0,
    y: 0,
    width: rect.width || 1,
    height: rect.height || 1,
  };
  return {
    x: viewBox.x + ((event.clientX - rect.left) / Math.max(rect.width, 1)) * viewBox.width,
    y: viewBox.y + ((event.clientY - rect.top) / Math.max(rect.height, 1)) * viewBox.height,
  };
}

function setViewBox(svg) {
  svg.setAttribute('viewBox', `${state.viewBox.x} ${state.viewBox.y} ${state.viewBox.width} ${state.viewBox.height}`);
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function selectWire(wireIndex, netName) {
  clearSelectionState();
  state.selectedWire = wireIndex;
  state.selectedNet = netName;
  state.selectedWires = [wireIndex];
  state.selectedNets = netName ? [netName] : [];
}

function selectPin(node) {
  clearSelectionState();
  state.selectedNode = node;
  const endpoints = [...document.querySelectorAll(`.wire-endpoint-group[data-node="${cssEscape(node)}"]`)];
  if (state.mode === 'net') {
    state.selectedNets = uniqueValues(endpoints.map((endpoint) => endpoint.dataset.net).filter(Boolean));
    state.selectedNet = state.selectedNets[0] || null;
  } else {
    state.selectedWires = uniqueValues(endpoints.map((endpoint) => endpoint.dataset.wire).filter(Boolean));
    state.selectedWire = state.selectedWires[0] || null;
  }
  applyHighlight();
}

function selectComponent(componentName) {
  clearSelectionState();
  state.selectedComponent = componentName;
  const endpoints = [...document.querySelectorAll(`.wire-endpoint-group[data-component="${cssEscape(componentName)}"]`)];
  if (state.mode === 'net') {
    state.selectedNets = uniqueValues(endpoints.map((endpoint) => endpoint.dataset.net).filter(Boolean));
    state.selectedNet = state.selectedNets[0] || null;
  } else {
    state.selectedWires = uniqueValues(endpoints.map((endpoint) => endpoint.dataset.wire).filter(Boolean));
    state.selectedWire = state.selectedWires[0] || null;
  }
  applyHighlight();
}

function selectDiagnosticNodes(nodes) {
  clearSelectionState();
  state.diagnosticNodes = nodes;
  applyHighlight();
}

function clearSelectionState() {
  state.selectedWire = null;
  state.selectedNet = null;
  state.selectedWires = [];
  state.selectedNets = [];
  state.selectedNode = null;
  state.selectedComponent = null;
  state.diagnosticNodes = [];
  state.diagnosticComponents = [];
}

function uniqueValues(values) {
  return [...new Set(values)];
}

function applyHighlight() {
  const selectedWires = new Set(state.selectedWires);
  const selectedNets = new Set(state.selectedNets);
  const hasSelection = state.mode === 'net'
    ? selectedNets.size > 0 || Boolean(state.selectedComponent)
    : selectedWires.size > 0 || Boolean(state.selectedComponent);
  document.querySelectorAll('.dimmed,.selected').forEach((item) => {
    item.classList.remove('dimmed', 'selected');
  });
  document.querySelectorAll('.diagnostic-selected').forEach((item) => {
    item.classList.remove('diagnostic-selected');
  });
  document.querySelectorAll('.pin-box').forEach((pin) => {
    pin.style.removeProperty('--net-color');
  });
  state.diagnosticNodes.forEach((node) => {
    const pin = document.querySelector(`.pin-box[data-node="${cssEscape(node)}"]`);
    if (pin) pin.classList.add('diagnostic-selected');
  });
  state.diagnosticComponents.forEach((componentName) => {
    const component = document.querySelector(`.component[data-component="${cssEscape(componentName)}"]`);
    if (component) component.classList.add('diagnostic-selected');
  });
  if (!hasSelection) return;

  document.querySelectorAll('.wire-endpoint-group').forEach((group) => {
    const match = state.mode === 'net'
      ? selectedNets.has(group.dataset.net)
      : selectedWires.has(group.dataset.wire);
    group.classList.toggle('selected', match);
    group.classList.toggle('dimmed', !match);
  });
  document.querySelectorAll('.wire-table-row').forEach((row) => {
    const match = state.mode === 'net'
      ? selectedNets.has(row.dataset.net)
      : selectedWires.has(row.dataset.wire);
    row.classList.toggle('selected', match);
    row.classList.toggle('dimmed', !match);
  });
  document.querySelectorAll('.component').forEach((component) => {
    component.classList.toggle('selected', component.dataset.component === state.selectedComponent);
  });
  document.querySelectorAll('.pin-box').forEach((pin) => {
    const endpoint = document.querySelector(`.wire-endpoint-group.selected[data-node="${cssEscape(pin.dataset.node)}"]`);
    pin.classList.toggle('selected', Boolean(endpoint));
    pin.classList.toggle('dimmed', !endpoint);
    if (endpoint) {
      pin.style.setProperty('--net-color', getComputedStyle(endpoint).getPropertyValue('--net-color'));
    }
  });
}

function setNetStyle(element, style) {
  element.style.setProperty('--net-color', style.color || '#475569');
  const lineWeight = Number(style.line_weight || 1.6);
  element.style.setProperty('--net-weight', lineWeight);
  element.style.setProperty('--net-selected-weight', lineWeight + 2);
  element.style.setProperty('--net-dasharray', dashArray(style.line_style));
}

function dashArray(lineStyle) {
  if (lineStyle === 'dashed') return '6 4';
  if (lineStyle === 'dotted') return '1 4';
  return 'none';
}

function el(name, attrs = {}) {
  const node = document.createElementNS(NS, name);
  Object.entries(attrs).forEach(([key, value]) => {
    if (value !== undefined && value !== null) node.setAttribute(key, value);
  });
  return node;
}

function textEl(value, attrs = {}) {
  const node = el('text', attrs);
  node.textContent = value;
  return node;
}

function fitTextSize(text, preferredSize, maxWidth, minimumSize) {
  const estimatedWidth = Math.max(1, String(text).length * preferredSize * 0.58);
  if (estimatedWidth <= maxWidth) return preferredSize;
  return Math.max(minimumSize, preferredSize * (maxWidth / estimatedWidth));
}

function cssEscape(value) {
  if (window.CSS && CSS.escape) return CSS.escape(value);
  return String(value).replace(/"/g, '\\"');
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (character) => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;',
  }[character]));
}
"""
