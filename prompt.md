# PanelViz

Write me a tool that automatically generates wire lists and diagrams for an electrical panel.
This tool is inspired by wireviz WV, but with these differences
  * WV cares about connectors and cables, but not about nets and wire labels. I want wirelabels as an output
  * WV is for wire harnesses, but I want components too
  * WV uses graphphz, and that's ok but i bet there are better alternatives out there now
  * WV doesnt make it easy to WRITE files, but that's one of my goals
  
The tool reads an input yaml file, which specifies veraious types of components, and connections between them.
The top-level yaml sections include `config`, `components`, `connections`, and `no_connects`; `connections` is not nested inside `components`.
The output includes CSV/text reports and SVG diagrams generated from the typed NetworkX-backed model.

I have created an example file called mycnc.yml that has full example. The detailed format notes that used to live as inline comments in that file are captured in this prompt so the example yaml can stay tight and machine-friendly.

## Concepts
  This tool must understand that wires connecting together are a 'net'. This is key for easily creating wires and labels.
  
  all components export pins, and any component may also export named nets, which are sets of one or more pins that are electrically common. A net with more than one pin means those pins are connected inside that component. For non-terminal components, every pin listed in a named net must be an actual physical pin on that component.
  
  this app is all about creating wire labels and nets for easy debugging. when we generate a wire list.
  Each physical wire must have a unique wire label.  Instead of a fixed numbering strategy, wire labels are generated from a user-provided text format with placeholders.
  The placeholder system should be printf-inspired. Examples:
    * `%netname-%seq` uses the resolved net name followed by a per-net or configured sequence.
    * `%seq` uses a global sequence.
    * `%{5d}seq` uses a zero-padded global sequence.
  The default wire label format should preserve the original intent of net-based labels, for example `%netname-%seq`.

  Pin references should use only the `component.pin` form.
  Do not support multiple syntaxes such as `component.position.pin`; normalized terminal pins should be addressed as a single pin token, for example `earth.1A`.

  Multiple physical wires may connect to the same pin. This should not be an error, but it must be reported clearly in the component summary and should generate a warning.

  The tool must support explicit `NC` for pins that are intentionally not connected. Unconnected pins and multi-connected pins should both be included in warnings and in the component summary.

## YAML DSL notes

### Top-level file shape

The top-level yaml sections are:
  * `config`: global settings including `wire_label_format`, `wiring_mode`, defaults, units, and visualization styling.
  * `components`: a mapping of component names to component definitions.
  * `connections`: a section containing the physical wire list.
  * `no_connects`: a list of pins intentionally marked not connected.

`config.wire_label_format` controls generated wire labels using placeholders like `%netname` and `%seq`.
`config.wiring_mode` controls how physical wires are drawn in the diagram. Supported values are `wires` and `labels`.
  * `wires`: draw routed wire paths between component pins.
  * `labels`: draw only short endpoint stubs with the same wire label at each end, like common schematic-editor practice.
`config.defaults.awg` sets the default wire gauge for connection rows that do not specify an `awg`.
`config.units.length` controls physical component dimensions. Supported length units are `mm` and `in`.
`config.visualization` controls net styling used by both the static SVG diagram and the interactive viewer.

Visualization style fields:
  * `default_net_style`: fallback style for any net not explicitly configured.
  * `net_styles`: a mapping from net name to style.
  * Each style supports `color`, `line_weight`, and `line_style`.
  * `line_style` supports `solid`, `dashed`, and `dotted`.
  * The renderer should expose these through CSS classes/custom properties rather than hard-coding presentation directly into routing logic.
  * Default styles should make common power nets legible immediately: `110L`, `110N`, `220L`, and `220N` blue; `earth` and earth-like nets green.

Example:

```yaml
config:
  wire_label_format: "%netname-%seq"
  wiring_mode: labels
  defaults:
    awg: 20
  units:
    length: mm
  visualization:
    default_net_style:
      color: "#475569"
      line_weight: 1.6
      line_style: solid
    net_styles:
      110L: { color: "#2563eb", line_weight: 1.8, line_style: solid }
      110N: { color: "#2563eb", line_weight: 1.8, line_style: solid }
      220L: { color: "#2563eb", line_weight: 1.8, line_style: solid }
      220N: { color: "#2563eb", line_weight: 1.8, line_style: solid }
      earth: { color: "#16a34a", line_weight: 2.0, line_style: solid }
```

