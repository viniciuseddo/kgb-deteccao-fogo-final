// Substitutos HOST das APIs Arduino/ESP32/FreeRTOS usadas pelo sketch.
// Servem SOMENTE para testar os adaptadores do .ino com g++. Nao sao um
// emulador do ESP32: escalonamento, prioridades e tempos aqui sao do SO host.
#pragma once
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include <atomic>
#include <chrono>
#include <deque>
#include <functional>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

typedef uint8_t byte;
#define HIGH 1
#define LOW 0
#define INPUT 0x01
#define OUTPUT 0x03
#define F(x) (x)

namespace stub {
struct EventoPino { uint32_t t; int pino; int nivel; bool modo; };
extern std::mutex mtx;
extern std::vector<EventoPino> pinos;
extern std::atomic<int64_t> deslocamento_ms;
extern std::atomic<int> lento_http_ms, lento_lcd_ms, lento_serial_ms;
extern std::atomic<bool> falhar_tarefa;
extern std::atomic<bool> wifi_conectado;
extern std::string wifi_ssid, wifi_senha;
extern std::deque<char> serial_entrada;
extern std::vector<std::string> serial_saida;
uint32_t agora_ms();
uint32_t agora_us();
void dormir(int ms);
}  // namespace stub

inline unsigned long millis() { return stub::agora_ms(); }
inline unsigned long micros() { return stub::agora_us(); }
inline void delay(unsigned long ms) { stub::dormir((int)ms); }
void pinMode(int pino, int modo);
void digitalWrite(int pino, int nivel);
int digitalRead(int pino);
inline uint32_t esp_random() { return 0xA5A55A5Au; }

class String {
 public:
  String() {}
  String(const char* s) : s_(s ? s : "") {}
  String(const std::string& s) : s_(s) {}
  const char* c_str() const { return s_.c_str(); }
  unsigned length() const { return (unsigned)s_.size(); }
  char charAt(unsigned i) const { return i < s_.size() ? s_[i] : '\0'; }
  bool operator==(const String& o) const { return s_ == o.s_; }
  bool operator!=(const String& o) const { return s_ != o.s_; }
  String operator+(const char* o) const { return String(s_ + o); }
  bool startsWith(const char* p) const { return s_.rfind(p, 0) == 0; }
 private:
  std::string s_;
};

class HardwareSerial {
 public:
  void begin(unsigned long) {}
  int available();
  int read();
  void print(const char* s);
  void print(const String& s) { print(s.c_str()); }
  void println(const char* s);
  void println(const String& s) { println(s.c_str()); }
  void println() { println(""); }
  void printf(const char* fmt, ...);
};
extern HardwareSerial Serial;

// ------------------------------------------------------------ FreeRTOS
typedef void* TaskHandle_t;
typedef int BaseType_t;
typedef unsigned UBaseType_t;
typedef uint32_t TickType_t;
#define pdPASS 1
#define pdFAIL 0
#define configMAX_PRIORITIES 25
#define pdMS_TO_TICKS(x) ((TickType_t)(x))
inline TickType_t xTaskGetTickCount() { return (TickType_t)millis(); }
void vTaskDelayUntil(TickType_t* anterior, TickType_t periodo);
BaseType_t xTaskCreatePinnedToCore(void (*fn)(void*), const char* nome, uint32_t pilha, void* arg,
                                   UBaseType_t prioridade, TaskHandle_t* handle, int nucleo);
