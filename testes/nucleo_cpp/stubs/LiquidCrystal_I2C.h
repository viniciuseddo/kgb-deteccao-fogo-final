#pragma once
#include "Arduino.h"
class LiquidCrystal_I2C {
 public:
  LiquidCrystal_I2C(int, int, int) {}
  void init() {}
  void backlight() {}
  void setCursor(int, int) {}
  void print(const char*) { int ms = stub::lento_lcd_ms; if (ms > 0) stub::dormir(ms); }
};