### Component definitions

The dictionary key under `components` is the component name.
`type` activates certain functionality for the component.
Supported simple component types include `connector`, `switch`, `power_supply`, `relay`, `driver`, `vfd`, `aviation_connector`, and `pcb`.
Terminal-style component types include `terminal_block` and `bus_block`.
`size.width` and `size.height` are conceptual physical dimensions in `config.units.length`.
These are not pixel dimensions or renderer-specific styling.

The `pins` value is a side map. Valid sides are `left`, `right`, `top`, and `bottom`.
Each side contains the pin names/labels located on that side of the component.
Pin names must be unique within a component across all sides.

Any component may also include a `nets` list. Each net has a `name` and `pins`; all listed pins are electrically connected inside that component. This is useful for boards, drivers, connectors, and other components that expose internal commons or semantic signal groups. For simple non-terminal components, `pins` in a net must name concrete component pins.

Example:

```yaml
components:
  transformer:
    type: power_supply
    size:
      width: 70
      height: 90
    pins:
      bottom: [GND, 110L, 110N, 220L, 220N]
    nets:
      - name: primary_neutral
        pins: [110N]
```

Earlier notes suggested pins could also be referenced by ordinal number, for example `contactor1.1` selecting the same pin as `contactor1.T1`. The current DSL rule is stricter: all pin references use `component.pin`, and terminal positions are normalized into a single pin token such as `earth.1A`.

Connectors have properties useful for diagramming.

### Terminal blocks and bus blocks

Terminal blocks have one set of pins per position.
The pin names use `component.pin`, for example `blk_power.1A`.
For terminal blocks and bus blocks, `size.width` is the width of one block, and `size.height` is the height of one block. The size describes one terminal position, not the total terminal strip.
Terminal block pin sides apply to every position. For example, `pins.left: [A]` and `pins.right: [B]` means every position has an A-side pin and a B-side pin.
All pins for a given position are always connected, even when the terminal block exposes no named nets. For example, `cnc_terminals.5A` and `cnc_terminals.5B` are electrically common by virtue of being the two sides of position 5.
In addition, all lists of pins listed in `connected` are also connected.
For example, a terminal block can have 12 total pins but only two nets because positions 1, 3, and 5 are connected, while positions 2, 4, and 6 are connected.
That is a block with two logical nets and 12 positions.

For terminal blocks, `positions` is optional. If provided, an error should occur if there is an attempt to use a number bigger than the provided value. If it is not provided, assume the number of blocks is equal to that used in the file.

`nets` is a very important part of this. By specifying nets, we can give friendly names to sets of pins. Then we can do two things:
  1. allow easier creation of wires by using net names instead of pins
  2. automatically detect errors trying to merge two nets together

Example: a terminal block group with 6 positions, each with two terminals, A and B. Pins 1A, 1B, 3A, 3B, 5A, and 5B are on net `110L`. The explicit net over positions 1, 3, and 5 is additive to the built-in per-position bridges, so each listed position includes both A and B side pins.

Terminal block and bus block behavior:
  * `terminal_block`: the net stays the same as long as the pins are connected to each other, but each physical wire gets a different sequence.
  * `bus_block`: all pins are automatically connected to each other. This is commonly used for earth blocks.

### Connections and nets

Connections list things connected to each other. Connections work together with components to form wire nets.
The key goal is to free the author from the tediousness of naming things so they are easy to trace. This is the core of the project.

`config.wire_label_format` controls generated wire labels. The net name is the name of the net, and is the same for all things electrically connected to the same net. The sequence is a sequential number after that, unique for each physical, uninterrupted wire.

The key to doing this automatically is to use the component type to determine if wires connected into multiple pins can form the same net. The default is "NO", in which case all different pins must be on different nets. Multiple wires connected to the same pin of a component are always on the same net.

The tricky thing with nets is that users name them once, even though they may have many wires and many pins connected. We do not want the user to have to manually give the net name to all of those wires. We want to infer that all wires in the same net must have the same net name. If the user connects two things that would create a net conflict, the tool should throw an error.

This means a user must name only one wire in a whole net. Any user-assigned net name becomes the name. Any nets without a name default to being named for the first component and pin connected, for example `wall_plug.GND`.

Connection rows support a compact list form and a more explicit object form:

