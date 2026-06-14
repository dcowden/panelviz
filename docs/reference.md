# YAML Reference

This page documents the supported PanelViz YAML fields. Examples are based on
the project file style used in `mycnc.yml`, but tests use small fixtures under
`tests/fixtures`.

## Top Level

```yaml
config: {}
components: {}
connections:
  wires: []
no_connects: []
```

`config` controls defaults, drawing metadata, labels, units, and visualization.
`components` defines all physical devices. `connections.wires` defines physical
wires and routes. `no_connects` lists intentionally unused `component.pin`
references.

## config

```yaml
config:
  wire_label_format: "%netname-%seq"
  wiring_mode: labels
  defaults:
    awg: 20
  drawing:
    company: ""
    author: ""
    title: "PanelViz Wiring Schematic"
  units:
    length: in
```

`wire_label_format`: String template for generated physical wire labels.
Supported placeholders are `%netname`, `%seq`, and `%{Nd}seq` where `N` is a
zero-padding width.

`wiring_mode`: `labels` or `wires`. `labels` draws short stubs and repeated wire
labels at both endpoints. `wires` draws direct wires.

`defaults.awg`: Positive integer default wire gauge.

`drawing.company`, `drawing.author`, `drawing.title`: Metadata used in drawing
PDF title blocks.

`units.length`: `in` or `mm`. Component `size.width` and `size.height` use this
unit unless a field has its own unit.

## labels

Printable wire-label PDF settings:

```yaml
labels:
  stock: premium_2_625x1_split
  style:
    font-family: Helvetica
    font-weight: bold
    color: "#000000"
  font_face: Helvetica
  font_height: 0.12
  font_height_unit: in
  left_margin: 0.1
  right_margin: 0.1
  page_margin: 0.3
  text_clearance: 2
  text_clearance_unit: pt
  tail_length: 0.75
  width_increment: 0.25
  whitespace: [1, 1.5, 2, 2.5]
```

`style`: CSS-like string map for label styling metadata.

`stock`: `freeform` or `premium_2_625x1_split`. `freeform` generates
cutter-friendly variable-width labels. `premium_2_625x1_split` targets
Premium Label Supply/Avery-compatible 2.625" x 1" 30-up address labels, and
prints two wire labels per sticker with a center cut line.

`font_face`: PDF font name.

`font_height`: Printed label text height.

`font_height_unit`: `in` or `pt`.

`left_margin`, `right_margin`: Minimum blank label space before and after the
wire text.

`page_margin`: US-letter page margin.

`text_clearance`: Clearance above the first stripe and below the last stripe.

`text_clearance_unit`: `in` or `pt`.

`tail_length`: Blank/unprinted label length, in inches, added below the printed
text stripes. This is useful for clear tape labels that wrap around the wire and
stick back onto themselves.

`width_increment`: Label widths are rounded up to this increment so cut lines
remain aligned.

`whitespace`: Multipliers for whitespace between repeated text stripes. The
label starts and ends with text, with these whitespace gaps between text runs.

## visualization

```yaml
visualization:
  terminal_width: 0.1
  terminal_width_unit: in
  default_net_style:
    color: "#576579"
    line_weight: 1.4
    line_style: solid
  net_styles:
    24V: {color: "#ff1111", line_weight: 2, line_style: solid}
    earth: {color: "#16a34a", line_weight: 2.5, line_style: solid}
```

`terminal_width`: Default rendered terminal width/depth.

`terminal_width_unit`: `in` or `mm`.

`default_net_style`: Style used for nets without a specific entry.

`net_styles`: Map of net names to styles. `color` is a CSS color string,
`line_weight` is numeric, and `line_style` is `solid`, `dashed`, or `dotted`.
Net names containing `earth` also use the earth style when no exact style exists.

## components

Each component is a mapping keyed by component name:

```yaml
contactor_110:
  type: switch
  tags: [vfd]
  size:
    width: 1.772
    height: 3.543
    terminal_width: 0.25
  pins:
    top: [L1, L2, L3, 13, A1]
    bottom: [T1, T2, T3, 14, A2]
```

`type`: Required. Valid values are `connector`, `switch`, `power_supply`,
`relay`, `driver`, `vfd`, `aviation_connector`, `terminal_block`, `bus_block`,
and `pcb`.

`tags`: Optional list of non-empty strings. Tags appear under component names in
diagrams and are combined into each wire-list row from both endpoint components.
They are useful for row filtering, such as `vfd`, `control`, `safety`, or
`dc_power`.

