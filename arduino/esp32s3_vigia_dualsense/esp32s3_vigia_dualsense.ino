/*
  Projeto Sompo / grupo KGB - Deteccao de fogo
  VIGIA DUALSENSE: variante opt-in do esp32s3_vigia_bomba

  O sketch original (arduino/esp32s3_vigia_bomba) NAO foi alterado e continua
  sendo a referencia validada e o rollback. Esta variante:

    - separa modo-base AUTO/MANUAL da acao de agua (combate);
    - move o PAN sem laco bloqueante (alvo/angulo/velocidade separados);
    - tem lease manual de 1500 ms no relogio local (watchdog);
    - entrega o rele a UMA tarefa FreeRTOS de protecao, de prioridade acima de
      HTTP/LCD/log, que e a unica a escrever no GPIO e corta a agua em
      5000 ms + J desde a energizacao (J a medir no S3; meta J <= 10 ms);
    - aplica cooldown de 12 s entre inicios e 12 s de inibicao apos
      cancelamento e apos o boot, para TODAS as origens (HTTP novo, /cmd, serial);
    - oferece POST /api/v1/session e POST /api/v1/command (JSON estrito,
      boot/sessao/seq/id, janelas de frescor emitidas pelo S3, RECUPERACAO);
    - mantem /status com pan/vigiando/fogo/bomba e acrescenta campos.

  PERFIS
    COMPAT    (do boot ate a 1a sessao protegida): letras legadas V L C R 4 6
              F X B H com a semantica documentada, MAS sujeitas ao guardiao:
              F/B repetidos nao reiniciam o timer, respeitam cooldown/inibicao;
              mover durante a agua e recusado sem alterar o alvo.
    PROTEGIDO (apos a 1a sessao protegida, ate o proximo reboot): letras que
              movem, ligam/cortam agua ou trocam modo sao recusadas (403),
              inclusive depois de o lease expirar. H e /status continuam.

  NAO E PARADA DE EMERGENCIA. Cancelar pela rede nao tem prazo fisico
  garantido. Travamento total do MCU, tempo do rele e vazao exigem corte
  eletrico e ensaio de bancada. A rede HTTP nao tem autenticacao: use somente
  em rede local confiavel.

  LIGACOES, ALIMENTACAO E RELE: iguais ao sketch original (PAN GPIO 4,
  rele GPIO 7, LED GPIO 6, LCD I2C SDA 8 / SCL 9). Confirme o modelo da placa
  antes de gravar; estes pinos supoem a ESP32-S3-N16R8 do projeto.
*/

#include <WiFi.h>
#include <WebServer.h>
#include <Wire.h>
#include <LiquidCrystal_I2C.h>
#include <ESP32Servo.h>
#include <atomic>

#include "vigia_config.h"
#include "vigia_protecao.h"
#include "vigia_arbitro.h"

// ---------------------------------------------------------------
#if __has_include("segredos_wifi.h")
#include "segredos_wifi.h"
#endif

#ifndef VIGIA_WIFI_SSID
#define VIGIA_WIFI_SSID "COLOQUE_O_NOME_DA_REDE"
#endif

#ifndef VIGIA_WIFI_SENHA
#define VIGIA_WIFI_SENHA "COLOQUE_A_SENHA"
#endif

const char *SSID  = VIGIA_WIFI_SSID;
const char *SENHA = VIGIA_WIFI_SENHA;
// ---------------------------------------------------------------

const byte PINO_PAN  = 4;
const byte PINO_LED  = 6;
const byte PINO_RELE = 7;
const byte PINO_SDA  = 8;
const byte PINO_SCL  = 9;

// Mesmo nivel do original: modulo com optoacoplador aciona em BAIXO.
const byte RELE_LIGA    = LOW;
const byte RELE_DESLIGA = HIGH;

// Tarefa de protecao: nucleo 1 (o do loop), acima da prioridade do loop.
const UBaseType_t PRIORIDADE_PROTECAO = configMAX_PRIORITIES - 5;
const uint32_t PILHA_PROTECAO = 3072;

#define GRAU 223