```yaml
connections:
  wires:
    - [transformer.220L, contactor_220.T1]
    - [z_motor.zma+, cnc_terminals.1, y_cl57s.EB+]
    - from: wall_plug.1
      to: power_t.110L
      net: line_power
      awg: 12
    - route: [48v.110N, switched_110N.110N_SWITCHED, axbb-e.IN-24V0]
      net: 110N_SWITCHED
```

Use the object form when a physical wire needs metadata such as a semantic net name or wire gauge. The `net` field names the resolved electrical net for that connected set of pins. This is useful when the default inferred name is technically correct but not semantically useful. A wire-level `net` can override one component-exposed net name, but it must not hide a true conflict between two different component-declared nets. If multiple wire-level names appear in the same electrical net, that is also a conflict.

A list with exactly two endpoints is one physical wire. A list with three or more endpoints is a route chain: each adjacent endpoint pair creates one physical wire, all wires in that chain belong to the same electrical net, and each wire receives its own sequence number. If the object form uses `route`, the same route-chain expansion applies, and `net`/`awg` apply to every physical wire created by that row.

Route-chain terminal block semantics are intentionally strict:
  * `terminal_block.position` is only meaningful for a middle hop in a route chain. It means pass through that terminal position: the incoming wire lands on the first side pin, and the outgoing wire leaves from the second side pin. For a left/right terminal block, `cnc_terminals.1` expands as `cnc_terminals.1A` on the incoming segment and `cnc_terminals.1B` on the outgoing segment.
  * `terminal_block.positionPin`, such as `cnc_terminals.1A`, is a concrete terminal pin. If used as a middle hop, both adjacent physical wires connect to that same pin, intentionally creating a multi-connected terminal.
  * Middle hops that are ordinary component pins or component-exposed nets also create a concrete multi-connect at the resolved endpoint.
  * If no `net` is provided on a route chain, the resolved net name is inferred from the connected electrical graph. For ordinary pin-to-terminal chains this normally means the first endpoint becomes the net name, for example `z_motor.zma+`.

When creating wire endpoints, there are two supported endpoint modes:
  1. specify two concrete pins
  2. specify a pin and a component-exposed net. If a net is given as an endpoint, look for a component that exposes that net, and pick the lowest numbered position and pin for that number.

### Example connection notes from `mycnc.yml`

The example wires demonstrate these behaviors:
  * `wall_plug.GND` to `earth.1A`: connect specifically to the `1A` pin of `earth`. This consumes that pin.
  * `wall_plug.1` to `power_t.110L`: `power_t` exposes net `110L` on positions 1, 3, and 5, so pins 1A, 1B, 3A, 3B, 5A, and 5B are available. Use the first one, `1A`.
  * `wall_plug.2` to `power_t.110N`: `power_t` exposes net `110N` on positions 2, 4, and 6. Use the first available pin, `2A`.
  * `power_t.110L` to `transformer.110L`: use the next available pin on `power_t.110L`, which will be `1B`.
  * `power_t.110N` to `transformer.110N`: use the next available pin on `power_t.110N`, which will be `2B`.
  * `power_t.110L` to `contactor_110.T2`: consume another pin from the `power_t` block, net `110L`.
  * `transformer.GND` to `earth.earth`: use the next available pin on `earth`.
  * `transformer.220L` to `contactor_220.T1`: this is straight pin-to-pin. It is not based on exposed nets from terminal blocks, so the tool needs to use a net name according to `config.wire_label_format`.
  * `48v.GND` to `earth.earth`: use the next terminal block pin on the earth set of pins.

## Outputs

The tool generates:
  1. An svg with a wiring diagram. components are shown as blocks with all of the pin numbers. In `wires` mode, each physical wire is drawn between components. In `labels` mode, each physical wire is shown as short endpoint stubs with matching wire labels on both ends. Label text is horizontal for left/right pins and vertical for top/bottom pins.
  
  2. An png export of the above
  
  3. A net list. This is a comma delimited file, which contains the net name in the first column, and then a list of all pins connected in subsequent columns
  
  4. A wire list. This is a csv with these columns:
     wirenumber, from_component, from_pin, to_component, to_pin, netname, awg
    The wirenumber is the same as the label, and thats controlled by the wire label format
	Wires should be exported grouped by netname
 
  5. component summary. a pretty printed list of all components, with its name, any unconnected pins, any pins explicitly marked NC, and any pins with multiple physical wire connections

