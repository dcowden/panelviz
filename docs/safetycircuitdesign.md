# Safety Circuit Design

This panel uses the Arduino Nano as a small run-permissive controller, not as the primary emergency-stop device. The goal is to make the machine fail safe in all practical cases available with the installed hardware, while keeping the logic simple enough to inspect and troubleshoot.

## Objectives

- A physical E-stop must directly remove contactor coil power without depending on UCCNC, the AXBB-E, or Arduino code.
- The machine must require a deliberate reset press to start.
- The contactors must drop if any upper limit is tripped, disconnected, or unpowered.
- The contactors must drop if any monitored driver alarm is active, disconnected, or unpowered after startup.
- The contactor run relay must be energized-to-run, so Arduino power loss, relay-board power loss, or a stopped sketch opens the contactor coil return.
- The AXBB-E should observe status, not be responsible for interrupting power.
- The upper-limit status should be reported to AXBB-E input I1.
- The contactor coil energized state should be reported to AXBB-E input I6.
- Field inputs should pass through the AL-ZARD opto-isolated board so the Arduino sees a clean block of eight logic inputs with visible board LEDs for troubleshooting.

## Explicit Limitation

This design does not provide true EDM in the safety-relay sense because the installed contactors only provide 13/14 normally-open auxiliary contacts. True EDM normally uses normally-closed, mechanically-linked auxiliary contacts to prove the contactors have dropped out before allowing another reset.

The design therefore does not claim safety-relay equivalence. It is a practical hardwired/Arduino hybrid intended to fail safe for the available signals and hardware.

## Field Input Convention

The AL-ZARD opto board presents eight Arduino inputs:

| Arduino pin | Signal | OK state |
| --- | --- | --- |
| D2 | X1 upper limit OK | HIGH |
| D3 | X2 upper limit OK | HIGH |
| D4 | Y upper limit OK | HIGH |
| D5 | Z upper limit OK | HIGH |
| D6 | X1 driver alarm OK | HIGH |
| D7 | X2 driver alarm OK | HIGH |
| D8 | Y driver alarm OK | HIGH |
| D9 | Z driver alarm OK | HIGH |

For the PL-05NB upper-limit sensors, the expected behavior is 5V when clear and GND when tripped or disabled. Each sensor output drives an opto input so the Arduino reads HIGH only when the limit is clear.

For the ISV57T driver alarms, the manual describes low impedance between ALM+ and ALM- during normal operation and high impedance when protection activates. Each alarm contact is wired as a 5V opto input current loop so a driver alarm, disconnected wire, or unpowered driver produces a LOW input.

## Outputs

The Arduino drives two active-low relay-board inputs:

| Arduino pin | Relay | Purpose |
| --- | --- | --- |
| D10 | run relay | Closes the contactor coil return when the machine is allowed to run |
| D11 | upper-limits-ok relay | Reports upper-limit status to AXBB-E I1 |

The relay boards are active-low in the sketch because the previous machine sketch used LOW to close relay contacts.

The Arduino sketch uses the Bounce2 library for input debouncing. Install `Bounce2` from the Arduino IDE Library Manager before compiling the sketch.

Power the Nano from the regulated 5V bus using the `5V` pin and logic ground, not through `VIN`.

## Reset Behavior

The reset pushbutton is wired to Arduino D12 using the Nano internal pullup:

- released or disconnected = HIGH
- pressed = LOW

The Arduino state machine is:

1. OFF: run relay is open.
2. STARTING: reset is held and all upper limits are OK. The run relay closes, allowing the contactors to energize. Driver alarms are allowed to be not OK during this human-held startup phase.
3. RUN: once all driver alarms report OK, the run relay remains closed after reset is released.
4. FAULT: any upper-limit fault or driver alarm fault opens the run relay. Reset must be released before another start attempt.

This avoids a magic startup timer. The operator must hold reset until the drivers are powered and report OK.

## Contactor Coil Path

The contactor coil source is interrupted directly by the series E-stop contacts:

```text
24V -> primary E-stop NC -> secondary E-stop NC -> contactor A1 bus
```

The contactor coil return is controlled by the Arduino run relay:

```text
contactor A2 bus -> run relay NO contact -> 24V0
```

Because the run relay is energized-to-run, loss of Arduino power or 5V relay-board power opens the coil return and drops the contactors.

## AXBB-E Signals

AXBB-E I6 is wired across the contactor coil bus:

```text
I6+ -> contactor A1 bus
I6- -> contactor A2 bus
```

I6 therefore means the contactor coils are actually energized.

AXBB-E I1 is driven by the upper-limits-ok relay NC contact:

```text
24V -> I1+ -> I1- -> upper-limits-ok relay NC -> 24V0
```

When upper limits are OK, the relay is energized and the NC contact opens, so I1 is inactive. If an upper limit trips, Arduino power fails, or relay-board power fails, the relay de-energizes and I1 becomes active as an upper-limit fault indication.

## Reset Lamp

The reset lamp is wired through the run relay NC contact. It is on when 24V control power is available but the run relay is not energized, and off when the run relay has closed the contactor coil return.

## What Fails Safe

- E-stop open: contactor source power is removed.
- Arduino off or crashed: run relay de-energizes and contactors drop.
- 5V logic power lost: opto outputs and relays stop proving OK, contactors drop.
- Upper-limit sensor tripped or disconnected: upper-limit OK input goes LOW, run relay opens.
- Driver alarm active or alarm loop disconnected: driver OK input goes LOW, run relay opens after startup.
- Reset button wire broken: reset is not seen as pressed because the input uses INPUT_PULLUP.

## What Is Not Covered

- Welded contactor main contacts are not detected because no NC contactor auxiliary contacts are available for EDM.
- This is not a certified safety relay circuit.
- The Arduino and relay modules should be treated as machine-protection and run-permissive logic, while the physical E-stop contacts remain the hardwired emergency-stop authority.
