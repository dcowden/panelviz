#include <Bounce2.h>

/*
  PanelViz run permissive controller for an Arduino Nano.

  Input convention for opto-board channels:
    HIGH = OK
    LOW  = fault / inactive / disconnected

  Reset button:
    Uses INPUT_PULLUP.
    LOW = pressed
    HIGH = released / disconnected

  AXBB-E O1 permission through a 4N26:
    A5 uses INPUT_PULLUP; collector (pin 5) to A5, emitter (pin 4) to Nano GND.
    LOW = charge-pump permission present; HIGH = absent / disconnected.
    This monitors AXBB-E's decoded O1 output, not a raw pulse train.
    See README.md for the isolated 24 V side and startup procedure.

  Relay boards:
    This sketch defaults to active-low relay modules because the prior
    machine sketch used LOW to close relay contacts.
*/

enum RunState {
  STATE_OFF,
  STATE_STARTING,
  STATE_RUN,
  STATE_FAULT
};

const uint8_t PIN_UL_X1_OK = 2;
const uint8_t PIN_UL_X2_OK = 3;
const uint8_t PIN_UL_Y_OK = 4;
const uint8_t PIN_UL_Z_OK = 5;

const uint8_t PIN_ALM_X1_OK = 6;
const uint8_t PIN_ALM_X2_OK = 7;
const uint8_t PIN_ALM_Y_OK = 8;
const uint8_t PIN_ALM_Z_OK = 9;

const uint8_t PIN_RUN_RELAY = 10;
const uint8_t PIN_UPPER_LIMITS_OK_RELAY = 11;
const uint8_t PIN_RESET = 12;
const uint8_t PIN_CHARGE_PUMP = A5;

const uint8_t RELAY_ON = LOW;
const uint8_t RELAY_OFF = HIGH;

const unsigned long DEBOUNCE_MS = 20;
const unsigned long STATUS_INTERVAL_MS = 2000;
const unsigned long SERIAL_BAUD = 115200;

RunState state = STATE_OFF;

Bounce ulX1 = Bounce();
Bounce ulX2 = Bounce();
Bounce ulY = Bounce();
Bounce ulZ = Bounce();

Bounce almX1 = Bounce();
Bounce almX2 = Bounce();
Bounce almY = Bounce();
Bounce almZ = Bounce();

Bounce resetButton = Bounce();
Bounce chargePump = Bounce();

// Startup may initially lack CP because I6 sees de-energized contactors.
// Once CP has appeared, losing it cancels this attempt even with reset held.
bool startupChargePumpSeen = false;

bool runRelayState = false;
bool upperLimitsRelayState = false;

unsigned long lastStatusTime = 0;

const char* stateName(RunState value) {
  switch (value) {
    case STATE_OFF:
      return "OFF";

    case STATE_STARTING:
      return "STARTING";

    case STATE_RUN:
      return "RUN";

    case STATE_FAULT:
      return "FAULT";

    default:
      return "UNKNOWN";
  }
}

void attachInput(Bounce& input, uint8_t pin, uint8_t mode = INPUT) {
  pinMode(pin, mode);
  input.attach(pin);
  input.interval(DEBOUNCE_MS);
}

void updateInputs() {
  ulX1.update();
  ulX2.update();
  ulY.update();
  ulZ.update();

  almX1.update();
  almX2.update();
  almY.update();
  almZ.update();

  resetButton.update();
  chargePump.update();
}

bool upperLimitsOk() {
  return ulX1.read() == HIGH &&
         ulX2.read() == HIGH &&
         ulY.read() == HIGH &&
         ulZ.read() == HIGH;
}

bool driverAlarmsOk() {
  return almX1.read() == HIGH &&
         almX2.read() == HIGH &&
         almY.read() == HIGH &&
         almZ.read() == HIGH;
}

bool resetPressed() {
  return resetButton.read() == LOW;
}

bool chargePumpOk() {
  return chargePump.read() == LOW;
}

void printOkFault(bool ok) {
  Serial.print(ok ? F("OK") : F("FAULT"));
}

void printPressedReleased(bool pressed) {
  Serial.print(pressed ? F("PRESSED") : F("RELEASED"));
}