## Visualization decision

Use a custom SVG renderer as the primary static diagram backend.
Reasons:
  * Component pins can appear on all four sides, and the renderer needs exact control over pin boxes, terminal strips, labels, and component name fit.
  * Label mode is more useful than long routed wires for dense panel docs: each physical wire is shown as a short endpoint stub with the same wire label at both ends.
  * Endpoint stubs should have enough length to clearly separate labels from component terminals. Heavier gauges should subtly render with heavier endpoint stubs/lines.
  * Net styling should be easy to control through CSS-like properties.
  * The same layout and view model can feed an interactive browser viewer without introducing a backend service.

Important architecture rule: the renderer must not become the source of truth.
The parser and wire router should build a typed internal panel model containing components, pins, nets, physical wires, warnings, generated labels, and NetworkX graph views. The same internal model should feed:
  * static SVG diagram output
  * static interactive SVG.js viewer output
  * wire list csv
  * net list csv
  * component summary

CSV export does not need to be solved by the visualization library. It should be generated directly from the internal model.

The renderer should be hidden behind small output functions so later versions can try other layout/rendering engines without changing the parser, net resolver, wire router, or reports.

The interactive viewer should be a no-build static web app using SVG.js plus plain JavaScript/CSS. It should be generated into the output directory as `viewer.html`, `viewer.css`, `viewer.js`, and `panel-data.json`. Running `panelviz --view <input_file> [output_dir]` should generate the normal outputs, generate the viewer bundle, serve the output directory on a local static HTTP server, and launch the browser.

Interactive viewer requirements:
  * Components are draggable on the canvas.
  * Wire labels are clickable.
  * In wire highlight mode, clicking a wire label highlights both endpoints of that physical wire.
  * In net highlight mode, clicking a wire label highlights all endpoints belonging to the same net.
  * Highlighting should affect both the wire endpoint graphics and the terminal/pin boxes.
  * Wires and labels should use the same net colors, line weights, and line styles as the static SVG diagram.
  * Labels must remain readable: left/right labels are horizontal, top/bottom labels are vertical, and layout spacing must account for label size so labels do not overlap components.
  * Multi-connected terminals must show all labels. Endpoint stubs and labels should fan out from the shared terminal while preserving the same physical terminal anchor.
  * Component blocks should show the component name and the `type` value. The name should remain visually above the type label after rotation, including 180 degree rotation.
  * Component outlines should remain visually clear when pin boxes sit on the component boundary. Pin boxes should not erase rounded component corners or make terminal borders appear heavier than the component body.
  * Holding the left mouse button on empty canvas and moving should pan. The scroll wheel should zoom around the pointer.
  * Right-clicking empty canvas should clear the current selection. Right-clicking a component should rotate that component by 90 degrees.
  * Rotating a component should keep its pins, endpoint dots, stubs, and labels attached to the rotated terminal boundary. Wire labels must stay readable and must not flip upside down.
  * The viewer should include a compact help legend for interactions such as pan, zoom, right-click clear, and right-click rotate.
  * The viewer should include an embedded wire list table. Rows should use the same net color coding as the labels and should participate in highlighting.
  * Wire list headers should be sortable because real panels may have long wire lists.
  * The wire list should support both a compact `wire/from/to/net` view and a split-column view with stacked headers:
    `wire`, `from component`, `from terminal`, `to component`, `to terminal`, `net`, and `awg`.
  * The wire list panel should be scrollable, collapsible, and horizontally resizable by dragging the boundary between the canvas and table.
  * The top bar should include diagnostic actions to highlight unconnected terminals, multi-connected terminals, and components with no connections at all.

Renderer alternatives considered:
  * D2: attractive modern diagram DSL with SVG/PNG/PDF export, but it adds another external CLI and is less proven for component pin/port-heavy diagrams.
  * Mermaid: good for docs and simple flowcharts, but less suitable for precise wiring diagrams with many pin-level edges.
  * ELK/Eclipse Layout Kernel: excellent layout engine, especially because it understands ports and hierarchical/compound graphs. It is a strong candidate for a later custom SVG renderer, but it is heavier than Graphviz for the first CLI version.
  * NetworkX: the right choice for the underlying connection state and graph analysis, but not the primary visual renderer.
  * Custom SVG: chosen for the current implementation because it gives maximum control over panel-like diagrams.

## NetworkX model decision

