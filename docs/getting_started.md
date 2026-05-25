# Getting Started

PanelViz turns a YAML panel description into wiring documentation and a local
browser UI. The normal workflow is to type components in YAML, then use the UI
to inspect the panel, move components, export PDFs/CSV files, and optionally add
or edit wires.

## Install

From the project root:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

Run tests with:

```powershell
.\run_tests.cmd
```

## Launch The App

Run the local PanelViz app against a YAML file:

```powershell
panelviz mycnc.yml
```

The app binds to `127.0.0.1` and defaults to port `8769`. To choose a port or
avoid opening a browser automatically:

```powershell
panelviz --port 8780 --no-open mycnc.yml
```

The app starts in view-only mode. Click `Enable Edit` before creating routes,
deleting wires, relocating wire endpoints, moving components, or rotating
components. The `?` button in the toolbar lists the mouse and keyboard controls.

## Minimal File Shape

A PanelViz file needs `components` and usually `connections`. `config` is
optional, but most useful files define units and a wire naming format.

```yaml
config:
  wire_label_format: "%netname-%seq"
  wiring_mode: labels
  defaults:
    awg: 20
  units:
    length: in

components:
  wall_plug:
    type: connector
    tags: [vfd]
    size:
      width: 0.95
      height: 0.95
      terminal_width: 0.25
    pins:
      right: [GND, 1, 2]

  live_power_t:
    type: terminal_block
    tags: [vfd]
    size:
      width: 0.236
      height: 0.118
    pins:
      left: [A]
      right: [B]
    positions: 6
    nets:
      - name: 110L
        positions: [1, 3, 5]
      - name: 110N
        positions: [2, 4, 6]

connections:
  wires:
    - {from: wall_plug.1, to: live_power_t.110L, net: 110L, awg: 12}
    - [wall_plug.2, live_power_t.110N]

no_connects:
  - wall_plug.GND
```

## Naming Rules

Every pin reference uses `component.pin`. Component names and pin names are
case-sensitive, so `axbb-e.O2` and `axbb-e.o2` are different.

Physical wire labels must be unique. PanelViz generates them from
`config.wire_label_format`. The common format is:

```yaml
wire_label_format: "%netname-%seq"
```

This creates labels such as `110L-1`, `110L-2`, and `earth-1`. `%seq` is the
sequence for that net when `%netname` is present. Use `%{5d}seq` for zero-padded
numbers such as `00001`.

## Nets

Nets may come from three places:

- A connection row with `net: NAME`.
- A component `nets` entry that maps one or more pins to a named net.
- A terminal block or bus block `nets` entry that maps positions to a named net.

For normal components, list pins:

```yaml
axbb-e:
  type: driver
  pins:
    left: [O1, O2, O3]
  nets:
    - {name: VFD_REV, pins: [O2]}
```

For terminal blocks, list positions. Every side of the same position is
electrically connected, so position `1` means `1A` is connected to `1B`.

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

## Connections

Short syntax is best for ordinary wires:

```yaml
- [z_motor.zma+, cnc_terminals.1A]
```

Long syntax is useful when you want to assign a net name or wire gauge:

```yaml
- from: wall_plug.1
  to: live_power_t.110L
  net: 110L
  awg: 12
```

Use `route` for multi-hop routes. Each adjacent pair becomes one physical wire:

```yaml
- route: [vfd.R, contactor_220.L1, transformer.220L]
  net: VFD_220L
  awg: 16
```

For terminal-block pass-through routing, use the bare position when you mean
"enter side A and leave side B":

```yaml
- [z_motor.zma+, cnc_terminals.1, y_cl57s.EB+]
```

Use a concrete side such as `cnc_terminals.1A` when multiple wires should land on
the same terminal side.

## No-Connects

Use top-level `no_connects` for pins that are intentionally unused. PanelViz
will not warn about those pins as unconnected.

```yaml
no_connects:
  - axbb-e.O1
  - axbb-e.O17
```

## Outputs

The app can download:

- wire list CSV
- schematic PDF
- wire list PDF with diagram references
- per-tag wire-label PDFs

The programmatic `panelviz.cli.run()` function can also write CSV, text, SVG,
and PDF outputs to a selected directory.
