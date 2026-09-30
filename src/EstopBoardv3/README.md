# Nano run permissive: option 1 with isolated charge-pump input

This sketch targets the classic 5 V ATmega328P Nano and uses Bounce2.
Existing D2-D12 wiring stays in place. A5 is the new charge-pump permission
input, configured as **INPUT_PULLUP**. No external 10 kOhm pull-up is needed.

## 4N26 connections

| 4N26 pin | Connection |
| --- | --- |
| 1, LED anode | Unswitched control +24 V through a **2.2 kOhm, 0.5 W** resistor |
| 2, LED cathode | AXBB-E **O1 / CHP** |
| 3 | Leave unconnected |
| 4, emitter | Nano GND / 5V0 |
| 5, collector | Nano **A5** |
| 6, base | Leave unconnected |

The LED series resistor is still required; the Nano pull-up only replaces
the resistor on the transistor side. Do not bond 24V0 to 5V0 through this
interface. Keep the A5/emitter leads short and route them away from motor wiring.
Check the package notch/dot against the manufacturer's top-view pinout.

O1 is a sinking output with an onboard charge-pump detector. Its terminal
provides a steady permission state while the controller's charge-pump stream
is present. The Nano therefore reads a level, rather than counting pulses.
With this wiring, **A5 LOW = permission present**, **A5 HIGH = absent/open wire**.
Sources: [AXBB-E manual, sections 8.3 and 9.1](https://www.cncdrive.com/downloads/AXBB_E_manual.pdf),
[4N26 datasheet](https://www.vishay.com/docs/83725/4n25.pdf).

## UCCNC prerequisite

Configure the charge-pump output for **Port 1, Pin 1 (O1 / CHP)**. Leave
**Charge pump always on** disabled so UCCNC Reset removes permission. Preserve
I6 as the existing coil-voltage E-stop input. The repository's saved
`docs/UCCNC-config.pro` has the charge pump disabled (port/pin zero); changing
this sketch does not change the live UCCNC configuration or that saved profile.

Before relying on the interlock, verify that A5 reads HIGH when UCCNC enters
Reset or loses its connection, and LOW when the charge pump is active.

## Startup and restart

1. Release the physical reset button. Power-up always starts OFF; a button
   already held at boot cannot start the controller.
2. With all upper limits healthy, press and **hold** physical reset. The Nano
   closes the run relay while temporarily tolerating driver alarms and absent
   charge-pump permission. Energized coils then clear the I6 input condition.
3. While holding physical reset, clear UCCNC Reset. Wait for charge-pump
   permission and all four driver-alarm inputs to become healthy. Only then
   does the Nano latch RUN; Serial Monitor at 115200 baud reports the transition.
4. Release physical reset. Releasing before RUN cancels startup.

Upper limits are never bypassed. Once charge-pump permission has been observed
during a startup attempt, losing it aborts that attempt even if reset stays
held. In RUN, any upper-limit, driver-alarm, or charge-pump fault drops the
run relay and requires a fresh physical reset press. Restoring a signal alone
cannot restart it. A press made with an upper-limit fault is not queued for
later when that fault clears.

The upper-limit relay remains independent: energized when all upper limits
are healthy, including while the run relay is OFF. Both relay outputs retain
their existing active-low polarity. Inputs use the existing 20 ms stable-state
debounce; output changes occur in the fault-recognition loop before serial
diagnostics. Total physical stopping delay also includes polling, UCCNC,
the O1 detector, and relay/contactor response.

## Scope of the startup bypass

Before charge-pump permission first appears, held reset intentionally allows
energized coils without UCCNC permission and has no timeout. During this window
the Nano cannot independently observe an E-stop: releasing a physical E-stop
while still holding reset can restore coil power. Release reset to cancel.
The physical E-stops must retain their direct series interruption of coil power.
This software change does not provide protection against a stuck Nano output,
a shorted optocoupler output, or welded relay contacts.

## Verification before operating the machine

With machine motion made safe, verify a normal held-reset startup, early
reset release, each upper limit and driver alarm, physical E-stop press/release,
UCCNC Reset, and UCCNC disconnection. After a running-state fault, verify that
restoring the signal never energizes the run relay without a fresh reset press;
repeat with reset held through the fault. Disconnect the A5 signal wire while
running and verify shutdown through the internal pull-up. Test the startup
bypass behavior above explicitly.

The automated host tests execute this sketch with the real Bounce2 library
and simulated electrical pins/time. They do not verify the physical wiring,
UCCNC configuration, or contactor timing:

```text
python tests/firmware/run_tests.py --bounce-dir <Bounce2-library>/src
```

Run from a C++ compiler environment (MSVC Developer Command Prompt on Windows,
or with `c++` on PATH). Build/upload the sketch with the Arduino IDE using
the actual Nano processor/bootloader selection. This update does not upload it.
