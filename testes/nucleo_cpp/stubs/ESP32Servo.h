#pragma once
#include "Arduino.h"
class ESP32PWM { public: static void allocateTimer(int) {} };
class Servo {
 public:
  void setPeriodHertz(int) {}
  void attach(int, int, int) { preso = true; }
  void detach() { preso = false; }
  void write(int g) { if (preso) ultimo = g; }
  bool preso = false;
  int ultimo = -1;
};