LiquidCrystal_I2C lcd(0x27, 16, 2);
WebServer servidor(80);
Servo servoPan;
bool wifiOk = false;
String ipLocal;  // Host aceito nas requisicoes (anti DNS rebinding)

// ------------------------------------------------------------ rele
// Escrita direta de GPIO, sem bloqueio. ler() devolve o nivel COMANDADO
// (sombra), nao uma medicao do contato do rele: nao ha realimentacao fisica.
class ReleGPIO : public vigia::SaidaRele {
 public:
  void escrever(bool ligado) override {
    digitalWrite(PINO_RELE, ligado ? RELE_LIGA : RELE_DESLIGA);
    bool anterior = comandado_.exchange(ligado, std::memory_order_relaxed);
    uint32_t agora_us = micros();
    uint32_t agora_ms = millis();
    if (ligado && !anterior) {
      t_on_us_.store(agora_us, std::memory_order_relaxed);
      t_on_ms_.store(agora_ms, std::memory_order_relaxed);
    } else if (!ligado && anterior) {
      t_off_us_.store(agora_us, std::memory_order_relaxed);
      t_off_ms_.store(agora_ms, std::memory_order_relaxed);
      uint32_t on = t_on_us_.load(std::memory_order_relaxed);
      uint32_t dur = (agora_us >= on) ? (agora_us - on) : 0;
      ult_dur_us_.store(dur, std::memory_order_relaxed);

      uint32_t n = agua_n_.load(std::memory_order_relaxed);
      if (n == 0) {
        min_dur_us_.store(dur, std::memory_order_relaxed);
        max_dur_us_.store(dur, std::memory_order_relaxed);
      } else {
        if (dur < min_dur_us_.load(std::memory_order_relaxed)) min_dur_us_.store(dur, std::memory_order_relaxed);
        if (dur > max_dur_us_.load(std::memory_order_relaxed)) max_dur_us_.store(dur, std::memory_order_relaxed);
      }
      agua_n_.store(n + 1, std::memory_order_relaxed);
    }
  }
  bool ler() override { return comandado_.load(std::memory_order_relaxed); }

  void zerar() {
    agua_n_.store(0, std::memory_order_relaxed);
    ult_dur_us_.store(0, std::memory_order_relaxed);
    min_dur_us_.store(0, std::memory_order_relaxed);
    max_dur_us_.store(0, std::memory_order_relaxed);
    t_on_ms_.store(0, std::memory_order_relaxed);
    t_off_ms_.store(0, std::memory_order_relaxed);
  }

  uint32_t agua_n() const { return agua_n_.load(std::memory_order_relaxed); }
  uint32_t ult_dur_us() const { return ult_dur_us_.load(std::memory_order_relaxed); }
  uint32_t min_dur_us() const { return min_dur_us_.load(std::memory_order_relaxed); }
  uint32_t max_dur_us() const { return max_dur_us_.load(std::memory_order_relaxed); }
  uint32_t t_on_ms() const { return t_on_ms_.load(std::memory_order_relaxed); }
  uint32_t t_off_ms() const { return t_off_ms_.load(std::memory_order_relaxed); }

 private:
  std::atomic<bool> comandado_{false};
  std::atomic<uint32_t> t_on_us_{0};
  std::atomic<uint32_t> t_off_us_{0};
  std::atomic<uint32_t> t_on_ms_{0};
  std::atomic<uint32_t> t_off_ms_{0};
  std::atomic<uint32_t> ult_dur_us_{0};
  std::atomic<uint32_t> min_dur_us_{0};
  std::atomic<uint32_t> max_dur_us_{0};
  std::atomic<uint32_t> agua_n_{0};
};

// ------------------------------------------------------------ servo/LED
class SaidasVigia : public vigia::SaidasAplicacao {
 public:
  void soltar_servo() override {
    // Igual ao original: solta ANTES de energizar para nao tremer.
    if (preso_) { servoPan.detach(); preso_ = false; }
  }
  void prender_servo(int graus) override {
    if (!preso_) {
      servoPan.setPeriodHertz(50);
      servoPan.attach(PINO_PAN, 500, 2400);
      preso_ = true;
    }
    servoPan.write(graus);
  }
  void escrever_servo(int graus) override {
    if (preso_) servoPan.write(graus);
  }
  void led(bool ligado) override {
    digitalWrite(PINO_LED, ligado ? HIGH : LOW);
    led_ = ligado;
  }
  void marcar_preso() { preso_ = true; }
  bool solto() const { return !preso_; }
  bool led_ligado() const { return led_; }

