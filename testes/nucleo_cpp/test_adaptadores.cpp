// Teste HOST dos adaptadores do sketch (tarefa 3.8 / 3.1).
//
// Compila o .ino REAL com substitutos de Arduino/FreeRTOS. A tarefa de
// protecao roda em uma thread propria; o loop da aplicacao e retido por
// HTTP lento, LCD/I2C lento ou log serial lento por 6 s. O teste mede no
// registro de GPIO quando o rele foi desligado.
//
// Isto prova que o corte nao depende do loop retido NOS ADAPTADORES DESTE
// CODIGO. Nao mede o jitter J no ESP32-S3: escalonamento aqui e o do Windows.
#include <stdlib.h>

#include "Arduino.h"
#include "LiquidCrystal_I2C.h"
#include "WebServer.h"
#include "WiFi.h"
#include "Wire.h"

// ------------------------------------------------------------ substitutos
namespace stub {
std::mutex mtx;
std::vector<EventoPino> pinos;
std::atomic<int64_t> deslocamento_ms{0};
std::atomic<int> lento_http_ms{0}, lento_lcd_ms{0}, lento_serial_ms{0};
std::atomic<bool> falhar_tarefa{false};
std::atomic<bool> wifi_conectado{true};
std::string wifi_ssid, wifi_senha;
std::deque<char> serial_entrada;
std::vector<std::string> serial_saida;
static const auto inicio = std::chrono::steady_clock::now();
uint32_t agora_ms() {
  auto d = std::chrono::steady_clock::now() - inicio;
  return (uint32_t)(std::chrono::duration_cast<std::chrono::milliseconds>(d).count() + deslocamento_ms.load());
}
uint32_t agora_us() {
  auto d = std::chrono::steady_clock::now() - inicio;
  return (uint32_t)(std::chrono::duration_cast<std::chrono::microseconds>(d).count() + deslocamento_ms.load() * 1000);
}
void dormir(int ms) { std::this_thread::sleep_for(std::chrono::milliseconds(ms)); }
}  // namespace stub

static int nivel_pino[64];
void pinMode(int p, int) {
  std::lock_guard<std::mutex> g(stub::mtx);
  stub::pinos.push_back({stub::agora_ms(), p, -1, true});
}
void digitalWrite(int p, int n) {
  std::lock_guard<std::mutex> g(stub::mtx);
  nivel_pino[p & 63] = n;
  stub::pinos.push_back({stub::agora_ms(), p, n, false});
}
int digitalRead(int p) { return nivel_pino[p & 63]; }

HardwareSerial Serial;
int HardwareSerial::available() { std::lock_guard<std::mutex> g(stub::mtx); return (int)stub::serial_entrada.size(); }
int HardwareSerial::read() {
  std::lock_guard<std::mutex> g(stub::mtx);
  if (stub::serial_entrada.empty()) return -1;
  char c = stub::serial_entrada.front();
  stub::serial_entrada.pop_front();
  return c;
}
void HardwareSerial::print(const char* s) {
  int ms = stub::lento_serial_ms;
  if (ms > 0) stub::dormir(ms);
  std::lock_guard<std::mutex> g(stub::mtx);
  stub::serial_saida.push_back(s);
}
void HardwareSerial::println(const char* s) { print(s); }
void HardwareSerial::printf(const char* fmt, ...) {
  char b[256];
  va_list a;
  va_start(a, fmt);
  vsnprintf(b, sizeof b, fmt, a);
  va_end(a);
  print(b);
}

void vTaskDelayUntil(TickType_t* anterior, TickType_t periodo) {
  // Espera ativa curta: o sleep do Windows tem granularidade ~15 ms.
  TickType_t alvo = *anterior + periodo;
  while ((int32_t)(millis() - alvo) < 0) std::this_thread::yield();
  *anterior = alvo;
}

BaseType_t xTaskCreatePinnedToCore(void (*fn)(void*), const char*, uint32_t, void* arg, UBaseType_t,
                                   TaskHandle_t* handle, int) {
  if (stub::falhar_tarefa) return pdFAIL;
  std::thread(fn, arg).detach();
  if (handle) *handle = (TaskHandle_t)1;
  return pdPASS;
}

WiFiClass WiFi;
TwoWire Wire;

void WebServer::handleClient() {
  int ms = stub::lento_http_ms;
  if (ms > 0) stub::dormir(ms);  // cliente HTTP parcial/lento retendo o loop
  if (fila.empty()) return;
  atual_ = fila.front();
  fila.pop_front();
  for (auto& r : rotas_)
    if (r.uri == atual_.uri && (r.metodo == HTTP_ANY || r.metodo == atual_.metodo)) { r.h(); return; }
  send(404, "text/plain", "nao encontrado");
}
const String& WebServer::arg(const char* k) {
  auto it = atual_.args.find(k);
  arg_ = String(it == atual_.args.end() ? std::string() : it->second);
  return arg_;
}

// ------------------------------------------------------------ sketch real
#include "esp32s3_vigia_dualsense.ino"