Represent the underlying connection state with NetworkX graphs. Typed Python models still define components, pins, terminal block behavior, bus block behavior, no-connects, warnings, and label generation rules, but the electrical connectivity should live in graph form.

Maintain two NetworkX graph views:

1. Physical wiring graph
   * Each node is a concrete `component.pin`.
   * Each edge is one physical wire.
  * Edge attributes include wire label, resolved net name, optional wire-declared net name, source endpoint, destination endpoint, input order, AWG, and any future wire metadata such as color, signal type, or notes.
   * Multiple physical wires connected to the same pin are represented as multiple incident edges. Use this graph to detect and report multi-connected pins.
   * Isolated nodes, or nodes with no physical wire edges and no `NC` marker, are unconnected pins for warnings and summaries.
   * Use a NetworkX multigraph if needed so multiple physical wires between the same two pins remain distinct.

2. Net graph
   * Each node is a resolved electrical net.
   * Edges represent relationships between nets created by routed wires, terminal block bridges, bus blocks, or future logical relationships.
   * Node attributes include net name, member pins, exposed-by components, and generated sequence state.
   * Use this graph to detect net conflicts, validate merges, group wire list rows by net, and produce the net list csv.

The two graphs should be derived from the same typed panel state and kept consistent by the wire routing/net resolution layer.
The physical wiring graph answers "what physical wire goes where?"
The net graph answers "what is electrically common?"

## Current implementation decisions

Project structure:
  * Python package lives in `src/panelviz`.
  * Tests live in `tests`, as a sibling to `src`.
  * The package is configured with `pyproject.toml` as an editable install.
  * Tests are run with `pytest` and `pytest-cov`.
  * `run_tests.cmd` sets `PYTHONDONTWRITEBYTECODE=1` and runs Python with `-B` so project-level `__pycache__` folders are not created during normal test runs.
  * Test and example SVG outputs live in `tests/outputs`; the test runner clears that folder before tests and regenerates the stable `labels` and `wires` diagrams after tests pass.
  * CLI entry points are `panelviz`, `panelvis`, and `panenvis`, all calling the same command.
  * CLI syntax is `panelviz [--view] <input_file> [output_dir]`. If `output_dir` is omitted, the current working directory is used. If provided, it is created.
  * CLI outputs are `wire_list.csv`, `wire_list.txt`, `component_summary.csv`, `component_summary.txt`, and `wiring_diagram.svg`. The CLI diagram uses label mode.
  * With `--view`, the CLI also writes `viewer.html`, `viewer.css`, `viewer.js`, and `panel-data.json`, then serves the output directory locally.
  * The interactive viewer includes pan, zoom, component drag, component rotation, wire/net/component/terminal highlighting, a sortable and resizable wire-list panel, and diagnostic highlighting for unconnected, multi-connected, and isolated components.

Typed model decisions:
  * Use Pydantic v2 for typed models and validation.
  * Component classes include `Component`, `Connector`, `Switch`, `PowerSupply`, `Relay`, `Driver`, `Vfd`, `AviationConnector`, `Pcb`, `TerminalBlock`, and `BusBlock`.
  * `ComponentSize` stores physical `width` and `height`.
  * `PinSide` stores valid pin sides: `left`, `right`, `top`, and `bottom`.
  * Component pin definitions are canonical as side maps, not flat lists.
  * `PinRef` parses and represents strict `component.pin` references.
  * `NetDefinition` describes named nets exposed by any component. Non-terminal components validate net pin names against their physical pins. Terminal blocks can expose nets by position/pin expansion, and bus blocks expose common bus nets.

Parser decisions:
  * The parser reads yaml and validates top-level `config` and `components`.
  * `PanelConfig` stores `wire_label_format`, `wiring_mode`, defaults such as AWG, units, and visualization styles.
  * `UnitsConfig.length` accepts only `mm` or `in`.
  * `wiring_mode` accepts only `wires` or `labels`.
  * `VisualizationConfig` stores `default_net_style` and per-net `NetStyle` entries with `color`, `line_weight`, and `line_style`.
  * `ComponentParseResult` stores parsed components, the parsed config, and a NetworkX `component_pin_graph`.
  * The component-pin graph is a NetworkX `MultiGraph` containing one node per concrete `component.pin`.
  * Component-pin graph node attributes include component name, pin name, pin side, component type, exposed nets, component width, component height, and whether the pin belongs to a terminal-style component.