 private:
  bool preso_ = false;
  bool led_ = false;
};

ReleGPIO rele;
SaidasVigia saidas;
vigia::Protecao protecao;
vigia::Arbitro arbitro;
TaskHandle_t tarefaProtecaoHandle = nullptr;
bool protecaoOk = false;

std::atomic<uint32_t> tickMaxGapUs{0};
std::atomic<uint32_t> ticksTotal{0};
std::atomic<bool> zerarDiagSolicitado{false};
uint32_t tInicioMs = 0;

static char resposta[vigia::RESPOSTA_MAX];

// ------------------------------------------------------------ tarefa
// Unica dona do rele. Sem rede, Serial, I2C, servo, log, heap ou mutex.
void tarefaProtecao(void *) {
  TickType_t ultimo = xTaskGetTickCount();
  TickType_t periodo = pdMS_TO_TICKS(1);
  if (periodo == 0) periodo = 1;
  uint32_t ultimo_us = micros();
  for (;;) {
    if (zerarDiagSolicitado.exchange(false, std::memory_order_relaxed)) {
      rele.zerar();
      tickMaxGapUs.store(0, std::memory_order_relaxed);
    }
    uint32_t agora_ms = millis();
    uint32_t agora_us = micros();
    uint32_t gap = (agora_us >= ultimo_us) ? (agora_us - ultimo_us) : 0;
    if (gap > tickMaxGapUs.load(std::memory_order_relaxed)) {
      tickMaxGapUs.store(gap, std::memory_order_relaxed);
    }
    ultimo_us = agora_us;
    ticksTotal.fetch_add(1, std::memory_order_relaxed);

    protecao.tick(agora_ms);
    vTaskDelayUntil(&ultimo, periodo);
  }
}

// ------------------------------------------------------------ LCD
void escreveLinha(byte linha, const char *texto) {
  char buf[17];
  byte i = 0;
  while (i < 16 && texto[i] != '\0') { buf[i] = texto[i]; i++; }
  while (i < 16) { buf[i] = ' '; i++; }
  buf[16] = '\0';
  lcd.setCursor(0, linha);
  lcd.print(buf);
}

void atualizaLCD(uint32_t agora) {
  static uint32_t ultimo = 0;
  static char antes0[17] = "", antes1[17] = "";
  if (agora - ultimo < 250) return;
  ultimo = agora;
  char l0[20], l1[20];
  const char *perfil = arbitro.perfil() == vigia::PERFIL_PROTEGIDO ? "P" : "C";
  if (!protecaoOk) {
    snprintf(l0, sizeof l0, "SEM PROTECAO");
  } else if (arbitro.em_combate()) {
    snprintf(l0, sizeof l0, "AGUA %s", arbitro.fogo() ? "FOGO" : "");
  } else if (arbitro.modo() == vigia::M_MANUAL) {
    snprintf(l0, sizeof l0, "Manual       %s", perfil);
  } else if (arbitro.vigiando()) {
    snprintf(l0, sizeof l0, "Vigiando...  %s", perfil);
  } else {
    snprintf(l0, sizeof l0, "Parado       %s", perfil);
  }
  if (wifiOk && ipLocal.length() > 0) {
    snprintf(l1, sizeof l1, "%d%c %s", arbitro.pan_graus(), GRAU, ipLocal.c_str());
  } else {
    snprintf(l1, sizeof l1, "P:%d%c", arbitro.pan_graus(), GRAU);
  }
  if (strcmp(l0, antes0)) { escreveLinha(0, l0); strncpy(antes0, l0, 16); antes0[16] = '\0'; }
  if (strcmp(l1, antes1)) { escreveLinha(1, l1); strncpy(antes1, l1, 16); antes1[16] = '\0'; }
}