// ------------------------------------------------------------ teste
static int falhas = 0;
#define CHECA(c, ...) do { if (!(c)) { printf("FALHA %s:%d: ", __FILE__, __LINE__); printf(__VA_ARGS__); printf("\n"); falhas++; } } while (0)

static std::vector<stub::EventoPino> eventos_rele() {
  std::lock_guard<std::mutex> g(stub::mtx);
  std::vector<stub::EventoPino> v;
  for (auto& e : stub::pinos) if (e.pino == PINO_RELE) v.push_back(e);
  return v;
}

static bool esperar_nivel(int nivel, uint32_t desde, uint32_t limite_ms, uint32_t* t) {
  uint32_t ini = millis();
  while (millis() - ini < limite_ms) {
    for (auto& e : eventos_rele())
      if (!e.modo && e.nivel == nivel && (int32_t)(e.t - desde) >= 0) { *t = e.t; return true; }
    std::this_thread::yield();
  }
  return false;
}

static void checar_inicializacao() {
  auto ev = eventos_rele();
  CHECA(ev.size() >= 2, "sem eventos do rele");
  if (ev.size() >= 2) {
    CHECA(!ev[0].modo && ev[0].nivel == RELE_DESLIGA, "primeira acao no rele deve ser nivel DESLIGA antes do pinMode");
    CHECA(ev[1].modo, "pinMode do rele deve vir depois do nivel seguro");
  }
  for (auto& e : ev) CHECA(e.modo || e.nivel == RELE_DESLIGA, "rele ligado durante a inicializacao");
}

static std::string ultima_serial() {
  std::lock_guard<std::mutex> g(stub::mtx);
  return stub::serial_saida.empty() ? std::string() : stub::serial_saida.back();
}

// Valor numerico de "chave":N no JSON (-1 se ausente ou null).
static long campo_num(const std::string& corpo, const char* chave) {
  std::string k = std::string("\"") + chave + "\":";
  size_t i = corpo.find(k);
  if (i == std::string::npos) return -1;
  i += k.size();
  if (corpo.compare(i, 4, "null") == 0) return -1;
  return strtol(corpo.c_str() + i, nullptr, 10);
}

