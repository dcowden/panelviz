from nicegui import ui

ui.add_head_html(
    """
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/jointjs/3.7.7/joint.min.css">

    <script src="https://cdnjs.cloudflare.com/ajax/libs/jquery/3.6.4/jquery.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/lodash.js/4.17.21/lodash.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/backbone.js/1.4.1/backbone-min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/jointjs/3.7.7/joint.min.js"></script>

    <style>
      #paper-wrap {
        width: 100%;
        height: 82vh;
        border: 1px solid #999;
        background: #eef3f7;
        overflow: hidden;
        cursor: grab;
      }

      #paper-wrap:active {
        cursor: grabbing;
      }

      .joint-paper {
        background: #eef3f7;
      }
    </style>
    """,
    shared=True,
)

ui.add_body_html(
    r"""
<script>
function initJointInsideLabelDemo() {
  const container = document.getElementById('paper-wrap');

  if (!container) {
    console.error('No #paper-wrap element found');
    return;
  }

  if (container.dataset.jointInitialized === 'true') {
    return;
  }

  if (typeof joint === 'undefined') {
    console.error('JointJS did not load. Check CDN/network access.');
    return;
  }

  container.dataset.jointInitialized = 'true';

  // ------------------------------------------------------------
  // Canonical app model
  // ------------------------------------------------------------

  const model = {
    components: [
      {
        id: 'live_power_3',
        ref: 'TB1',
        name: 'live_power_3',
        type: 'terminal_block',
        x: 80,
        y: 210,
        w: 160,
        h: 240,
        orientation: 0,
        terminals: [
          { id: 'VIN_PLUS',  pin: '1', signal: 'VIN+', side: 'top' },
          { id: 'VIN_MINUS', pin: '2', signal: 'VIN-', side: 'top' },
          { id: 'GND',       pin: '3', signal: 'GND',  side: 'top' },
          { id: 'OUT1',      pin: '4', signal: 'OUT1', side: 'bottom' },
          { id: 'OUT2',      pin: '5', signal: 'OUT2', side: 'bottom' },
          { id: 'OUT3',      pin: '6', signal: 'OUT3', side: 'bottom' },
        ],
      },
      {
        id: 'opto_board',
        ref: 'U1',
        name: 'opto_board',
        type: 'pcb',
        x: 360,
        y: 160,
        w: 420,
        h: 370,
        orientation: 0,
        terminals: [
          { id: 'B_MINUS', pin: '1',  signal: 'B-',     side: 'top' },
          { id: 'B_PLUS',  pin: '2',  signal: 'B+',     side: 'top' },
          { id: 'YLIM_P',  pin: '3',  signal: 'YLIM+',  side: 'top' },
          { id: 'YLIM_M',  pin: '4',  signal: 'YLIM-',  side: 'top' },
          { id: 'XLIM_P',  pin: '5',  signal: 'XLIM+',  side: 'top' },
          { id: 'XLIM_M',  pin: '6',  signal: 'XLIM-',  side: 'top' },
          { id: 'ZLIM_P',  pin: '7',  signal: 'ZLIM+',  side: 'bottom' },
          { id: 'ZLIM_M',  pin: '8',  signal: 'ZLIM-',  side: 'bottom' },
          { id: 'COIL',    pin: '9',  signal: 'COIL',   side: 'bottom' },
          { id: 'SPARE',   pin: '10', signal: 'SPARE',  side: 'bottom' },
        ],
      },
      {
        id: 'alarm_limit_board',
        ref: 'U2',
        name: 'alarm_limit_board',
        type: 'pcb',
        x: 910,
        y: 230,
        w: 340,
        h: 250,
        orientation: 0,
        terminals: [
          { id: 'YLIM_P', pin: '1', signal: 'YLIM+', side: 'top' },
          { id: 'YLIM_M', pin: '2', signal: 'YLIM-', side: 'top' },
          { id: 'XLIM_P', pin: '3', signal: 'XLIM+', side: 'top' },
          { id: 'XLIM_M', pin: '4', signal: 'XLIM-', side: 'top' },
          { id: 'ZLIM_P', pin: '5', signal: 'ZLIM+', side: 'bottom' },
          { id: 'ZLIM_M', pin: '6', signal: 'ZLIM-', side: 'bottom' },
          { id: 'ESTOP',  pin: '7', signal: 'ESTOP', side: 'bottom' },
          { id: 'GND',    pin: '8', signal: 'GND',   side: 'bottom' },
        ],
      },
    ],

    wires: [
      {
        id: 'W101',
        net: 'VIN+',
        color: '#1565c0',
        from: ['live_power_3', 'VIN_PLUS'],
        to: ['opto_board', 'B_PLUS'],
      },
      {
        id: 'W102',
        net: 'VIN-',
        color: '#1565c0',
        from: ['live_power_3', 'VIN_MINUS'],
        to: ['opto_board', 'B_MINUS'],
      },
      {
        id: 'W201',
        net: 'YLIM+',
        color: '#555555',
        from: ['opto_board', 'YLIM_P'],
        to: ['alarm_limit_board', 'YLIM_P'],
      },
      {
        id: 'W202',
        net: 'YLIM-',
        color: '#555555',
        from: ['opto_board', 'YLIM_M'],
        to: ['alarm_limit_board', 'YLIM_M'],
      },
      {
        id: 'W203',
        net: 'XLIM+',
        color: '#b71c1c',
        from: ['opto_board', 'XLIM_P'],
        to: ['alarm_limit_board', 'XLIM_P'],
      },
      {
        id: 'W204',
        net: 'XLIM-',
        color: '#b71c1c',
        from: ['opto_board', 'XLIM_M'],
        to: ['alarm_limit_board', 'XLIM_M'],
      },
    ],
  };

  // ------------------------------------------------------------
  // JointJS setup
  // ------------------------------------------------------------

  joint.shapes.panel = {};

  const graph = new joint.dia.Graph({}, { cellNamespace: joint.shapes });

  const paper = new joint.dia.Paper({
    el: container,
    model: graph,
    width: container.clientWidth,
    height: container.clientHeight,
    gridSize: 10,
    drawGrid: {
      name: 'doubleMesh',
      args: [
        { color: '#d5dde5', thickness: 1, scaleFactor: 1 },
        { color: '#ef9a75', thickness: 1, scaleFactor: 5 },
      ],
    },
    background: { color: '#eef3f7' },
    cellViewNamespace: joint.shapes,

    interactive: function(cellView) {
      const cell = cellView.model;

      if (cell.get('isInternalLabel')) {
        return false;
      }

      if (cell.isLink()) {
        return {
          linkMove: false,
          labelMove: false,
          vertexAdd: false,
          vertexMove: false,
          arrowheadMove: false,
        };
      }

      return true;
    },

    defaultRouter: {
      name: 'manhattan',
      args: {
        padding: 35,
        step: 10,
      },
    },

    defaultConnector: {
      name: 'rounded',
      args: {
        radius: 8,
      },
    },
  });

  // ------------------------------------------------------------
  // Custom component element
  // ------------------------------------------------------------

  joint.shapes.panel.Component = joint.dia.Element.define(
    'panel.Component',
    {
      attrs: {
        body: {
          refWidth: '100%',
          refHeight: '100%',
          fill: '#ffffcc',
          stroke: '#8b0000',
          strokeWidth: 2,
        },
        refText: {
          text: 'U?',
          refX: '50%',
          refY: -34,
          textAnchor: 'middle',
          textVerticalAnchor: 'middle',
          fill: '#006060',
          fontSize: 18,
          fontFamily: 'Consolas, monospace',
        },
        nameText: {
          text: 'component',
          refX: '50%',
          refY: -13,
          textAnchor: 'middle',
          textVerticalAnchor: 'middle',
          fill: '#006060',
          fontSize: 16,
          fontFamily: 'Consolas, monospace',
        },
        centerText: {
          text: 'pcb',
          refX: '50%',
          refY: '50%',
          textAnchor: 'middle',
          textVerticalAnchor: 'middle',
          fill: '#222',
          fontSize: 13,
          fontFamily: 'Arial, sans-serif',
        },
      },
      ports: {
        groups: {
          top: makePortGroup('top'),
          bottom: makePortGroup('bottom'),
          left: makePortGroup('left'),
          right: makePortGroup('right'),
        },
        items: [],
      },
    },
    {
      markup: [
        { tagName: 'rect', selector: 'body' },
        { tagName: 'text', selector: 'refText' },
        { tagName: 'text', selector: 'nameText' },
        { tagName: 'text', selector: 'centerText' },
      ],
    }
  );

  joint.shapes.panel.InternalLabel = joint.dia.Element.define(
    'panel.InternalLabel',
    {
      size: { width: 1, height: 1 },
      attrs: {
        label: {
          text: '',
          x: 0,
          y: 0,
          fill: '#006060',
          fontSize: 12,
          fontFamily: 'Consolas, monospace',
          textAnchor: 'middle',
          textVerticalAnchor: 'middle',
          pointerEvents: 'none',
        },
      },
    },
    {
      markup: [
        { tagName: 'text', selector: 'label' },
      ],
    }
  );

  // ------------------------------------------------------------
  // Port groups: ports are anchors + small pin numbers only
  // ------------------------------------------------------------

  function makePortGroup(side) {
    const common = {
      markup: [
        { tagName: 'line', selector: 'stub' },
        { tagName: 'rect', selector: 'terminalBox' },
        { tagName: 'text', selector: 'pinText' },
      ],
      attrs: {
        terminalBox: {
          width: 10,
          height: 10,
          x: -5,
          y: -5,
          fill: '#f8fbff',
          stroke: '#789',
          strokeWidth: 1,
          magnet: true,
        },
        stub: {
          stroke: '#8b0000',
          strokeWidth: 1.4,
        },
        pinText: {
          fill: '#8b0000',
          fontSize: 12,
          fontFamily: 'Consolas, monospace',
          pointerEvents: 'none',
        },
      },
    };

    if (side === 'top') {
      return {
        ...common,
        position: { name: 'top' },
        attrs: {
          ...common.attrs,
          stub: { ...common.attrs.stub, x1: 0, y1: 0, x2: 0, y2: -24 },
          pinText: {
            ...common.attrs.pinText,
            x: 0,
            y: -36,
            textAnchor: 'middle',
            textVerticalAnchor: 'middle',
            transform: 'rotate(-90)',
          },
        },
      };
    }

    if (side === 'bottom') {
      return {
        ...common,
        position: { name: 'bottom' },
        attrs: {
          ...common.attrs,
          stub: { ...common.attrs.stub, x1: 0, y1: 0, x2: 0, y2: 24 },
          pinText: {
            ...common.attrs.pinText,
            x: 0,
            y: 36,
            textAnchor: 'middle',
            textVerticalAnchor: 'middle',
            transform: 'rotate(-90)',
          },
        },
      };
    }

    if (side === 'left') {
      return {
        ...common,
        position: { name: 'left' },
        attrs: {
          ...common.attrs,
          stub: { ...common.attrs.stub, x1: 0, y1: 0, x2: -24, y2: 0 },
          pinText: {
            ...common.attrs.pinText,
            x: -36,
            y: 0,
            textAnchor: 'end',
            textVerticalAnchor: 'middle',
          },
        },
      };
    }

    return {
      ...common,
      position: { name: 'right' },
      attrs: {
        ...common.attrs,
        stub: { ...common.attrs.stub, x1: 0, y1: 0, x2: 24, y2: 0 },
        pinText: {
          ...common.attrs.pinText,
          x: 36,
          y: 0,
          textAnchor: 'start',
          textVerticalAnchor: 'middle',
        },
      },
    };
  }

  // ------------------------------------------------------------
  // Layout helpers
  // ------------------------------------------------------------

  const sides = ['top', 'right', 'bottom', 'left'];

  function rotateSide(side, orientation) {
    const turns = (((orientation % 360) + 360) % 360) / 90;
    const index = sides.indexOf(side);
    return sides[(index + turns) % 4];
  }

  function buildPorts(component) {
    return component.terminals.map((terminal) => {
      const visualSide = rotateSide(terminal.side, component.orientation);

      return {
        id: terminal.id,
        group: visualSide,
        attrs: {
          pinText: {
            text: terminal.pin,
          },
        },
      };
    });
  }

  function terminalsByVisualSide(component) {
    const grouped = {
      top: [],
      bottom: [],
      left: [],
      right: [],
    };

    component.terminals.forEach((terminal) => {
      const visualSide = rotateSide(terminal.side, component.orientation);
      grouped[visualSide].push(terminal);
    });

    return grouped;
  }

  function signalLabelLayout(component, side, index, count) {
    const w = component.w;
    const h = component.h;

    if (side === 'top') {
      const gap = w / (count + 1);
      return {
        x: gap * (index + 1),
        y: 42,
        angle: -90,
        anchor: 'end',
      };
    }

    if (side === 'bottom') {
      const gap = w / (count + 1);
      return {
        x: gap * (index + 1),
        y: h - 42,
        angle: -90,
        anchor: 'start',
      };
    }

    if (side === 'left') {
      const gap = h / (count + 1);
      return {
        x: 44,
        y: gap * (index + 1),
        angle: 0,
        anchor: 'start',
      };
    }

    const gap = h / (count + 1);
    return {
      x: w - 44,
      y: gap * (index + 1),
      angle: 0,
      anchor: 'end',
    };
  }

  // ------------------------------------------------------------
  // Renderers
  // ------------------------------------------------------------

  function renderComponent(component) {
    const element = new joint.shapes.panel.Component({
      id: component.id,
      position: { x: component.x, y: component.y },
      size: { width: component.w, height: component.h },
      attrs: {
        refText: { text: component.ref },
        nameText: { text: component.name },
        centerText: { text: component.type },
      },
      ports: {
        groups: {
          top: makePortGroup('top'),
          bottom: makePortGroup('bottom'),
          left: makePortGroup('left'),
          right: makePortGroup('right'),
        },
        items: buildPorts(component),
      },
    });

    element.set('componentId', component.id);
    return element;
  }

  function renderInternalLabels(component, parentElement) {
    const grouped = terminalsByVisualSide(component);
    const labels = [];

    Object.keys(grouped).forEach((side) => {
      const terminals = grouped[side];

      terminals.forEach((terminal, index) => {
        const layout = signalLabelLayout(component, side, index, terminals.length);

        const label = new joint.shapes.panel.InternalLabel({
          position: {
            x: component.x + layout.x,
            y: component.y + layout.y,
          },
          attrs: {
            label: {
              text: terminal.signal,
              transform: `rotate(${layout.angle})`,
              textAnchor: layout.anchor,
              textVerticalAnchor: 'middle',
            },
          },
        });

        label.set('isInternalLabel', true);
        label.set('parentComponentId', component.id);
        label.set('labelKind', 'signal');

        parentElement.embed(label);
        labels.push(label);
      });
    });

    return labels;
  }

  function renderWire(wire) {
    return new joint.shapes.standard.Link({
      id: wire.id,
      source: {
        id: wire.from[0],
        port: wire.from[1],
      },
      target: {
        id: wire.to[0],
        port: wire.to[1],
      },
      router: {
        name: 'manhattan',
        args: {
          padding: 35,
          step: 10,
        },
      },
      connector: {
        name: 'rounded',
        args: {
          radius: 8,
        },
      },
      attrs: {
        line: {
          stroke: wire.color,
          strokeWidth: 3,
          targetMarker: null,
          sourceMarker: null,
        },
      },
      labels: [
        {
          position: 0.5,
          attrs: {
            text: {
              text: wire.id,
              fill: wire.color,
              fontSize: 11,
              fontFamily: 'Consolas, monospace',
            },
            rect: {
              fill: '#eef3f7',
              stroke: 'none',
            },
          },
        },
      ],
    });
  }

  function renderDiagram() {
    graph.clear();

    const componentElements = [];
    const labelElements = [];
    const wireElements = [];

    model.components.forEach((component) => {
      const element = renderComponent(component);
      componentElements.push(element);

      const labels = renderInternalLabels(component, element);
      labelElements.push(...labels);
    });

    model.wires.forEach((wire) => {
      wireElements.push(renderWire(wire));
    });

    graph.addCells([...componentElements, ...labelElements, ...wireElements]);

    updateZoomVisibility();
  }

  function findComponentModel(id) {
    return model.components.find((component) => component.id === id);
  }

  // ------------------------------------------------------------
  // Zoom-dependent label visibility
  // ------------------------------------------------------------

  let viewScale = 1.0;

  function updateZoomVisibility() {
    graph.getCells().forEach((cell) => {
      if (cell.get('isInternalLabel')) {
        cell.attr('label/display', viewScale < 0.55 ? 'none' : '');
      }

      if (cell.isElement() && cell.get('componentId')) {
        const component = findComponentModel(cell.id);
        if (!component) return;

        component.terminals.forEach((terminal) => {
          const display = viewScale < 0.40 ? 'none' : '';
          cell.portProp(terminal.id, 'attrs/pinText/display', display);
        });

        cell.attr('centerText/display', viewScale < 0.45 ? 'none' : '');
      }
    });
  }

  // ------------------------------------------------------------
  // Interactions
  // ------------------------------------------------------------

  graph.on('change:position', (cell) => {
    if (!cell.isElement() || cell.get('isInternalLabel')) {
      return;
    }

    const component = findComponentModel(cell.id);

    if (!component) {
      return;
    }

    const pos = cell.position();
    component.x = pos.x;
    component.y = pos.y;
  });

  paper.on('element:contextmenu', (elementView, evt) => {
    evt.preventDefault();

    const cell = elementView.model;

    if (cell.get('isInternalLabel')) {
      return;
    }

    const component = findComponentModel(cell.id);

    if (!component) {
      return;
    }

    component.orientation = (component.orientation + 90) % 360;
    renderDiagram();
  });

  paper.on('link:mouseenter', (linkView) => {
    linkView.model.attr('line/strokeWidth', 5);
    linkView.model.label(0, {
      attrs: {
        text: {
          text: linkView.model.id + '  ' + getWireNet(linkView.model.id),
        },
      },
    });
  });

  paper.on('link:mouseleave', (linkView) => {
    linkView.model.attr('line/strokeWidth', 3);
    linkView.model.label(0, {
      attrs: {
        text: {
          text: linkView.model.id,
        },
      },
    });
  });

  paper.on('element:mouseenter', (elementView) => {
    const cell = elementView.model;
    if (!cell.get('isInternalLabel')) {
      cell.attr('body/strokeWidth', 3);
    }
  });

  paper.on('element:mouseleave', (elementView) => {
    const cell = elementView.model;
    if (!cell.get('isInternalLabel')) {
      cell.attr('body/strokeWidth', 2);
    }
  });

  function getWireNet(wireId) {
    const wire = model.wires.find((w) => w.id === wireId);
    return wire ? wire.net : '';
  }

  // ------------------------------------------------------------
  // Pan and zoom
  // ------------------------------------------------------------

  let tx = 0;
  let ty = 0;

  function applyViewport() {
    paper.scale(viewScale, viewScale);
    paper.translate(tx, ty);
    updateZoomVisibility();
  }

  container.addEventListener('wheel', (evt) => {
    evt.preventDefault();

    const rect = container.getBoundingClientRect();
    const mx = evt.clientX - rect.left;
    const my = evt.clientY - rect.top;

    const oldScale = viewScale;
    const scaleBy = 1.08;

    if (evt.deltaY < 0) {
      viewScale *= scaleBy;
    } else {
      viewScale /= scaleBy;
    }

    viewScale = Math.max(0.2, Math.min(5.0, viewScale));

    const worldX = (mx - tx) / oldScale;
    const worldY = (my - ty) / oldScale;

    tx = mx - worldX * viewScale;
    ty = my - worldY * viewScale;

    applyViewport();
  }, { passive: false });

  let isPanning = false;
  let lastPan = null;

  paper.on('blank:pointerdown', (evt) => {
    isPanning = true;
    lastPan = {
      x: evt.clientX,
      y: evt.clientY,
    };
  });

  window.addEventListener('mousemove', (evt) => {
    if (!isPanning) {
      return;
    }

    const dx = evt.clientX - lastPan.x;
    const dy = evt.clientY - lastPan.y;

    tx += dx;
    ty += dy;

    lastPan = {
      x: evt.clientX,
      y: evt.clientY,
    };

    applyViewport();
  });

  window.addEventListener('mouseup', () => {
    isPanning = false;
  });

  window.addEventListener('resize', () => {
    paper.setDimensions(container.clientWidth, container.clientHeight);
  });

  // ------------------------------------------------------------
  // Go
  // ------------------------------------------------------------

  renderDiagram();
  applyViewport();

  console.log('JointJS inside-label wiring demo initialized');
}
</script>
""",
    shared=True,
)


@ui.page("/")
def index():
    ui.label("JointJS wiring diagram demo — inside terminal labels").classes("text-h5 q-pa-sm")

    with ui.row().classes("q-pa-sm q-gutter-sm"):
        ui.label(
            "Drag components. Right-click a component to rotate/reflow. "
            "Mouse wheel zooms. Drag blank space to pan. "
            "Ports are anchors; signal labels are inside the component."
        )

    ui.element("div").props("id=paper-wrap")

    ui.timer(0.2, lambda: ui.run_javascript("initJointInsideLabelDemo()"), once=True)


ui.run(
    title="PanelViz JointJS Inside Labels Demo",
    reload=False,
)