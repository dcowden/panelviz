// Runs the actual sketch and real Bounce2; only electrical I/O and time are fake.
#include "Arduino.h"
#include <algorithm>
#include <cstdlib>
#include <iostream>
#include <stdexcept>

unsigned long testMillis = 0;
int levels[32], modes[32], outputs[32];
std::vector<std::string> events;
TestSerial Serial;
#include "../../src/EstopBoardv3/EstopBoardv3.ino"

void require(bool condition, const char* message) {
  if (!condition) throw std::runtime_error(message);
}
void tick(unsigned long ms = 1) { testMillis += ms; loop(); }
void settle() { tick(); tick(20); tick(); }
void drive(int pin, int value) { levels[pin] = value; settle(); }
void relay(bool want) {
  require(outputs[10] == (want ? LOW : HIGH), want ? "run relay should be ON" : "run relay should be OFF");
}
void boot(bool resetHeld = false) {
  std::fill(levels, levels + 32, -1);
  for (int pin = 2; pin <= 9; ++pin) levels[pin] = HIGH;
  levels[12] = resetHeld ? LOW : HIGH;
  setup(); settle();
}
void startRunning() {
  drive(12, LOW); relay(true);
  drive(A5, LOW);
  drive(12, HIGH); relay(true);
}
void faultBeforeLogging(int pin, int level) {
  levels[pin] = level;
  tick(); // Bounce2 starts its stable-interval timer.
  events.clear();
  tick(20); // Fault must remove power on this iteration, before serial logging.
  relay(false);
  const auto off = std::find(events.begin(), events.end(), "write:10:1");
  const auto log = std::find(events.begin(), events.end(), "serial");
  require(off != events.end() && off < log, "fault output must precede diagnostics");
}
int main(int argc, char** argv) {
  if (argc < 2) return 2;
  const std::string name = argv[1];
  try {
    if (name == "held_at_boot") {
      boot(true); relay(false);
      drive(12, HIGH); relay(false);
      drive(12, LOW); relay(true);
    } else {
      boot(); relay(false);
      if (name == "disconnected_cp_cannot_latch") {
        drive(12, LOW); relay(true);
        drive(12, HIGH); relay(false);
      } else if (name == "cp_before_alarms") {
        drive(6, LOW); drive(12, LOW); relay(true);
        drive(A5, LOW); relay(true);
        drive(6, HIGH); drive(12, HIGH); relay(true);
      } else if (name == "alarms_before_cp") {
        drive(12, LOW); relay(true);
        drive(A5, LOW); drive(12, HIGH); relay(true);
      } else if (name == "release_with_alarm") {
        drive(6, LOW); drive(12, LOW); drive(A5, LOW);
        drive(12, HIGH); relay(false);
        drive(6, HIGH); relay(false);
      } else if (name == "cp_loss_during_start") {
        drive(6, LOW); drive(12, LOW); drive(A5, LOW); relay(true);
        faultBeforeLogging(A5, -1);
        drive(A5, LOW); drive(6, HIGH); relay(false);
        drive(12, HIGH); relay(false);
        drive(12, LOW); relay(true);
      } else if (name == "blocked_press_not_queued") {
        drive(2, LOW); drive(12, LOW); relay(false);
        drive(2, HIGH); relay(false);
        drive(12, HIGH); drive(12, LOW); relay(true);
      } else if (name == "upper_limit_during_start") {
        drive(6, LOW); drive(12, LOW); relay(true);
        faultBeforeLogging(2, LOW);
        drive(2, HIGH); drive(6, HIGH); drive(A5, LOW); relay(false);
      } else if (name == "cp_fault_needs_fresh_press") {
        startRunning(); faultBeforeLogging(A5, -1);
        drive(A5, LOW); relay(false);
        drive(12, LOW); relay(true);
        drive(12, HIGH); relay(true);
      } else if (name == "held_reset_cannot_retry") {
        drive(12, LOW); drive(A5, LOW); relay(true);
        faultBeforeLogging(A5, -1);
        drive(A5, LOW); relay(false);
        settle(); relay(false);
        drive(12, HIGH); relay(false);
        drive(12, LOW); relay(true);
      } else if (name == "fault_each_input") {
        require(argc == 3, "fault pin required");
        startRunning();
        const int pin = std::atoi(argv[2]);
        faultBeforeLogging(pin, LOW);
        drive(pin, HIGH); relay(false);
      } else if (name == "cp_noise_debounce") {
        startRunning();
        levels[A5] = -1; tick(); tick(19); relay(true);
        levels[A5] = LOW; settle(); relay(true);
        faultBeforeLogging(A5, -1);
      } else if (name == "upper_relay_independent") {
        require(outputs[11] == LOW, "healthy upper relay should be ON even when stopped");
        drive(2, LOW);
        require(outputs[11] == HIGH, "upper relay should turn OFF on upper fault");
      } else {
        throw std::runtime_error("unknown scenario");
      }
    }
    std::cout << "PASS " << name << '\n';
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "FAIL " << name << ": " << error.what() << '\n';
    return 1;
  }
}