int main(int argc, char** argv) {
  std::string modo = argc > 1 ? argv[1] : "http";
  if (modo == "falha") stub::falhar_tarefa = true;

  setup();
  if (modo == "ssid") {
    // Credenciais vem de segredos_wifi.h (gerado fora do Git) ou dos placeholders.
    printf("ssid=%s senha=%s\n", stub::wifi_ssid.c_str(), stub::wifi_senha.c_str());
    fflush(stdout);
    std::_Exit(0);
  }
  checar_inicializacao();

  // Uma requisicao HTTP real pelo adaptador.
  servidor.fila.push_back({"/status", HTTP_GET, {}});
  loop();
  CHECA(!servidor.respostas.empty(), "status sem resposta");
  if (!servidor.respostas.empty()) {
    auto& r = servidor.respostas.back();
    CHECA(r.codigo == 200, "status http %d", r.codigo);
    bool ok_esperado = modo != "falha";
    CHECA(r.corpo.find(ok_esperado ? "\"protecao_ok\":true" : "\"protecao_ok\":false") != std::string::npos,
          "protecao_ok inesperado: %s", r.corpo.c_str());
  }

  // Host de outro nome (DNS rebinding) e POST sem JSON declarado sao recusados.
  {
    WebServer::Pedido p{"/status", HTTP_GET, {}};
    p.host = "atacante.exemplo";
    servidor.fila.push_back(p);
    loop();
    CHECA(servidor.respostas.back().codigo == 421, "host estranho: %d", servidor.respostas.back().codigo);
    WebServer::Pedido q{"/api/v1/session", HTTP_POST, {{"plain", "{}"}}};
    servidor.fila.push_back(q);
    loop();
    CHECA(servidor.respostas.back().codigo == 415, "sem content-type: %d", servidor.respostas.back().codigo);
    q.headers["Content-Type"] = "application/json";
    servidor.fila.push_back(q);
    loop();
    CHECA(servidor.respostas.back().codigo == 400, "json aceito pela rota: %d", servidor.respostas.back().codigo);
  }

  stub::deslocamento_ms += 13000;  // passa a inibicao de boot sem esperar 12 s reais
  for (int i = 0; i < 5; i++) { loop(); stub::dormir(2); }

  if (modo == "falha") {
    {
      std::lock_guard<std::mutex> g(stub::mtx);
      stub::serial_entrada.push_back('B');
    }
    loop();
    CHECA(ultima_serial().find("protecao_indisponivel") != std::string::npos, "serial: %s", ultima_serial().c_str());
    stub::dormir(300);
    for (auto& e : eventos_rele()) CHECA(e.modo || e.nivel == RELE_DESLIGA, "rele ligou sem protecao");
    printf("modo=falha falhas=%d\n", falhas);
    fflush(stdout);
    std::_Exit(falhas ? 1 : 0);
  }

  // Retem o loop por 6 s no adaptador escolhido. LCD e log sao retidos na
  // propria iteracao que aceita o B (o LCD so redesenha quando o texto muda).
  if (modo == "lcd") { stub::lento_lcd_ms = 6000; stub::dormir(300); }
  if (modo == "serial") stub::lento_serial_ms = 6000;
  uint32_t pedido = millis();
  {
    std::lock_guard<std::mutex> g(stub::mtx);
    stub::serial_entrada.push_back('B');
  }
  uint32_t ini_retido = millis();
  loop();
  if (modo == "http") {
    stub::lento_http_ms = 6000;
    ini_retido = millis();
    loop();
  }
  uint32_t fim_retido = millis();
  stub::lento_http_ms = 0;
  stub::lento_lcd_ms = 0;
  stub::lento_serial_ms = 0;

  uint32_t t_on = 0;
  bool ligou = esperar_nivel(RELE_LIGA, pedido, 200, &t_on);
  CHECA(ligou, "rele nao energizou apos B");

  uint32_t t_off = 0;
  bool desligou = esperar_nivel(RELE_DESLIGA, t_on + 1, 50, &t_off);
  CHECA(fim_retido - ini_retido >= 5900, "loop nao ficou retido (%u ms)", (unsigned)(fim_retido - ini_retido));
  CHECA(desligou, "rele nao desligou");
  int32_t duracao = (int32_t)(t_off - t_on);
  CHECA(duracao >= 5000, "desligou cedo: %d ms", (int)duracao);
  CHECA(duracao <= 5000 + 50, "desligou tarde (host): %d ms", (int)duracao);
  CHECA((int32_t)(t_off - fim_retido) < 0, "corte so ocorreu depois de o loop voltar");

  for (int i = 0; i < 5; i++) { loop(); stub::dormir(2); }
  CHECA(!arbitro.em_combate(), "combate nao encerrou apos o corte");

  // Telemetria interna da protecao (/diag): medida pela propria tarefa.
  {
    servidor.fila.push_back({"/diag", HTTP_GET, {}});
    loop();
    auto& r = servidor.respostas.back();
    CHECA(r.codigo == 200, "diag http %d", r.codigo);
    long n = campo_num(r.corpo, "agua_n");
    long us = campo_num(r.corpo, "agua_ult_us");
    long liga = campo_num(r.corpo, "rele_ligado_em_ms");
    long desliga = campo_num(r.corpo, "rele_desligado_em_ms");
    CHECA(n == 1, "agua_n=%ld corpo=%s", n, r.corpo.c_str());
    CHECA(us >= 4990000 && us <= 5050000, "agua_ult_us=%ld", us);
    CHECA(campo_num(r.corpo, "agua_max_us") == us && campo_num(r.corpo, "agua_min_us") == us, "min/max: %s", r.corpo.c_str());
    CHECA(liga == (long)t_on && desliga == (long)t_off, "ligado/desligado %ld/%ld vs %u/%u", liga, desliga, (unsigned)t_on, (unsigned)t_off);
    CHECA(r.corpo.find("\"rele\":false") != std::string::npos, "rele: %s", r.corpo.c_str());
    CHECA(campo_num(r.corpo, "tick_max_gap_us") > 0, "tick_max_gap_us: %s", r.corpo.c_str());
    CHECA(campo_num(r.corpo, "ticks") > 1000, "ticks: %s", r.corpo.c_str());
    CHECA(campo_num(r.corpo, "t_inicio_ms") >= 0, "t_inicio_ms: %s", r.corpo.c_str());
    CHECA(r.corpo.find("\"led\":") != std::string::npos && r.corpo.find("\"servo_solto\":") != std::string::npos &&
              campo_num(r.corpo, "pan") >= 0,
          "led/servo_solto/pan: %s", r.corpo.c_str());

    WebServer::Pedido p{"/diag", HTTP_GET, {}};
    p.host = "atacante.exemplo";
    servidor.fila.push_back(p);
    loop();
    CHECA(servidor.respostas.back().codigo == 421, "diag host estranho: %d", servidor.respostas.back().codigo);

    // Zerar e feito pela propria tarefa (escritor unico das estatisticas).
    servidor.fila.push_back({"/diag", HTTP_GET, {{"zerar", "1"}}});
    loop();
    stub::dormir(20);
    servidor.fila.push_back({"/diag", HTTP_GET, {}});
    loop();
    CHECA(campo_num(servidor.respostas.back().corpo, "agua_n") == 0, "zerar: %s", servidor.respostas.back().corpo.c_str());
  }

  printf("modo=%s duracao_ms=%d J_host_ms=%d loop_retido_ms=%u falhas=%d\n", modo.c_str(), (int)duracao,
         (int)(duracao - 5000), (unsigned)(fim_retido - ini_retido), falhas);
  fflush(stdout);
  std::_Exit(falhas ? 1 : 0);
}