void printStatus(const __FlashStringHelper* reason) {
  Serial.print(F("["));
  Serial.print(millis());
  Serial.print(F(" ms] "));
  Serial.println(reason);

  Serial.print(F("  State: "));
  Serial.println(stateName(state));

  Serial.print(F("  Upper limits: "));
  printOkFault(upperLimitsOk());
  Serial.print(F("  X1="));
  Serial.print(ulX1.read());
  Serial.print(F(" X2="));
  Serial.print(ulX2.read());
  Serial.print(F(" Y="));
  Serial.print(ulY.read());
  Serial.print(F(" Z="));
  Serial.println(ulZ.read());

  Serial.print(F("  Driver alarms: "));
  printOkFault(driverAlarmsOk());
  Serial.print(F("  X1="));
  Serial.print(almX1.read());
  Serial.print(F(" X2="));
  Serial.print(almX2.read());
  Serial.print(F(" Y="));
  Serial.print(almY.read());
  Serial.print(F(" Z="));
  Serial.println(almZ.read());

  Serial.print(F("  Charge-pump permission: "));
  printOkFault(chargePumpOk());
  Serial.print(F(" raw="));
  Serial.println(chargePump.read());

  Serial.print(F("  Reset: "));
  printPressedReleased(resetPressed());
  Serial.print(F(" raw="));
  Serial.println(resetButton.read());

  Serial.print(F("  Run relay: "));
  Serial.println(runRelayState ? F("ON") : F("OFF"));

  Serial.print(F("  Upper-limits relay: "));
  Serial.println(upperLimitsRelayState ? F("ON") : F("OFF"));
}

void setState(RunState newState, const __FlashStringHelper* reason) {
  if (newState == state) {
    return;
  }

  Serial.print(F("["));
  Serial.print(millis());
  Serial.print(F(" ms] State change: "));
  Serial.print(stateName(state));
  Serial.print(F(" -> "));
  Serial.print(stateName(newState));
  Serial.print(F(" | "));
  Serial.println(reason);

  state = newState;
}

void runRelay(bool on) {
  digitalWrite(PIN_RUN_RELAY, on ? RELAY_ON : RELAY_OFF);
  runRelayState = on;
}

void upperLimitsOkRelay(bool on) {
  digitalWrite(
    PIN_UPPER_LIMITS_OK_RELAY,
    on ? RELAY_ON : RELAY_OFF
  );
  upperLimitsRelayState = on;
}

void reportInputChanges() {
  if (ulX1.changed()) {
    Serial.print(F("UL X1 changed -> "));
    printOkFault(ulX1.read() == HIGH);
    Serial.println();
  }

  if (ulX2.changed()) {
    Serial.print(F("UL X2 changed -> "));
    printOkFault(ulX2.read() == HIGH);
    Serial.println();
  }

  if (ulY.changed()) {
    Serial.print(F("UL Y changed -> "));
    printOkFault(ulY.read() == HIGH);
    Serial.println();
  }

  if (ulZ.changed()) {
    Serial.print(F("UL Z changed -> "));
    printOkFault(ulZ.read() == HIGH);
    Serial.println();
  }

  if (almX1.changed()) {
    Serial.print(F("ALARM X1 changed -> "));
    printOkFault(almX1.read() == HIGH);
    Serial.println();
  }

  if (almX2.changed()) {
    Serial.print(F("ALARM X2 changed -> "));
    printOkFault(almX2.read() == HIGH);
    Serial.println();
  }

  if (almY.changed()) {
    Serial.print(F("ALARM Y changed -> "));
    printOkFault(almY.read() == HIGH);
    Serial.println();
  }

  if (almZ.changed()) {
    Serial.print(F("ALARM Z changed -> "));
    printOkFault(almZ.read() == HIGH);
    Serial.println();
  }

  if (resetButton.changed()) {
    Serial.print(F("RESET changed -> "));
    printPressedReleased(resetPressed());
    Serial.println();
  }

  if (chargePump.changed()) {
    Serial.print(F("CHARGE PUMP changed -> "));
    printOkFault(chargePumpOk());
    Serial.println();
  }
}

