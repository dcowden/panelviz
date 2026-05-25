const NS = 'http://www.w3.org/2000/svg';

const state = {
  mode: 'wire',
  selectedWire: null,
  selectedNet: null,
  selectedWires: [],
  selectedNets: [],
  selectedNode: null,
  selectedComponent: null,
  selectedComponents: [],
  viewBox: null,
  canvas: null,
  scene: null,
  data: null,
  components: new Map(),
  tableMode: 'combined',
  sortKey: 'index',
  sortDirection: 'asc',
  tagFilter: '',
  diagnosticNodes: [],
  diagnosticComponents: [],
};

const host = document.getElementById('canvas-host');
const workspace = document.querySelector('.workspace');
const statusEl = document.getElementById('status');
const wireTableHead = document.getElementById('wire-table-head');
const wireTableBody = document.getElementById('wire-table-body');
const wireTableCount = document.getElementById('wire-table-count');
const toggleWireColumnsButton = document.getElementById('toggle-wire-columns');
const toggleWireTableButton = document.getElementById('toggle-wire-table');
const toggleReferenceGridButton = document.getElementById('toggle-reference-grid');
const wireTableResizer = document.getElementById('wire-table-resizer');
const wireTagFilterInput = document.getElementById('wire-tag-filter');
const wireTagOptions = document.getElementById('wire-tag-options');

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

if (wireTagFilterInput) {
  wireTagFilterInput.addEventListener('input', () => {
    state.tagFilter = wireTagFilterInput.value.trim().toLowerCase();
    renderWireTable(state.data.wires);
    applyHighlight();
  });
}

toggleReferenceGridButton.addEventListener('click', () => {
  const svg = host.querySelector('svg');
  const layer = host.querySelector('.reference-grid-layer');
  const visible = !(layer?.classList.contains('visible') ?? false);
  updateReferenceGrid(svg, visible);
});

fetch('panel-data.json', { cache: 'no-store' })
  .then((response) => response.json().then((data) => {
    if (!response.ok) throw new Error(data.error || `${response.status} ${response.statusText}`);
    return data;
  }))
  .then((data) => render(data))
  .catch((error) => {
    statusEl.textContent = `Could not load panel-data.json: ${error}`;
  });

function render(data, options = {}) {
  host.textContent = '';
  if (data.error) {
    statusEl.textContent = `Could not load panel-data.json: ${data.error}`;
    return;
  }
  const preservedViewBox = options.preserveViewBox && state.viewBox ? { ...state.viewBox } : null;
  state.data = data;
  state.components = new Map(data.components.map((component) => [component.name, {
    ...component,
    baseX: component.x,
    baseY: component.y,
    endpointOriginX: component.x,
    endpointOriginY: component.y,
    rotation: component.rotation || 0,
  }]));
  state.canvas = normalizeBounds(data.canvas);
  state.scene = normalizeBounds(data.scene || data.canvas);
  state.viewBox = preservedViewBox || fitBoundsToViewport(state.scene, 72);
  const svg = createCanvas(state.canvas);
  const layers = createSceneLayers(svg);

  data.components.forEach((component) => renderComponent(layers.physical, component));
  data.wires.forEach((wire) => renderWireEndpointGroups(wire, layers.labels));
  sortEndpointLayers();
  state.scene = renderedSceneBounds(svg, state.scene);
  updateReferenceGrid(svg, false);
  if (!preservedViewBox) {
    state.viewBox = fitBoundsToViewport(state.scene, 72);
  }
  setViewBox(svg);
  populateTagFilterOptions(data.wires);
  renderWireTable(data.wires);

  enableDrag(svg);
  enableMarqueeSelect(svg);
  enablePan(svg);
  enableZoom(svg);
  enableContextMenu(svg);
  enableTableResize();
  statusEl.textContent = `${data.components.length} components, ${data.wires.length} wires. SVG.js ${window.SVG ? 'loaded' : 'fallback renderer active'}.`;
}

window.PanelVizRender = render;
window.PanelVizRefreshData = refreshData;

function refreshData(data, options = {}) {
  if (data.error) {
    statusEl.textContent = `Could not load panel-data.json: ${data.error}`;
    return;
  }
  const componentNames = new Set(data.components.map((component) => component.name));
  const existingNames = new Set([...state.components.keys()]);
  const componentSetChanged = componentNames.size !== existingNames.size
    || [...componentNames].some((name) => !existingNames.has(name));
  if (!host.querySelector('svg') || componentSetChanged) {
    render(data, options);
    return;
  }

  state.data = data;
  state.canvas = normalizeBounds(data.canvas);
  state.scene = normalizeBounds(data.scene || data.canvas);
  data.components.forEach((component) => {
    const existing = state.components.get(component.name) || {};
    state.components.set(component.name, {
      ...component,
      x: existing.x ?? component.x,
      y: existing.y ?? component.y,
      baseX: existing.baseX ?? component.x,
      baseY: existing.baseY ?? component.y,
      endpointOriginX: component.x,
      endpointOriginY: component.y,
      rotation: existing.rotation ?? component.rotation ?? 0,
    });
  });

  const labelsLayer = host.querySelector('.wire-label-layer');
  if (labelsLayer) labelsLayer.textContent = '';
  data.wires.forEach((wire) => renderWireEndpointGroups(wire, labelsLayer));
  const svg = host.querySelector('svg');
  const oldGrid = host.querySelector('.reference-grid-layer');
  const gridVisible = oldGrid?.classList.contains('visible') ?? false;
  sortEndpointLayers();
  state.scene = renderedSceneBounds(svg, state.scene);
  updateReferenceGrid(svg, gridVisible);
  populateTagFilterOptions(data.wires);
  renderWireTable(data.wires);
  applyHighlight();
  statusEl.textContent = `${data.components.length} components, ${data.wires.length} wires. SVG.js ${window.SVG ? 'loaded' : 'fallback renderer active'}.`;
}

