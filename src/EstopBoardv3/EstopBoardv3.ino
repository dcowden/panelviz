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

const uint8_t RELAY_ON = LOW;
const uint8_t RELAY_OFF = HIGH;
const unsigned long DEBOUNCE_MS = 20;

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

void runRelay(bool on) {
  digitalWrite(PIN_RUN_RELAY, on ? RELAY_ON : RELAY_OFF);
}

void upperLimitsOkRelay(bool on) {
  digitalWrite(PIN_UPPER_LIMITS_OK_RELAY, on ? RELAY_ON : RELAY_OFF);
}

void setup() {
  digitalWrite(PIN_RUN_RELAY, RELAY_OFF);
  digitalWrite(PIN_UPPER_LIMITS_OK_RELAY, RELAY_OFF);
  pinMode(PIN_RUN_RELAY, OUTPUT);
  pinMode(PIN_UPPER_LIMITS_OK_RELAY, OUTPUT);

  attachInput(ulX1, PIN_UL_X1_OK);
  attachInput(ulX2, PIN_UL_X2_OK);
  attachInput(ulY, PIN_UL_Y_OK);
  attachInput(ulZ, PIN_UL_Z_OK);

  attachInput(almX1, PIN_ALM_X1_OK);
  attachInput(almX2, PIN_ALM_X2_OK);
  attachInput(almY, PIN_ALM_Y_OK);
  attachInput(almZ, PIN_ALM_Z_OK);

  attachInput(resetButton, PIN_RESET, INPUT_PULLUP);

  updateInputs();
  runRelay(false);
  upperLimitsOkRelay(false);
}

void loop() {
  updateInputs();

  bool ulOk = upperLimitsOk();
  bool almOk = driverAlarmsOk();
  bool reset = resetPressed();

  upperLimitsOkRelay(ulOk);

  switch (state) {
    case STATE_OFF:
      runRelay(false);

      if (reset && ulOk) {
        state = STATE_STARTING;
      }
      break;

    case STATE_STARTING:
      if (!ulOk) {
        state = STATE_FAULT;
        break;
      }

      if (!reset && !almOk) {
        state = STATE_OFF;
        break;
      }

      runRelay(true);

      if (almOk) {
        state = STATE_RUN;
      }
      break;

    case STATE_RUN:
      if (!ulOk || !almOk) {
        state = STATE_FAULT;
        break;
      }

      runRelay(true);
      break;

    case STATE_FAULT:
      runRelay(false);

      if (!reset) {
        state = STATE_OFF;
      }
      break;
  }
}