Wire routing decisions:
  * `WireRouter` is the stateful basis for wire routing.
  * `WireRouter.from_parse_result(...)` starts from the parsed component-pin graph.
  * `route_wire(...)` and `route_many(...)` resolve endpoints in input order and add physical wire edges to the NetworkX `MultiGraph`.
  * `ResolvedEndpoint` stores the requested endpoint, resolved concrete pin, exposed-net hint, and whether the pin was auto-selected.
  * `RoutedWire` stores routed physical wire details and preserves source/target endpoint metadata, optional wire-declared net name, resolved net name, generated wire label, and AWG.
  * If an endpoint names a concrete pin, route to that exact pin.
  * If an endpoint names a component-exposed net, select the next available concrete pin from that net.
  * Explicitly using a concrete pin that belongs to an exposed net consumes that pin for future auto-selection on that net.
  * Terminal block position bridges are added to the electrical model before named nets are resolved, so `1A` and `1B` on the same position are electrically common even when no named terminal net exists.
  * Component-declared nets on non-terminal components add internal electrical connectivity between the listed pins, allowing boards and connectors to export semantic nets without requiring a terminal-block type.
  * Explicit reuse of a concrete pin is allowed and produces multiple incident physical wire edges.
  * `PinRouteStatus` and `unrouted_pins(...)` expose routed/unrouted/NC status for component summaries and future file update operations.
  * Pins marked `NC` are physically unrouted but excluded from `unrouted_pins()` by default.
  * CLI file update operations are still a future step.

## Inspirations
We're bvulding somethign similar to WireViz, but with more focus on components and less on harnesses.


## Libraries and frameworks
* python 3
* I've started you in a project with a python virtual environment
* graphics: custom SVG renderer for static diagrams, plus a static SVG.js browser viewer for interactive exploration
* graph model: use NetworkX for the underlying physical wiring graph and net graph
* pretty printing: use tabular
* interface: command line
* cli file operations: the command line should support automatic operations on the input file, such as marking all currently unconnected pins as `NC`. Design this as a deliberate file update operation rather than an accidental side effect of report generation.
* unit testing: pytest
* files generated: graphics and .csv files suitable for dispaly in google sheets or excel
* debugging: use standard python logging
* output: print helpful stats as we process wires, so that as we 'wire it up' we can see whats happening. these events are needed:  
     1. assigning wire numbers
     2. selecting pins from terminal blocks automatically from next available
     3. extending a block 
* python project coding style-- editable package, using pyproject.toml

## Coding modules
We need to create separate modules, each one should be unit tested.  these are:
  * components. implemented first. Several types exist. Main functionality is exposing side-aware pins and nets, validating physical sizes, and exposing the next pin on a net when asked by the wire router.
  * parser. implemented for config and component trees. Reads yaml, creates typed components, and builds the component-pin NetworkX graph.
  * wire routing. implemented as the first routing layer. Manages endpoint resolution, auto-selection, routed wire state, physical wire edges, and unrouted pin queries.
  * nets. future module for understanding connected nets using the NetworkX net graph. later, will handle wire guages, signal type (AC, DC, signal)
  * reports/outputs. should be separte from models that store the state of the panel wiring. must be unit testable
  * visualization. implemented as custom SVG output using the routed model rather than owning the state.
  * viewer. implemented as a static SVG.js web app generated from the same routed model.
  * command line

# IMPORTANT: execution steps
We're not going to just 'sling the code'

* STEP1: review.  read my prompt and example, and ask relevant clarifying questions. compare prior art. look for other tools ( including WireViz) to find best practices I should consider
* STEP2: select dsl. Explore other dsls besides yaml What would a python dsl look like instead of yaml? is it better? are there others better?
* STEP3: select visualization. Completed. Use custom SVG for generated documentation and a static SVG.js web app for interactive viewing.
* STEP4: create core libs, including unit tests. all tests should pass. Completed for component models.
* STEP5: create rest of the project, and test. In progress:
  * STEP5a: parser for config/components and component-pin graph. Completed and unit tested.
  * STEP5b: NetworkX-backed wire routing basis, endpoint resolution, auto-selection, and unrouted pin listing. Completed and unit tested.
  * Visualization using the routed component-pin graph and side/size metadata is implemented. Next work should focus on polishing viewer interactions, richer layout persistence, and future CLI file update operations.