function createCanvas(canvas) {
  if (window.SVG) {
    const draw = SVG().addTo(host).viewbox(canvas.x, canvas.y, canvas.width, canvas.height).attr({
      role: 'img',
      'aria-label': 'PanelViz interactive wiring viewer',
    });
    return draw.node;
  }
  const svg = el('svg', {
    viewBox: `${canvas.x} ${canvas.y} ${canvas.width} ${canvas.height}`,
    role: 'img',
    'aria-label': 'PanelViz interactive wiring viewer',
  });
  host.appendChild(svg);
  return svg;
}

function createSceneLayers(svg) {
  const physical = el('g', { class: 'scene-layer physical-layer components-layer' });
  const labels = el('g', { class: 'scene-layer wire-label-layer' });
  const interaction = el('g', { class: 'scene-layer interaction-layer' });
  const debug = el('g', { class: 'scene-layer debug-layer' });
  svg.appendChild(physical);
  svg.appendChild(labels);
  svg.appendChild(interaction);
  svg.appendChild(debug);
  return { physical, labels, interaction, debug };
}

function updateReferenceGrid(svg, visible = false) {
  const debugLayer = host.querySelector('.debug-layer');
  if (!debugLayer) return;
  debugLayer.textContent = '';
  if (!svg) return;
  const bounds = renderedSceneBounds(svg, state.scene || state.canvas);
  const grid = referenceGridFromBounds(bounds, state.data?.reference_grid);
  if (state.data) state.data.reference_grid = grid;
  applyWireReferences(grid);
  renderReferenceGrid(debugLayer, grid, visible);
  if (state.data && wireTableBody.children.length) renderWireTable(state.data.wires);
}

function referenceGridFromBounds(bounds, fallbackGrid = {}) {
  const normalized = normalizeBounds(bounds);
  const columns = Math.max(8, Math.min(80, Number(fallbackGrid?.columns) || Math.ceil(normalized.width / 90)));
  const rows = Math.max(4, Math.min(26, Number(fallbackGrid?.rows) || Math.ceil(normalized.height / 90)));
  const verticals = [];
  const horizontals = [];
  for (let index = 0; index <= columns; index += 1) {
    verticals.push(normalized.x + (normalized.width * index) / columns);
  }
  for (let index = 0; index <= rows; index += 1) {
    horizontals.push(normalized.y + (normalized.height * index) / rows);
  }
  const labels = [];
  for (let row = 0; row < rows; row += 1) {
    const rowLabel = String.fromCharCode('A'.charCodeAt(0) + row);
    for (let col = 0; col < columns; col += 1) {
      labels.push({
        ref: `${rowLabel}${col + 1}`,
        x: (verticals[col] + verticals[col + 1]) / 2,
        y: (horizontals[row] + horizontals[row + 1]) / 2,
      });
    }
  }
  return {
    columns: columns || fallbackGrid.columns || 8,
    rows: rows || fallbackGrid.rows || 4,
    verticals,
    horizontals,
    labels,
  };
}

function renderReferenceGrid(parentLayer, grid, visible = false) {
  if (!parentLayer || !grid || !grid.verticals?.length || !grid.horizontals?.length) return;
  const gridGroup = el('g', {
    class: `reference-grid-layer${visible ? ' visible' : ''}`,
    'data-columns': grid.columns,
    'data-rows': grid.rows,
  });
  const minY = grid.horizontals[0];
  const maxY = grid.horizontals[grid.horizontals.length - 1];
  const minX = grid.verticals[0];
  const maxX = grid.verticals[grid.verticals.length - 1];
  grid.verticals.forEach((x) => {
    gridGroup.appendChild(el('line', {
      class: 'reference-grid-line',
      x1: x,
      y1: minY,
      x2: x,
      y2: maxY,
    }));
  });
  grid.horizontals.forEach((y) => {
    gridGroup.appendChild(el('line', {
      class: 'reference-grid-line',
      x1: minX,
      y1: y,
      x2: maxX,
      y2: y,
    }));
  });
  grid.labels.forEach((label) => {
    gridGroup.appendChild(textEl(label.ref, {
      class: 'reference-grid-label',
      x: label.x,
      y: label.y,
    }));
  });
  parentLayer.appendChild(gridGroup);
  toggleReferenceGridButton.setAttribute('aria-pressed', String(visible));
}