// ------------------------------------------------------------ HTTP
// Recusa Host diferente do IP do S3: uma pagina externa que reaponte seu nome
// para este IP (DNS rebinding) envia o proprio nome no Host.
bool hostValido() {
  String h = servidor.hostHeader();
  if (h == ipLocal || h == ipLocal + ":80") return true;
  servidor.send(421, "text/plain", "host invalido");
  return false;
}

// /api/v1/* exige JSON declarado: formularios/imagens de outro site nao conseguem
// enviar esse Content-Type sem preflight CORS, que este servidor nao responde.
bool jsonDeclarado() {
  if (servidor.header("Content-Type").startsWith("application/json")) return true;
  servidor.send(415, "text/plain", "content-type deve ser application/json");
  return false;
}

void rotaStatus() {
  if (!hostValido()) return;
  int cod = arbitro.status_json(millis(), resposta, sizeof resposta);
  servidor.send(cod, "application/json", resposta);
}

void rotaCmd() {
  if (!hostValido()) return;
  if (!servidor.hasArg("c")) { servidor.send(400, "text/plain", "falta c"); return; }
  int cod = arbitro.letra(millis(), servidor.arg("c").charAt(0), resposta, sizeof resposta);
  servidor.send(cod, "text/plain", resposta);
}

void rotaSessao() {
  if (!hostValido() || !jsonDeclarado()) return;
  const String &corpo = servidor.arg("plain");
  int cod = arbitro.http_sessao(millis(), corpo.c_str(), corpo.length(), resposta, sizeof resposta);
  servidor.send(cod, "application/json", resposta);
}

void rotaComando() {
  if (!hostValido() || !jsonDeclarado()) return;
  const String &corpo = servidor.arg("plain");
  int cod = arbitro.http_comando(millis(), corpo.c_str(), corpo.length(), resposta, sizeof resposta);
  servidor.send(cod, "application/json", resposta);
}

void rotaDiag() {
  if (!hostValido()) return;
  if (servidor.hasArg("zerar")) {
    zerarDiagSolicitado.store(true, std::memory_order_relaxed);
  }
  uint32_t n = rele.agua_n();
  uint32_t ult = rele.ult_dur_us();
  uint32_t min_us = rele.min_dur_us();
  uint32_t max_us = rele.max_dur_us();
  uint32_t t_on = rele.t_on_ms();
  uint32_t t_off = rele.t_off_ms();
  bool r_ligado = rele.ler();
  uint32_t gap = tickMaxGapUs.load(std::memory_order_relaxed);
  uint32_t tks = ticksTotal.load(std::memory_order_relaxed);
  bool led = saidas.led_ligado();
  bool s_solto = saidas.solto();
  int pan = arbitro.pan_graus();

  char buf[384];
  char s_ult[16], s_min[16], s_max[16], s_on[16], s_off[16];
  if (n > 0) {
    snprintf(s_ult, sizeof s_ult, "%lu", (unsigned long)ult);
    snprintf(s_min, sizeof s_min, "%lu", (unsigned long)min_us);
    snprintf(s_max, sizeof s_max, "%lu", (unsigned long)max_us);
    snprintf(s_on, sizeof s_on, "%lu", (unsigned long)t_on);
    snprintf(s_off, sizeof s_off, "%lu", (unsigned long)t_off);
  } else {
    strcpy(s_ult, "null");
    strcpy(s_min, "null");
    strcpy(s_max, "null");
    strcpy(s_on, "null");
    strcpy(s_off, "null");
  }

  snprintf(buf, sizeof buf,
           "{\"agua_n\":%lu,\"agua_ult_us\":%s,\"agua_min_us\":%s,\"agua_max_us\":%s,"
           "\"rele_ligado_em_ms\":%s,\"rele_desligado_em_ms\":%s,\"rele\":%s,"
           "\"tick_max_gap_us\":%lu,\"ticks\":%lu,\"t_inicio_ms\":%lu,"
           "\"led\":%s,\"servo_solto\":%s,\"pan\":%d}",
           (unsigned long)n, s_ult, s_min, s_max, s_on, s_off,
           r_ligado ? "true" : "false", (unsigned long)gap, (unsigned long)tks,
           (unsigned long)tInicioMs, led ? "true" : "false",
           s_solto ? "true" : "false", pan);

  servidor.send(200, "application/json", buf);
}

