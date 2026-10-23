#pragma once
#include "Arduino.h"
#define WIFI_STA 1
#define WL_CONNECTED 3
class WiFiClass {
 public:
  void mode(int) {}
  void begin(const char* ssid, const char* senha) { stub::wifi_ssid = ssid; stub::wifi_senha = senha; }
  int status() { return stub::wifi_conectado ? WL_CONNECTED : 0; }
  struct IP { String toString() const { return String("192.168.4.1"); } };
  IP localIP() { return IP(); }
};
extern WiFiClass WiFi;
