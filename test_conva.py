from nicegui import ui

ui.add_head_html(
    """
    <script src="https://unpkg.com/konva@9/konva.min.js"></script>
    """,
    shared=True,
)

ui.add_body_html(
    r"""
<script>
function initKonvaDemo() {
  const container = document.getElementById('diagram');

  if (!container) {
    console.error('No #diagram element found');
    return;
  }

  if (container.dataset.konvaInitialized === 'true') {
    return;
  }

  if (typeof Konva === 'undefined') {
    console.error('Konva did not load. Check internet/CDN access.');
    return;
  }

  container.dataset.konvaInitialized = 'true';

  const stage = new Konva.Stage({
    container: 'diagram',
    width: container.clientWidth,
    height: container.clientHeight,
    draggable: true,
  });

  const gridLayer = new Konva.Layer({ listening: false });
  const wireLayer = new Konva.Layer();
  const componentLayer = new Konva.Layer();

  stage.add(gridLayer);
  stage.add(wireLayer);
  stage.add(componentLayer);

  const components = {};
  const terminals = {};
  const wires = [];

  function drawGrid() {
    gridLayer.destroyChildren();

    const scale = stage.scaleX();
    const pos = stage.position();

    const minor = 25;
    const major = 125;

    const width = stage.width();
    const height = stage.height();

    const startX = -pos.x / scale;
    const startY = -pos.y / scale;
    const endX = startX + width / scale;
    const endY = startY + height / scale;

    for (let x = Math.floor(startX / minor) * minor; x < endX; x += minor) {
      gridLayer.add(new Konva.Line({
        points: [x, startY, x, endY],
        stroke: '#d5dde5',
        strokeWidth: 1 / scale,
      }));
    }

    for (let y = Math.floor(startY / minor) * minor; y < endY; y += minor) {
      gridLayer.add(new Konva.Line({
        points: [startX, y, endX, y],
        stroke: '#d5dde5',
        strokeWidth: 1 / scale,
      }));
    }

    for (let x = Math.floor(startX / major) * major; x < endX; x += major) {
      gridLayer.add(new Konva.Line({
        points: [x, startY, x, endY],
        stroke: '#ef9a75',
        dash: [8 / scale, 8 / scale],
        strokeWidth: 1.5 / scale,
      }));
    }

    for (let y = Math.floor(startY / major) * major; y < endY; y += major) {
      gridLayer.add(new Konva.Line({
        points: [startX, y, endX, y],
        stroke: '#ef9a75',
        dash: [8 / scale, 8 / scale],
        strokeWidth: 1.5 / scale,
      }));
    }

    gridLayer.batchDraw();
  }

  function updateReadableLabels(componentGroup) {
    const rotation = componentGroup.rotation();

    componentGroup.find('.readable-label').forEach((label) => {
      label.rotation(-rotation);
    });
  }

  function updateAllReadableLabels() {
    Object.values(components).forEach(updateReadableLabels);
  }

  function terminalWorldPosition(terminalId) {
    const terminal = terminals[terminalId];
    return terminal.getAbsoluteTransform().point({ x: 0, y: 0 });
  }

  function orthogonalRoute(a, b) {
    const midY = Math.min(a.y, b.y) - 55;

    return [
      a.x, a.y,
      a.x, midY,
      b.x, midY,
      b.x, b.y,
    ];
  }

  function updateWires() {
    wires.forEach((wire) => {
      const a = terminalWorldPosition(wire.from);
      const b = terminalWorldPosition(wire.to);

      const points = orthogonalRoute(a, b);
      wire.line.points(points);

      wire.startDot.position(a);
      wire.endDot.position(b);

      const labelX = points[2] + 6;
      const labelY = points[3] - 18;

      wire.label.position({
        x: labelX,
        y: labelY,
      });
    });

    wireLayer.batchDraw();
  }

  function updateScene() {
    updateAllReadableLabels();
    updateWires();
    componentLayer.batchDraw();
    wireLayer.batchDraw();
  }

  function component({ id, x, y, w, h, name, type, rotation = 0 }) {
    const group = new Konva.Group({
      x,
      y,
      rotation,
      draggable: true,
      id,
      name: 'component',
    });

    group.add(new Konva.Rect({
      x: 0,
      y: 0,
      width: w,
      height: h,
      fill: 'white',
      stroke: '#222',
      strokeWidth: 2,
      cornerRadius: 8,
      shadowColor: 'black',
      shadowBlur: 4,
      shadowOpacity: 0.15,
      shadowOffset: { x: 2, y: 2 },
    }));

    group.add(new Konva.Text({
      x: 0,
      y: h / 2 - 20,
      width: w,
      align: 'center',
      text: name + '\n' + type,
      fontSize: 15,
      lineHeight: 1.25,
      fill: '#333',
      listening: false,
    }));

    group.on('dragmove', () => {
      updateScene();
    });

    group.on('contextmenu', (e) => {
      e.evt.preventDefault();

      const next = (group.rotation() + 90) % 360;
      group.rotation(next);

      updateScene();
    });

    componentLayer.add(group);
    components[id] = group;

    updateReadableLabels(group);

    return group;
  }

  function addTerminal(parent, {
    id,
    x,
    y,
    label,
    labelDx = -12,
    labelDy = -44,
  }) {
    const terminal = new Konva.Group({
      x,
      y,
      id,
      name: 'terminal',
    });

    terminal.add(new Konva.Rect({
      x: -7,
      y: -7,
      width: 14,
      height: 14,
      fill: '#f7fbff',
      stroke: '#789',
      strokeWidth: 1,
    }));

    terminal.add(new Konva.Circle({
      x: 0,
      y: 0,
      radius: 2,
      fill: '#333',
    }));

    /*
      Important pattern:

      The label is inside the component group, so its POSITION follows
      component movement and rotation.

      But it has class readable-label, and updateReadableLabels sets:

          label.rotation(-component.rotation())

      So the text's global rotation remains readable/upright.
    */
    const text = new Konva.Text({
      x: x + labelDx,
      y: y + labelDy,
      text: label,
      fontSize: 11,
      fill: '#0040aa',
      name: 'readable-label',
      listening: false,
    });

    parent.add(terminal);
    parent.add(text);

    terminals[id] = terminal;

    updateReadableLabels(parent);

    return terminal;
  }

  function addWire({ from, to, color = 'red', label }) {
    const a = terminalWorldPosition(from);
    const b = terminalWorldPosition(to);
    const points = orthogonalRoute(a, b);

    const line = new Konva.Line({
      points,
      stroke: color,
      strokeWidth: 3,
      lineCap: 'round',
      lineJoin: 'round',
    });

    const startDot = new Konva.Circle({
      x: a.x,
      y: a.y,
      radius: 4,
      fill: color,
    });

    const endDot = new Konva.Circle({
      x: b.x,
      y: b.y,
      radius: 4,
      fill: color,
    });

    const text = new Konva.Text({
      x: points[2] + 6,
      y: points[3] - 18,
      text: label,
      fontSize: 11,
      fill: color,
      listening: false,
    });

    wireLayer.add(line);
    wireLayer.add(startDot);
    wireLayer.add(endDot);
    wireLayer.add(text);

    wires.push({
      from,
      to,
      line,
      startDot,
      endDot,
      label: text,
    });
  }

  const livePower = component({
    id: 'live_power_3',
    x: 170,
    y: 260,
    w: 100,
    h: 250,
    name: 'live_power_3',
    type: 'terminal_block',
  });

  const opto = component({
    id: 'opto_board',
    x: 350,
    y: 160,
    w: 360,
    h: 360,
    name: 'opto_board',
    type: 'pcb',
  });

  const alarm = component({
    id: 'alarm_limit_board',
    x: 820,
    y: 260,
    w: 290,
    h: 210,
    name: 'alarm_limit_board',
    type: 'pcb',
  });

  const rotated = component({
    id: 'rotated_device',
    x: 500,
    y: 650,
    w: 260,
    h: 120,
    name: 'rotated_device',
    type: 'right-click me',
    rotation: -15,
  });

  ['VIN+', 'VIN-', 'GND', 'OUT1', 'OUT2', 'OUT3'].forEach((name, i) => {
    addTerminal(livePower, {
      id: `live_power_3.${name}`,
      x: 24 + (i % 3) * 26,
      y: i < 3 ? 0 : 250,
      label: name,
    });
  });

  [
    'B-', 'B+', 'YLIM+', 'YLIM-', 'XLIM+',
    'XLIM-', 'ZLIM+', 'ZLIM-', 'COIL', 'SPARE'
  ].forEach((name, i) => {
    addTerminal(opto, {
      id: `opto_board.${name}`,
      x: 60 + i * 24,
      y: 0,
      label: name,
    });
  });

  [
    'YLIM+', 'YLIM-', 'XLIM+', 'XLIM-',
    'ZLIM+', 'ZLIM-', 'ESTOP', 'GND'
  ].forEach((name, i) => {
    addTerminal(alarm, {
      id: `alarm_limit_board.${name}`,
      x: 40 + i * 28,
      y: 0,
      label: name,
    });
  });

  ['A1', 'A2', '13', '24'].forEach((name, i) => {
    addTerminal(rotated, {
      id: `rotated_device.${name}`,
      x: 50 + i * 45,
      y: 0,
      label: name,
      labelDx: -8,
      labelDy: -30,
    });
  });

  addWire({
    from: 'opto_board.YLIM+',
    to: 'alarm_limit_board.YLIM+',
    color: '#555',
    label: 'YLIM+',
  });

  addWire({
    from: 'opto_board.YLIM-',
    to: 'alarm_limit_board.YLIM-',
    color: '#555',
    label: 'YLIM-',
  });

  addWire({
    from: 'opto_board.XLIM+',
    to: 'alarm_limit_board.XLIM+',
    color: 'red',
    label: 'XLIM+',
  });

  addWire({
    from: 'opto_board.XLIM-',
    to: 'alarm_limit_board.XLIM-',
    color: 'red',
    label: 'XLIM-',
  });

  addWire({
    from: 'live_power_3.VIN+',
    to: 'opto_board.B+',
    color: 'blue',
    label: 'VIN+',
  });

  addWire({
    from: 'live_power_3.VIN-',
    to: 'opto_board.B-',
    color: 'blue',
    label: 'VIN-',
  });

  addWire({
    from: 'rotated_device.A1',
    to: 'opto_board.COIL',
    color: 'green',
    label: 'A1',
  });

  drawGrid();
  updateScene();

  stage.on('dragmove', () => {
    drawGrid();
  });

  stage.on('wheel', (e) => {
    e.evt.preventDefault();

    const oldScale = stage.scaleX();
    const pointer = stage.getPointerPosition();

    const mousePointTo = {
      x: (pointer.x - stage.x()) / oldScale,
      y: (pointer.y - stage.y()) / oldScale,
    };

    const scaleBy = 1.08;
    const direction = e.evt.deltaY > 0 ? -1 : 1;
    let newScale = direction > 0 ? oldScale * scaleBy : oldScale / scaleBy;

    newScale = Math.max(0.15, Math.min(6.0, newScale));

    stage.scale({
      x: newScale,
      y: newScale,
    });

    stage.position({
      x: pointer.x - mousePointTo.x * newScale,
      y: pointer.y - mousePointTo.y * newScale,
    });

    drawGrid();
    stage.batchDraw();
  });

  window.addEventListener('resize', () => {
    stage.width(container.clientWidth);
    stage.height(container.clientHeight);
    drawGrid();
    stage.batchDraw();
  });
}
</script>
""",
    shared=True,
)


@ui.page("/")
def index():
    ui.label("Konva wiring diagram demo").classes("text-h5 q-pa-sm")

    with ui.row().classes("q-pa-sm q-gutter-sm"):
        ui.label("Drag components. Right-click a component to rotate it 90°. Labels follow the component but stay readable. Wires reroute from terminal positions.")

    ui.element("div").props("id=diagram").style(
        """
        width: 100%;
        height: 82vh;
        border: 1px solid #999;
        background: #eef3f7;
        overflow: hidden;
        """
    )

    ui.timer(0.2, lambda: ui.run_javascript("initKonvaDemo()"), once=True)


ui.run(
    title="PanelViz Konva Demo",
    reload=False,
)