function applyWireReferences(grid) {
  if (!state.data?.wires || !grid?.verticals?.length || !grid?.horizontals?.length) return;
  state.data.wires.forEach((wire) => {
    const fromAnchor = renderedEndpointAnchor(wire, wire.endpoints?.[0]);
    const toAnchor = renderedEndpointAnchor(wire, wire.endpoints?.[1]);
    wire.from_ref = fromAnchor ? referenceForPoint(grid, fromAnchor.x, fromAnchor.y) : '';
    wire.to_ref = toAnchor ? referenceForPoint(grid, toAnchor.x, toAnchor.y) : '';
  });
}

function renderedEndpointAnchor(wire, endpoint) {
  if (!endpoint) return null;
  const component = state.components.get(endpoint.component);
  const pin = component?.pins?.find((item) => item.node === endpoint.node);
  if (component && pin) {
    return transformComponentLocalPoint(component, pinBoundaryPoint(pin));
  }
  return endpoint.anchor || null;
}

function transformComponentLocalPoint(component, point) {
  const rotated = rotatePoint(
    point,
    { x: component.width / 2, y: component.height / 2 },
    Number(component.rotation || 0),
  );
  return {
    x: Number(component.x) + rotated.x,
    y: Number(component.y) + rotated.y,
  };
}

function referenceForPoint(grid, x, y) {
  let col = 0;
  while (col + 1 < grid.verticals.length && Number(x) >= grid.verticals[col + 1]) col += 1;
  let row = 0;
  while (row + 1 < grid.horizontals.length && Number(y) >= grid.horizontals[row + 1]) row += 1;
  col = Math.max(0, Math.min(grid.columns - 1, col));
  row = Math.max(0, Math.min(grid.rows - 1, row));
  return `${String.fromCharCode('A'.charCodeAt(0) + row)}${col + 1}`;
}