// ------------------------------------------------------------ setup
void setup() {
  tInicioMs = millis();
  // Rele PRIMEIRO, nivel antes do pinMode, como no original (sem esguicho).
  digitalWrite(PINO_RELE, RELE_DESLIGA);
  pinMode(PINO_RELE, OUTPUT);
  digitalWrite(PINO_RELE, RELE_DESLIGA);

  pinMode(PINO_LED, OUTPUT);
  digitalWrite(PINO_LED, LOW);

  // Protecao antes de qualquer atuacao. Falha -> rele desligado e toda agua recusada.
  protecao.iniciar(&rele, millis(), true);
  BaseType_t criada = xTaskCreatePinnedToCore(tarefaProtecao, "protecao", PILHA_PROTECAO, nullptr,
                                              PRIORIDADE_PROTECAO, &tarefaProtecaoHandle, 1);
  protecaoOk = (criada == pdPASS);
  if (!protecaoOk) protecao.iniciar(&rele, millis(), false);

  Serial.begin(115200);
  Serial.println();
  Serial.println(F("=== VIGIA DUALSENSE (variante) em ESP32-S3 ==="));
  Serial.println(protecaoOk ? F("Protecao da bomba: tarefa criada")
                            : F("FALHA ao criar a protecao: agua desabilitada"));

  Wire.begin(PINO_SDA, PINO_SCL);
  lcd.init();
  lcd.backlight();
  escreveLinha(0, "Vigia DualSense");
  escreveLinha(1, protecaoOk ? "Centralizando..." : "SEM PROTECAO");

  ESP32PWM::allocateTimer(0);
  ESP32PWM::allocateTimer(1);
  ESP32PWM::allocateTimer(2);
  ESP32PWM::allocateTimer(3);
  servoPan.setPeriodHertz(50);
  servoPan.attach(PINO_PAN, 500, 2400);
  servoPan.write(vigia::PAN_CENTRO);
  saidas.marcar_preso();

  arbitro.iniciar(&protecao, &saidas, millis(), esp_random(), esp_random());

  WiFi.mode(WIFI_STA);
  WiFi.begin(SSID, SENHA);
  unsigned long inicio = millis();
  // Espera curta e sem atuacao: o PAN so comeca a varrer no loop.
  while (WiFi.status() != WL_CONNECTED && millis() - inicio < 20000) delay(200);
  wifiOk = WiFi.status() == WL_CONNECTED;
  if (wifiOk) {
    ipLocal = WiFi.localIP().toString();
    Serial.print(F("WiFi OK: http://"));
    Serial.println(ipLocal);
    escreveLinha(0, "WiFi Conectado!");
    escreveLinha(1, ipLocal.c_str());
    delay(1500);
    static const char *cabecalhos[] = {"Content-Type"};
    servidor.collectHeaders(cabecalhos, 1);
    servidor.on("/status", HTTP_GET, rotaStatus);
    servidor.on("/diag", HTTP_GET, rotaDiag);
    servidor.on("/cmd", rotaCmd);
    servidor.on("/api/v1/session", HTTP_POST, rotaSessao);
    servidor.on("/api/v1/command", HTTP_POST, rotaComando);
    servidor.begin();
  } else {
    Serial.println(F("Sem WiFi. Somente serial (perfil COMPAT)."));
  }
  Serial.println(F("Perfil COMPAT ate a primeira sessao protegida. H = ajuda"));
}

// ------------------------------------------------------------ loop
void loop() {
  arbitro.passo(millis());

  if (wifiOk) servidor.handleClient();

  if (Serial.available()) {
    char c = Serial.read();
    if (c != '\n' && c != '\r' && c != ' ') {
      arbitro.letra(millis(), c, resposta, sizeof resposta);
      Serial.println(resposta);
    }
  }

  atualizaLCD(millis());
}
