#pragma once
#include <cstdint>
#include <string>
#include <vector>

#define HIGH 1
#define LOW 0
#define INPUT 0
#define OUTPUT 1
#define INPUT_PULLUP 2
#define A0 14
#define A5 19
class __FlashStringHelper;
#define F(s) reinterpret_cast<const __FlashStringHelper *>(s)

extern unsigned long testMillis;
extern int levels[32]; // -1 means disconnected; INPUT_PULLUP supplies HIGH.
extern int modes[32];
extern int outputs[32];
extern std::vector<std::string> events;
inline unsigned long millis() { return testMillis; }
inline void delay(unsigned long ms) { testMillis += ms; }
inline void pinMode(int pin, int mode) { modes[pin] = mode; }
inline int digitalRead(int pin) {
  return levels[pin] < 0 ? (modes[pin] == INPUT_PULLUP ? HIGH : LOW) : levels[pin];
}
inline void digitalWrite(int pin, int value) {
  outputs[pin] = value;
  events.push_back("write:" + std::to_string(pin) + ":" + std::to_string(value));
}
struct TestSerial {
  void begin(unsigned long) {}
  template<class T> void print(T) { events.push_back("serial"); }
  template<class T> void println(T) { events.push_back("serial"); }
  void println() { events.push_back("serial"); }
};
extern TestSerial Serial;