function renderComponent(layer, component) {
  const storedComponent = state.components.get(component.name);
  const group = el('g', {
    class: 'component',
    'data-component': component.name,
  });
  group.dataset.x = component.x;
  group.dataset.y = component.y;
  group.dataset.rotation = component.rotation || 0;

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
  const preferredNameSize = Math.max(component.font.name * 2.2, Math.min(22, Math.max(12, component.center.height * 0.16)));
  const thinCenterText = centerTextOrientation(component, component.rotation || 0, component.name, preferredNameSize) === 'vertical';
  const centerFitWidth = centerTextFitWidth(component, component.rotation || 0, thinCenterText ? 'vertical' : 'horizontal');
  const fittedNameSize = fitTextSize(component.name, preferredNameSize, centerFitWidth, 8);
  const preferredTypeSize = Math.max(5, fittedNameSize * 0.62);
  const componentSubtitle = componentSubtitleText(component);
  const typeFontSize = Math.min(fittedNameSize * 0.72, fitTextSize(componentSubtitle, preferredTypeSize, centerFitWidth, 4.5));
  group.appendChild(textEl(component.name, {
    class: 'component-name',
    'data-text-role': 'name',
    'data-preferred-size': preferredNameSize,
    'data-center-orientation': thinCenterText ? 'vertical' : 'horizontal',
    'data-center-x': centerX,
    'data-center-y': centerY,
    x: centerX,
    y: centerY - typeFontSize * 0.55,
    'font-size': fittedNameSize,
  }));
  group.appendChild(textEl(componentSubtitle, {
    class: 'component-type',
    'data-text-role': 'type',
    'data-preferred-size': preferredTypeSize,
    'data-center-orientation': thinCenterText ? 'vertical' : 'horizontal',
    'data-center-x': centerX,
    'data-center-y': centerY,
    x: centerX,
    y: centerY + fittedNameSize * 0.75,
    'font-size': typeFontSize,
  }));

  component.pins.forEach((pin) => {
    const terminalFontSize = terminalTextFontSize(component, pin);
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
    const pinLabel = textEl(pin.pin, {
      class: 'pin-label',
      'data-side': pin.side,
      x: pin.x + pin.width / 2,
      y: pin.y + pin.height / 2,
      'font-size': terminalFontSize,
    });
    group.appendChild(pinLabel);
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
  const markerLayer = el('g', { class: 'component-marker-layer' });
  component.pins.forEach((pin) => renderNoConnectMarker(markerLayer, pin));
  group.appendChild(markerLayer);
  updateComponentTransform(group, storedComponent);
  layer.appendChild(group);
}

function terminalTextFontSize(component, pin) {
  const terminalDepth = Math.max(pin.width, pin.height);
  return Math.max(component.font.pin, Math.min(4.2, terminalDepth * 0.32));
}

function renderNoConnectMarker(group, pin) {
  if (!pin.no_connect) return;
  const vector = sideVector(pin.side);
  const anchor = pinBoundaryPoint(pin);
  const stubLength = 20;
  const markerGap = 5;
  const stub = {
    x: anchor.x + vector.x * stubLength,
    y: anchor.y + vector.y * stubLength,
  };
  const center = {
    x: stub.x + vector.x * markerGap,
    y: stub.y + vector.y * markerGap,
  };
  const terminalPitch = Math.min(pin.width, pin.height);
  const size = Math.max(1.8, terminalPitch * 0.38);
  group.appendChild(el('path', {
    class: 'no-connect-stub',
    'data-node': pin.node,
    d: `M ${anchor.x} ${anchor.y} L ${stub.x} ${stub.y}`,
  }));
  group.appendChild(el('circle', {
    class: 'no-connect-dot',
    'data-node': pin.node,
    cx: anchor.x,
    cy: anchor.y,
    r: Math.max(0.8, Math.min(1.25, Math.max(pin.width, pin.height) * 0.16)),
  }));
  [
    [center.x - size, center.y - size, center.x + size, center.y + size],
    [center.x + size, center.y - size, center.x - size, center.y + size],
  ].forEach(([x1, y1, x2, y2]) => {
    group.appendChild(el('line', {
      class: 'no-connect-x no-connect-marker',
      'data-node': pin.node,
      x1,
      y1,
      x2,
      y2,
    }));
  });
}

function pinBoundaryPoint(pin) {
  if (pin.side === 'left') return { x: pin.x, y: pin.y + pin.height / 2 };
  if (pin.side === 'right') return { x: pin.x + pin.width, y: pin.y + pin.height / 2 };
  if (pin.side === 'top') return { x: pin.x + pin.width / 2, y: pin.y };
  return { x: pin.x + pin.width / 2, y: pin.y + pin.height };
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
  const visibleWires = sortedWires(wires);
  updateWireTableCount(visibleWires.length, wires.length);
  visibleWires.forEach((wire) => {
    const row = document.createElement('tr');
    row.className = 'wire-table-row';
    row.dataset.wire = String(wire.index);
    row.dataset.net = wire.net;
    row.dataset.tags = wire.tags || '';
    setNetStyle(row, wire.style);
    row.innerHTML = state.tableMode === 'combined'
      ? `
        <td><span class="wire-chip">${escapeHtml(wire.label)}</span></td>
        <td>${escapeHtml(wire.from)}</td>
        <td>${escapeHtml(wire.to)}</td>
        <td>${escapeHtml(wire.net)}</td>
        <td>${escapeHtml(wire.awg)}</td>
        <td>${escapeHtml(wire.tags || '')}</td>
        <td>${escapeHtml(wire.from_ref || '')}</td>
        <td>${escapeHtml(wire.to_ref || '')}</td>
      `
      : `
        <td><span class="wire-chip">${escapeHtml(wire.label)}</span></td>
        <td>${escapeHtml(wire.from_component)}</td>
        <td>${escapeHtml(wire.from_pin)}</td>
        <td>${escapeHtml(wire.from_ref || '')}</td>
        <td>${escapeHtml(wire.to_component)}</td>
        <td>${escapeHtml(wire.to_pin)}</td>
        <td>${escapeHtml(wire.to_ref || '')}</td>
        <td>${escapeHtml(wire.net)}</td>
        <td>${escapeHtml(wire.awg)}</td>
        <td>${escapeHtml(wire.tags || '')}</td>
      `;
    row.addEventListener('click', () => {
      selectWire(String(wire.index), wire.net);
      applyHighlight();
    });
    wireTableBody.appendChild(row);
  });
}

function updateWireTableCount(visibleCount, totalCount) {
  if (!wireTableCount) return;
  const visible = Number(visibleCount) || 0;
  const total = Number(totalCount) || 0;
  wireTableCount.textContent = visible === total ? `${total} wires` : `${visible} of ${total} wires`;
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
        ${sortableHeader('Tags', 'tags', marker('tags'))}
        ${sortableHeader('From Ref', 'from_ref', marker('from_ref'))}
        ${sortableHeader('To Ref', 'to_ref', marker('to_ref'))}
      </tr>
    `;
  } else {
    wireTableHead.innerHTML = `
      <tr>
        <th rowspan="2">${sortButton('Wire', 'label', marker('label'))}</th>
        <th colspan="3">From</th>
        <th colspan="3">To</th>
        <th rowspan="2">${sortButton('Net', 'net', marker('net'))}</th>
        <th rowspan="2">${sortButton('AWG', 'awg', marker('awg'))}</th>
        <th rowspan="2">${sortButton('Tags', 'tags', marker('tags'))}</th>
      </tr>
      <tr>
        ${sortableHeader('Component', 'from_component', marker('from_component'))}
        ${sortableHeader('Terminal', 'from_pin', marker('from_pin'))}
        ${sortableHeader('Ref', 'from_ref', marker('from_ref'))}
        ${sortableHeader('Component', 'to_component', marker('to_component'))}
        ${sortableHeader('Terminal', 'to_pin', marker('to_pin'))}
        ${sortableHeader('Ref', 'to_ref', marker('to_ref'))}
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
  return filterWiresByTag(wires).sort((left, right) => {
    const leftValue = wireSortValue(left, state.sortKey);
    const rightValue = wireSortValue(right, state.sortKey);
    if (leftValue < rightValue) return -1 * direction;
    if (leftValue > rightValue) return 1 * direction;
    return left.index - right.index;
  });
}

function filterWiresByTag(wires) {
  if (!state.tagFilter) return [...wires];
  return wires.filter((wire) => wireTags(wire).some((tag) => tag.toLowerCase() === state.tagFilter));
}

function wireTags(wire) {
  return String(wire.tags || '')
    .split(',')
    .map((tag) => tag.trim())
    .filter(Boolean);
}

function populateTagFilterOptions(wires) {
  if (!wireTagOptions) return;
  const tags = [...new Set(wires.flatMap(wireTags))].sort((left, right) => left.localeCompare(right));
  wireTagOptions.textContent = '';
  tags.forEach((tag) => {
    const option = document.createElement('option');
    option.value = tag;
    wireTagOptions.appendChild(option);
  });
}

function componentSubtitleText(component) {
  if (Array.isArray(component.tags) && component.tags.length) return component.tags.join(', ');
  return component.type || '';
}

function wireSortValue(wire, key) {
  if (key === 'index') return wire.index;
  if (key === 'awg') return Number(wire.awg || 0);
  return String(wire[key] || '').toLowerCase();
}

function renderWireEndpointGroups(wire, endpointLayer = host.querySelector('.wire-label-layer')) {
  wire.endpoints.forEach((endpoint) => {
    const component = state.components.get(endpoint.component);
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
    group.dataset.stubDistance = localEndpoint.stub_distance || endpoint.stub_distance || endpoint.stub_length;
    group.dataset.labelGap = endpoint.label_gap;
    group.dataset.labelWidth = endpoint.label.width || Math.max(8, wire.label.length * 4 + 1.5);
    group.dataset.labelHeight = endpoint.label.height || 17;
    group.dataset.slot = endpoint.label.slot || 0;
    group.dataset.slotCount = endpoint.label.slot_count || 1;
    group.setAttribute('transform', componentTransform(component));
    setNetStyle(group, wire.style);

    group.appendChild(el('path', {
      class: 'wire-stub',
      d: `M ${localEndpoint.anchor.x} ${localEndpoint.anchor.y} L ${localEndpoint.stub.x} ${localEndpoint.stub.y}`,
    }));
    group.appendChild(el('circle', {
      class: 'wire-dot',
      cx: localEndpoint.anchor.x,
      cy: localEndpoint.anchor.y,
      r: localEndpoint.dot_radius || endpoint.dot_radius || 1.15,
    }));

    group.dataset.labelX = localEndpoint.label.x;
    group.dataset.labelY = localEndpoint.label.y;
    const label = renderWireLabel(wire, localEndpoint);
    group.appendChild(label);
    endpointLayer.appendChild(group);
  });
}

function sortEndpointLayers() {
  const layer = host.querySelector('.wire-label-layer');
  if (!layer) return;
  [...layer.querySelectorAll('.wire-endpoint-group')]
    .sort((left, right) => Number(right.dataset.slot || 0) - Number(left.dataset.slot || 0))
    .forEach((group) => layer.appendChild(group));
}

function endpointToLocal(endpoint, component) {
  const pin = component.pins.find((item) => item.node === endpoint.node);
  if (!pin) {
    return absoluteEndpointToLocal(endpoint, component);
  }
  const slot = Number(endpoint.label.slot || 0);
  const vector = sideVector(endpoint.side);
  const anchor = pinBoundaryPoint(pin);
  const stubLength = Number(endpoint.stub_length || 0);
  const labelWidth = Number(endpoint.label.width || 44);
  const labelGap = Number(endpoint.label_gap || 0);
  const stubDistance = stubLength + slot * (labelWidth + stubLength);
  const labelOffset = labelGap + labelWidth / 2;
  const stub = {
    x: anchor.x + vector.x * stubDistance,
    y: anchor.y + vector.y * stubDistance,
  };
  return {
    ...endpoint,
    anchor,
    stub,
    stub_distance: stubDistance,
    label: {
      ...endpoint.label,
      x: stub.x + vector.x * labelOffset,
      y: stub.y + vector.y * labelOffset,
      rotation: readableLabelLocalRotation(endpoint.side, component.rotation || 0),
    },
  };
}

function absoluteEndpointToLocal(endpoint, component) {
  const originX = component.endpointOriginX ?? component.x;
  const originY = component.endpointOriginY ?? component.y;
  return {
    ...endpoint,
    anchor: {
      x: endpoint.anchor.x - originX,
      y: endpoint.anchor.y - originY,
    },
    stub: {
      x: endpoint.stub.x - originX,
      y: endpoint.stub.y - originY,
    },
    label: {
      ...endpoint.label,
      x: endpoint.label.x - originX,
      y: endpoint.label.y - originY,
      rotation: readableLabelLocalRotation(endpoint.side, component.rotation || 0),
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
  const width = endpoint.label.width || Math.max(8, wire.label.length * 4 + 1.5);
  const height = endpoint.label.height || 17;
  const cornerRadius = endpoint.label.corner_radius || 2;
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
    rx: cornerRadius,
    ry: cornerRadius,
  }));
  label.appendChild(textEl(wire.label, {
    class: 'wire-label-text',
    x: endpoint.label.x,
    y: endpoint.label.y,
    'font-size': endpoint.label.font_size || 5,
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
    const names = dragSelectionNames(component.dataset.component);
    const items = names
      .map((name) => {
        const element = document.querySelector(`.component[data-component="${cssEscape(name)}"]`);
        const model = state.components.get(name);
        if (!element || !model) return null;
        return {
          element,
          component: model,
          name,
          x: Number(element.dataset.x),
          y: Number(element.dataset.y),
        };
      })
      .filter(Boolean);
    active = {
      items,
      name: component.dataset.component,
      names,
      startX: start.x,
      startY: start.y,
      moved: false,
    };
    items.forEach((item) => item.element.classList.add('dragging'));
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
    active.items.forEach((item) => {
      const x = item.x + dx;
      const y = item.y + dy;
      item.element.dataset.x = x;
      item.element.dataset.y = y;
      item.component.x = x;
      item.component.y = y;
      updateComponentTransform(item.element, item.component);
      updateComponentEndpoints(item.component);
    });
  });
  svg.addEventListener('pointerup', () => endDrag(true));
  svg.addEventListener('pointercancel', () => endDrag(false));

  function endDrag(selectAfterDrag) {
    if (!active) return;
    active.items.forEach((item) => {
      item.component.x = Number(item.element.dataset.x);
      item.component.y = Number(item.element.dataset.y);
      if (active.moved) {
        item.element.dataset.ignoreClick = 'true';
      }
      item.element.classList.remove('dragging');
    });
    if (selectAfterDrag) {
      if (active.names.length > 1) {
        setComponentGroupSelection(active.names);
      } else {
        selectComponent(active.name);
      }
    }
    active.items.forEach((item) => dispatchComponentLayout(item.name, item.component));
    state.scene = renderedSceneBounds(svg, state.scene);
    updateReferenceGrid(svg, host.querySelector('.reference-grid-layer')?.classList.contains('visible') ?? false);
    active = null;
  }
}

function dragSelectionNames(componentName) {
  if (state.selectedComponents.includes(componentName)) {
    return [...state.selectedComponents];
  }
  return [componentName];
}

function enableMarqueeSelect(svg) {
  let activeMarquee = null;
  svg.addEventListener('pointerdown', (event) => {
    if (event.button !== 0 || !event.shiftKey || event.target.closest('.component') || event.target.closest('.wire-label-group')) return;
    event.preventDefault();
    event.stopPropagation();
    const start = pointerToSvg(svg, event);
    const rect = el('rect', {
      class: 'selection-marquee',
      x: start.x,
      y: start.y,
      width: 0,
      height: 0,
    });
    const interactionLayer = svg.querySelector('.interaction-layer') || svg;
    interactionLayer.appendChild(rect);
    activeMarquee = {
      pointerId: event.pointerId,
      start,
      rect,
    };
    svg.setPointerCapture(event.pointerId);
  });
  svg.addEventListener('pointermove', (event) => {
    if (!activeMarquee) return;
    const current = pointerToSvg(svg, event);
    updateMarqueeRect(activeMarquee.rect, activeMarquee.start, current);
  });
  svg.addEventListener('pointerup', () => endMarquee(true));
  svg.addEventListener('pointercancel', () => endMarquee(false));

  function endMarquee(selectComponents) {
    if (!activeMarquee) return;
    const bounds = normalizedRect(activeMarquee.rect);
    activeMarquee.rect.remove();
    activeMarquee = null;
    if (!selectComponents) return;
    const names = [...state.components.values()]
      .filter((component) => rectsIntersect(bounds, componentBounds(component)))
      .map((component) => component.name);
    setComponentGroupSelection(names);
  }
}

function updateMarqueeRect(rect, start, current) {
  const x = Math.min(start.x, current.x);
  const y = Math.min(start.y, current.y);
  const width = Math.abs(current.x - start.x);
  const height = Math.abs(current.y - start.y);
  rect.setAttribute('x', x);
  rect.setAttribute('y', y);
  rect.setAttribute('width', width);
  rect.setAttribute('height', height);
}

function normalizedRect(rect) {
  return {
    x: Number(rect.getAttribute('x')),
    y: Number(rect.getAttribute('y')),
    width: Number(rect.getAttribute('width')),
    height: Number(rect.getAttribute('height')),
  };
}

function componentBounds(component) {
  return {
    x: component.x,
    y: component.y,
    width: component.width,
    height: component.height,
  };
}

function rectsIntersect(left, right) {
  return left.x <= right.x + right.width
    && left.x + left.width >= right.x
    && left.y <= right.y + right.height
    && left.y + left.height >= right.y;
}

function enablePan(svg) {
  let activePan = null;
  svg.addEventListener('pointerdown', (event) => {
    if (event.button !== 0 || event.shiftKey || event.target.closest('.component') || event.target.closest('.wire-label-group')) return;
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
    if (!state.viewBox || !state.canvas || !state.scene) return;
    state.scene = renderedSceneBounds(svg, state.scene);
    const pointer = pointerToSvg(svg, event);
    const zoomFactor = event.deltaY > 0 ? 1.12 : 0.89;
    const fitBox = fitBoundsToViewport(state.scene, 96);
    const aspect = state.viewBox.height / Math.max(state.viewBox.width, 1);
    const minWidth = Math.max(24, fitBox.width / 80);
    const maxWidth = fitBox.width * 1.15;
    const nextWidth = clamp(state.viewBox.width * zoomFactor, minWidth, maxWidth);
    const nextHeight = nextWidth * aspect;
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
  dispatchComponentLayout(componentName, component);
  updateReferenceGrid(host.querySelector('svg'), host.querySelector('.reference-grid-layer')?.classList.contains('visible') ?? false);
}

function dispatchComponentLayout(componentName, component) {
  document.dispatchEvent(new CustomEvent('panelviz:component-layout', {
    detail: {
      component: componentName,
      x: Number(component.x),
      y: Number(component.y),
      rotation: Number(component.rotation || 0),
    },
  }));
}

function updateComponentTransform(group, component) {
  group.setAttribute('transform', componentTransform(component));
  group.dataset.x = component.x;
  group.dataset.y = component.y;
  group.dataset.rotation = component.rotation || 0;
  updateReadableComponentText(group, component.rotation || 0);
}

function componentTransform(component) {
  return `translate(${component.x} ${component.y}) rotate(${component.rotation || 0} ${component.width / 2} ${component.height / 2})`;
}

function updateReadableComponentText(group, rotation) {
  const normalized = ((rotation % 360) + 360) % 360;
  updateCenterTextMetrics(group, rotation);
  group.querySelectorAll('.pin-label,.component-name,.component-type').forEach((text) => {
    let x = Number(text.getAttribute('x'));
    let y = Number(text.getAttribute('y'));
    const role = text.dataset.textRole;
    if (role === 'name' || role === 'type') {
      const centerX = Number(text.dataset.centerX);
      const centerY = Number(text.dataset.centerY);
      const centerOrientation = text.dataset.centerOrientation === 'vertical' ? 'vertical' : 'horizontal';
      const offsetMagnitude = role === 'name' ? -Number(text.getAttribute('font-size')) * 0.45 : Number(text.getAttribute('font-size')) * 1.15;
      const offsetVector = centerOrientation === 'vertical'
        ? { x: offsetMagnitude, y: 0 }
        : { x: 0, y: offsetMagnitude };
      const localOffset = inverseRotateVector(offsetVector.x, offsetVector.y, normalized);
      x = centerX + localOffset.x;
      y = centerY + localOffset.y;
      text.setAttribute('x', x);
      text.setAttribute('y', y);
    }
    const textRotation = role === 'name' || role === 'type'
      ? readableCenterTextLocalRotation(text.dataset.centerOrientation, rotation)
      : readableLabelLocalRotation(text.dataset.side, rotation);
    text.setAttribute('transform', `rotate(${textRotation} ${x} ${y})`);
  });
}

function updateCenterTextMetrics(group, rotation) {
  const component = state.components.get(group.dataset.component);
  if (!component) return;
  const nameText = group.querySelector('.component-name');
  const typeText = group.querySelector('.component-type');
  if (!nameText || !typeText) return;
  const preferredNameSize = Number(nameText.dataset.preferredSize || nameText.getAttribute('font-size') || component.font.name || 10);
  const centerOrientation = centerTextOrientation(component, rotation, nameText.textContent, preferredNameSize);
  const fitWidth = centerTextFitWidth(component, rotation, centerOrientation);
  const fittedNameSize = fitTextSize(nameText.textContent, preferredNameSize, fitWidth, 8);
  const preferredTypeSize = Math.max(5, fittedNameSize * 0.62);
  const typeFontSize = Math.min(fittedNameSize * 0.72, fitTextSize(typeText.textContent, preferredTypeSize, fitWidth, 4.5));
  [nameText, typeText].forEach((text) => {
    text.dataset.centerOrientation = centerOrientation;
  });
  nameText.setAttribute('font-size', fittedNameSize);
  typeText.setAttribute('font-size', typeFontSize);
}

function inverseRotateVector(x, y, rotation) {
  if (rotation === 90) return { x: y, y: -x };
  if (rotation === 180) return { x: -x, y: -y };
  if (rotation === 270) return { x: -y, y: x };
  return { x, y };
}

function updateComponentEndpoints(component) {
  document.querySelectorAll(`.wire-endpoint-group[data-component="${cssEscape(component.name)}"]`).forEach((group) => {
    group.setAttribute('transform', componentTransform(component));
    const label = {
      x: Number(group.dataset.labelX),
      y: Number(group.dataset.labelY),
      width: Number(group.dataset.labelWidth),
      height: Number(group.dataset.labelHeight),
      rotation: readableLabelLocalRotation(group.dataset.side, component.rotation || 0),
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

function readableScreenRotation(side) {
  return readableScreenTextRotationForSide(side, 0);
}

function readableLabelLocalRotation(localSide, componentRotation) {
  return readableLocalTextRotation(
    readableScreenTextRotationForSide(localSide, componentRotation || 0),
    componentRotation || 0,
  );
}

function readableCenterTextLocalRotation(centerOrientation, componentRotation) {
  return readableLocalTextRotation(centerOrientation === 'vertical' ? -90 : 0, componentRotation || 0);
}

function centerTextOrientation(component, componentRotation, text, preferredSize) {
  const screenSize = centerScreenSize(component, componentRotation || 0);
  const screenWidth = Math.max(1, screenSize.width);
  const screenHeight = Math.max(1, screenSize.height);
  if (screenWidth < screenHeight * 0.62) return 'vertical';
  if (estimateTextWidth(text, preferredSize) > Math.max(1, screenWidth - 8)) return 'vertical';
  return 'horizontal';
}

function centerTextFitWidth(component, componentRotation, centerOrientation) {
  const screenSize = centerScreenSize(component, componentRotation || 0);
  const fitSpan = centerOrientation === 'vertical' ? screenSize.height : screenSize.width;
  return Math.max(8, fitSpan - 8);
}

function centerScreenSize(component, componentRotation) {
  const rotation = normalizeRotation(componentRotation || 0);
  if (Math.abs(rotation) === 90) {
    return { width: component.center.height, height: component.center.width };
  }
  return { width: component.center.width, height: component.center.height };
}

function readableScreenTextRotationForSide(localSide, componentRotation) {
  const screenSide = rotateSide(localSide, componentRotation || 0);
  return screenSide === 'top' || screenSide === 'bottom' ? -90 : 0;
}

function readableLocalTextRotation(targetScreenRotation, componentRotation) {
  return normalizeRotation(targetScreenRotation - (componentRotation || 0));
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

function normalizeBounds(bounds) {
  return {
    x: Number(bounds?.x ?? 0),
    y: Number(bounds?.y ?? 0),
    width: Math.max(1, Number(bounds?.width ?? 1)),
    height: Math.max(1, Number(bounds?.height ?? 1)),
  };
}

function fitBoundsToViewport(bounds, padding = 48) {
  const normalized = normalizeBounds(bounds);
  const rect = host.getBoundingClientRect();
  const viewportAspect = Math.max(rect.width, 1) / Math.max(rect.height, 1);
  let width = normalized.width + padding * 2;
  let height = normalized.height + padding * 2;
  if (width / height < viewportAspect) {
    width = height * viewportAspect;
  } else {
    height = width / viewportAspect;
  }
  const centerX = normalized.x + normalized.width / 2;
  const centerY = normalized.y + normalized.height / 2;
  return {
    x: centerX - width / 2,
    y: centerY - height / 2,
    width,
    height,
  };
}

function renderedSceneBounds(svg, fallbackBounds) {
  if (!svg || !svg.getScreenCTM) return normalizeBounds(fallbackBounds);
  const inverse = svg.getScreenCTM()?.inverse();
  if (!inverse) return normalizeBounds(fallbackBounds);
  const items = [...svg.querySelectorAll('.component,.wire-endpoint-group,.no-connect-marker,.no-connect-stub,.no-connect-dot')];
  const points = [];
  items.forEach((item) => {
    const rect = item.getBoundingClientRect();
    if (!rect.width && !rect.height) return;
    [
      [rect.left, rect.top],
      [rect.right, rect.top],
      [rect.right, rect.bottom],
      [rect.left, rect.bottom],
    ].forEach(([x, y]) => {
      const point = svg.createSVGPoint();
      point.x = x;
      point.y = y;
      points.push(point.matrixTransform(inverse));
    });
  });
  if (!points.length) return normalizeBounds(fallbackBounds);
  const minX = Math.min(...points.map((point) => point.x));
  const minY = Math.min(...points.map((point) => point.y));
  const maxX = Math.max(...points.map((point) => point.x));
  const maxY = Math.max(...points.map((point) => point.y));
  return {
    x: minX,
    y: minY,
    width: Math.max(1, maxX - minX),
    height: Math.max(1, maxY - minY),
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

function setComponentGroupSelection(componentNames) {
  clearSelectionState();
  state.selectedComponents = uniqueValues(componentNames);
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
  state.selectedComponents = [];
  state.diagnosticNodes = [];
  state.diagnosticComponents = [];
  document.querySelectorAll('.component.group-selected').forEach((component) => {
    component.classList.remove('group-selected');
  });
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
    document.querySelectorAll(`.wire-endpoint-group[data-node="${cssEscape(node)}"]`).forEach((endpoint) => {
      endpoint.classList.add('diagnostic-selected');
    });
  });
  state.diagnosticComponents.forEach((componentName) => {
    const component = document.querySelector(`.component[data-component="${cssEscape(componentName)}"]`);
    if (component) component.classList.add('diagnostic-selected');
  });
  document.querySelectorAll('.component').forEach((component) => {
    component.classList.toggle('group-selected', state.selectedComponents.includes(component.dataset.component));
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

function estimateTextWidth(text, fontSize) {
  return Math.max(1, String(text).length * fontSize * 0.58);
}

function cssEscape(value) {
  if (window.CSS && CSS.escape) return CSS.escape(value);
  return String(value).replace(/"/g, '\"');
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