void setup() {
  // Establish OFF before serial initialization or any startup delay.
  // Set the output level before changing the pin to OUTPUT.
  digitalWrite(PIN_RUN_RELAY, RELAY_OFF);
  digitalWrite(PIN_UPPER_LIMITS_OK_RELAY, RELAY_OFF);
  pinMode(PIN_RUN_RELAY, OUTPUT);
  pinMode(PIN_UPPER_LIMITS_OK_RELAY, OUTPUT);

  Serial.begin(SERIAL_BAUD);
  delay(250);

  Serial.println();
  Serial.println(F("===================================="));
  Serial.println(F("PanelViz controller starting"));
  Serial.println(F("Serial debugging enabled at 115200"));
  Serial.println(F("===================================="));

  attachInput(ulX1, PIN_UL_X1_OK);
  attachInput(ulX2, PIN_UL_X2_OK);
  attachInput(ulY, PIN_UL_Y_OK);
  attachInput(ulZ, PIN_UL_Z_OK);

  attachInput(almX1, PIN_ALM_X1_OK);
  attachInput(almX2, PIN_ALM_X2_OK);
  attachInput(almY, PIN_ALM_Y_OK);
  attachInput(almZ, PIN_ALM_Z_OK);

  attachInput(resetButton, PIN_RESET, INPUT_PULLUP);
  attachInput(chargePump, PIN_CHARGE_PUMP, INPUT_PULLUP);

  // Allow inputs to settle and Bounce2 to read them.
  delay(DEBOUNCE_MS + 5);
  updateInputs();

  runRelay(false);
  upperLimitsOkRelay(false);

  printStatus(F("Initial status"));
  lastStatusTime = millis();
}

void loop() {
  updateInputs();

  bool ulOk = upperLimitsOk();
  bool almOk = driverAlarmsOk();
  bool reset = resetPressed();
  bool cpOk = chargePumpOk();
  RunState nextState = state;
  const __FlashStringHelper* reason = F("No state change");

  switch (state) {
    case STATE_OFF:
      // Only a new press can start. Held-at-boot or a rejected press is
      // never queued for later when a fault/permission recovers.
      if (resetButton.fell() && ulOk) {
        startupChargePumpSeen = cpOk;
        nextState = STATE_STARTING;
        reason = F("Fresh reset press; hold until alarms and CP are OK");
      }
      break;

    case STATE_STARTING:
      if (!ulOk) {
        nextState = STATE_FAULT;
        reason = F("Upper-limit permissive lost during startup");
      } else if (startupChargePumpSeen && !cpOk) {
        nextState = STATE_FAULT;
        reason = F("Charge-pump permission lost during startup");
      } else if (!reset) {
        nextState = STATE_OFF;
        reason = F("Reset released before startup completed");
      } else {
        startupChargePumpSeen = startupChargePumpSeen || cpOk;
        if (almOk && cpOk) {
          nextState = STATE_RUN;
          reason = F("Driver alarms and charge-pump permission are OK");
        }
      }
      break;

    case STATE_RUN:
      if (!ulOk) {
        nextState = STATE_FAULT;
        reason = F("Upper-limit permissive lost while running");
      } else if (!almOk) {
        nextState = STATE_FAULT;
        reason = F("Driver alarm detected while running");
      } else if (!cpOk) {
        nextState = STATE_FAULT;
        reason = F("Charge-pump permission lost while running");
      }
      break;

    case STATE_FAULT:
      if (!reset) {
        nextState = STATE_OFF;
        reason = F("Reset released; waiting for a fresh press");
      }
      break;

    default:
      nextState = STATE_FAULT;
      reason = F("Invalid controller state");
      break;
  }

  // Apply both outputs in the same iteration that recognizes a fault,
  // before diagnostics (Serial.print can block when its buffer is full).
  runRelay(nextState == STATE_STARTING || nextState == STATE_RUN);
  upperLimitsOkRelay(ulOk);
  setState(nextState, reason);
  reportInputChanges();

  if (millis() - lastStatusTime >= STATUS_INTERVAL_MS) {
    lastStatusTime = millis();
    printStatus(F("Periodic status"));
  }
}