`size.width`, `size.height`: Positive physical dimensions in `config.units.length`.
For terminal blocks, `height` is the height of one position.

`size.terminal_width`: Optional positive override for the component's terminal
width/depth.

`size.terminal_width_unit`: Optional unit for `terminal_width`; valid values are
`in` and `mm`.

`pins`: Required side-to-pin map. Valid sides are `left`, `right`, `top`, and
`bottom`. Pin names are unique within a component.

## component nets

Normal components expose nets by pin:

```yaml
48v:
  type: power_supply
  pins:
    bottom: [GND, 110L, 110N, 48V0, 48V]
  nets:
    - {name: DRIVER_48V, pins: [48V]}
    - {name: DRIVER_GND, pins: [48V0]}
```

Multiple pins in the same net are electrically connected.

Terminal blocks expose nets by position:

```yaml
live_power_t:
  type: terminal_block
  pins:
    left: [A]
    right: [B]
  positions: 6
  nets:
    - name: 110L
      positions: [1, 3, 5]
```

For terminal blocks, every pin on a position is internally connected. With
`left: [A]` and `right: [B]`, position `1` creates `1A` and `1B`, and those two
pins are connected.

Bus blocks are terminal blocks whose net spans all positions unless positions are
specified:

```yaml
control_5v0:
  type: bus_block
  tags: [control]
  positions: 5
  pins:
    left: [A]
    right: [B]
  nets:
    - name: 5V0
```

## connections.wires

Short two-endpoint wire:

```yaml
- [y_cl57s.PUL+, axbb-e.YSTEP]
```

Long two-endpoint wire:

```yaml
- from: wall_plug.1
  to: live_power_t.110L
  net: 110L
  awg: 12
```

Multi-hop route:

```yaml
- route: [vfd.R, contactor_220.L1, transformer.220L]
  net: VFD_220L
  awg: 16
```

Fields:

`from`, `to`: Endpoint references in `component.pin` form.

`route`: List of two or more endpoints. Adjacent endpoints become physical
wires, and all segments share the same net.

`net`: Optional explicit net name. If omitted, PanelViz uses exposed component
nets when available or derives a net from the first wire endpoint.

`awg`: Optional positive integer wire gauge. Defaults to `config.defaults.awg`.

Endpoint references may target an exposed component net instead of a concrete
pin. For example, `live_power_t.110L` auto-selects the next available concrete
terminal on that net.

## no_connects

```yaml
no_connects:
  - axbb-e.O1
  - axbb-e.O17
```

Each item must be a concrete `component.pin` reference. Marking a pin as NC
suppresses the unconnected warning and draws the no-connect marker in diagrams.

## Sidecar Layout

Interactive component positions and rotations live in a separate sidecar file
next to the input YAML:

```text
mycnc.layout.yml
```

The sidecar is intentionally layout-only. Wiring, components, and nets remain in
the main YAML file.

## Sidecar Labels

Final wire labels can be assigned from the app with `Assign Labels`. The app
saves a sidecar file next to the input YAML:

```text
mycnc.labels.yaml
```

Shape:

```yaml
source: mycnc.yml
component_order: [wall_plug, live_power_t, transformer]
wires:
  - key: row:0:segment:0
    label: 110L-1
    net: 110L
    from: wall_plug.1
    to: live_power_t.1A
    assigned_component: wall_plug
```

`component_order`: The order used when assigning final labels.

`wires[].key`: Stable source-route key for a physical wire segment.

`wires[].label`: Final printable wire label.

`wires[].net`, `from`, `to`: Human-readable context for reviewing the sidecar.

`assigned_component`: The component whose processing step first assigned this
wire label.

When this sidecar exists, PanelViz uses it for the interactive wire list, CSV
exports, schematic PDFs, wire-list PDFs, and CLI-generated reports. The main YAML
continues to describe the design by components, nets, and routes.

`Assign Labels` and drawing PDF exports also create pure wire-label PDFs using
the configured label stock. `all_labels.pdf` is a multi-page PDF containing two
labels for every physical wire, sorted alphabetically with matching labels
together. Tag-oriented PDFs named `wirelabel_<tag>.pdf` contain no component
diagrams. Tag labels are sorted by net and then by wire label. For each physical
wire, every endpoint tag receives two copies of the wire label, including wires
that span multiple tags.
