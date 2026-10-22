/*
  Projeto Sompo / grupo KGB - Deteccao de fogo
  VIGIA: ESP32-S3 varrendo o ambiente + bomba d'agua

  COMPORTAMENTO
    Ao ligar, o servo de baixo (PAN) comeca a varrer o ambiente sozinho,
    indo da esquerda para a direita e voltando, sem parar. E o modo
    "vigiando".

    Quando a ESP32-CAM detecta fogo, o Python manda F pela serial. Ai o
    servo PARA onde esta, o LED acende e a bomba dispara.

    Depois de TEMPO_VOLTA_MS sem receber nenhum comando novo, ele volta
    a varrer sozinho. Isso fecha o ciclo sem ninguem encostar em nada,
    que e o que precisa aparecer no video.

  SO UM SERVO. O de tilt saiu desta versao. Se um dia quiser de volta,
  troca USAR_TILT para true e liga o sinal dele no GPIO 5.

  LIGACOES (ESP32-S3-N16R8 na base de bornes)
    Servo PAN, o de baixo -> fio LARANJA (sinal) no borne GPIO 4
                             fio VERMELHO no trilho + da protoboard
                             fio MARROM   no trilho - da protoboard
    RELE IN1  -> GPIO 7
    LED       -> GPIO 6 com resistor 220R para o GND (opcional)
    LCD I2C   -> SDA GPIO 8, SCL GPIO 9 (opcional, nao trava se faltar)

    GND COMUM obrigatorio: um fio do trilho - da protoboard ate um
    borne GND do S3. Sem ele o servo ignora o sinal.

    NAO usar GPIO 33 a 37: a PSRAM OPI desta placa ocupa esses pinos.

  ALIMENTACAO
    S3 pelo USB do notebook. Servo pela fonte 5V 2A nos trilhos.
    A BOMBA NAO PASSA PELA PLACA: fonte propria dela cortada no fio
    positivo, passando pelos bornes COM e NO do rele.

  RELE COM LOGICA DE 3,3V
    Tira o jumper J1 do modulo. VCC no 3V3 da placa, RY-VCC no 5V da
    fonte, GND comum.

  COMANDOS PELA SERIAL, 115200
    V = volta a varrer (vigiando)
    L / C / R = para a varredura e aponta esquerda / centro / direita
    F = fogo: para tudo, acende o LED e dispara a bomba
    X = cancela: apaga o LED, corta a agua e volta a varrer
    B = testa so a bomba
    H = ajuda
    4 / 6 = ajuste fino de 10 graus para esquerda / direita
*/

#include <WiFi.h>
#include <WebServer.h>
#include <Wire.h>
#include <LiquidCrystal_I2C.h>
#include <ESP32Servo.h>

// ---------------------------------------------------------------
const char *SSID  = "COLOQUE_O_NOME_DA_REDE";
const char *SENHA = "COLOQUE_A_SENHA";
// ---------------------------------------------------------------

const bool USAR_TILT = false;   // troque para true se religar o 2o servo

const byte PINO_PAN  = 4;
const byte PINO_TILT = 5;
const byte PINO_LED  = 6;
const byte PINO_RELE = 7;
const byte PINO_SDA  = 8;
const byte PINO_SCL  = 9;

// A maioria dos modulos com optoacoplador aciona em nivel BAIXO.
// Se a bomba ligar sozinha ao energizar, troque estes dois valores.
const byte RELE_LIGA    = LOW;
const byte RELE_DESLIGA = HIGH;

const unsigned long TEMPO_BOMBA_MS = 5000;   // duracao de um disparo
const unsigned long TEMPO_VOLTA_MS = 8000;   // silencio ate voltar a varrer

// Varredura
const int PAN_ESQUERDA = 150;
const int PAN_CENTRO   = 90;
const int PAN_DIREITA  = 30;
const int PAN_MIN      = 10;
const int PAN_MAX      = 170;
const unsigned long PASSO_VARRE_MS = 18;  // menor = varre mais rapido
const int PASSO = 10;

const int TILT_MEIO = 90;

#define GRAU 223

LiquidCrystal_I2C lcd(0x27, 16, 2);
WebServer servidor(80);
Servo servoPan;
Servo servoTilt;

int  angPan   = PAN_CENTRO;
int  angTilt  = TILT_MEIO;
bool fogo     = false;
bool vigiando = true;          // comeca varrendo
int  direcao  = 1;             // 1 sobe o angulo, -1 desce
char rotulo[12] = "Vigiando";

bool          bombaLigada = false;
unsigned long bombaInicio = 0;

// Enquanto a bomba dispara, o servo e SOLTO (detach). Sem pulso chegando,
// ele para de corrigir posicao e nao treme quando a tensao do trilho cai.
// O atrito das engrenagens segura o angulo sozinho por alguns segundos.
bool servoSolto = false;
unsigned long ultimoPasso = 0;
unsigned long ultimoComando = 0;


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

void atualizaLCD() {
  char l0[20], l1[20];
  if (fogo || bombaLigada) {
    snprintf(l0, sizeof(l0), "FOGO DETECTADO");
    snprintf(l1, sizeof(l1), bombaLigada ? "AGUA  P%d%c" : "Mira  P%d%c",
             angPan, GRAU);
  } else if (vigiando) {
    snprintf(l0, sizeof(l0), "Vigiando...");
    snprintf(l1, sizeof(l1), "P:%d%c", angPan, GRAU);
  } else {
    snprintf(l0, sizeof(l0), "Parado: %s", rotulo);
    snprintf(l1, sizeof(l1), "P:%d%c", angPan, GRAU);
  }
  escreveLinha(0, l0);
  escreveLinha(1, l1);
}


// ----------------------------------------------------------- bomba
void ligaBomba() {
  // Solta o servo ANTES de energizar a bomba. Sem isso ele treme durante
  // todo o disparo, porque a bomba derruba a tensao do trilho e o servo
  // fica perdendo e recuperando torque. Tremer no disparo estraga a mira,
  // que e justamente o momento que precisa estar firme.
  if (!servoSolto) {
    servoPan.detach();
    servoSolto = true;
  }
  digitalWrite(PINO_RELE, RELE_LIGA);
  bombaLigada = true;
  bombaInicio = millis();
  Serial.println(F("BOMBA LIGADA (servo solto para nao tremer)"));
}

void desligaBomba() {
  digitalWrite(PINO_RELE, RELE_DESLIGA);
  if (bombaLigada) Serial.println(F("BOMBA DESLIGADA"));
  bombaLigada = false;

  // Devolve o controle ao servo e reafirma o angulo em que ele estava.
  if (servoSolto) {
    servoPan.setPeriodHertz(50);
    servoPan.attach(PINO_PAN, 500, 2400);
    servoPan.write(angPan);
    servoSolto = false;
  }
}

void verificaBomba() {
  if (bombaLigada && (millis() - bombaInicio >= TEMPO_BOMBA_MS)) {
    desligaBomba();
    atualizaLCD();
  }
}


// -------------------------------------------------------- varredura
void voltaAVigiar() {
  fogo = false;
  digitalWrite(PINO_LED, LOW);
  desligaBomba();
  vigiando = true;
  strncpy(rotulo, "Vigiando", sizeof(rotulo) - 1);
  rotulo[sizeof(rotulo) - 1] = '\0';
  Serial.println(F("VIGIANDO: varredura ligada"));
  atualizaLCD();
}

void paraVarredura(const char *motivo) {
  vigiando = false;
  strncpy(rotulo, motivo, sizeof(rotulo) - 1);
  rotulo[sizeof(rotulo) - 1] = '\0';
}

// Um passo da varredura, sem travar o loop. Chamada o tempo todo.
void atualizaVarredura() {
  if (!vigiando) return;
  if (servoSolto) return;   // durante o disparo o servo esta solto
  if (millis() - ultimoPasso < PASSO_VARRE_MS) return;
  ultimoPasso = millis();

  angPan += direcao;
  if (angPan >= PAN_ESQUERDA) { angPan = PAN_ESQUERDA; direcao = -1; }
  if (angPan <= PAN_DIREITA)  { angPan = PAN_DIREITA;  direcao =  1; }
  servoPan.write(angPan);

  // o LCD so a cada 10 graus, senao o I2C engasga a varredura
  if (angPan % 10 == 0) atualizaLCD();
}

// Depois de um tempo sem comando nenhum, volta a vigiar sozinho.
void verificaRetorno() {
  if (vigiando) return;
  if (bombaLigada) return;
  if (millis() - ultimoComando < TEMPO_VOLTA_MS) return;
  Serial.println(F("Silencio, voltando a vigiar"));
  voltaAVigiar();
}


// --------------------------------------------------------- movimento
void moveSuave(int destino) {
  destino = constrain(destino, PAN_MIN, PAN_MAX);
  // Nao tenta mover com o servo solto: espera a bomba terminar.
  if (servoSolto) { angPan = destino; return; }
  int passo = (destino > angPan) ? 1 : -1;
  while (angPan != destino) {
    angPan += passo;
    servoPan.write(angPan);
    verificaBomba();
    delay(8);
  }
}

void movePan(int destino, const char *nome) {
  paraVarredura(nome);
  moveSuave(destino);
  atualizaLCD();
  Serial.printf("PAN -> %s (%d graus)\n", nome, angPan);
}


void ajuda() {
  Serial.println(F("--- comandos ---"));
  Serial.println(F("V = volta a varrer o ambiente"));
  Serial.println(F("L / C / R = para e aponta esq / centro / dir"));
  Serial.println(F("F = fogo (LED + bomba)   X = cancela e volta a varrer"));
  Serial.println(F("B = testa so a bomba     4 / 6 = ajuste de 10 graus"));
}


// ------------------------------------------------------ interpretador
bool executaComando(char c) {
  c = toupper(c);
  ultimoComando = millis();

  switch (c) {
    case 'V': voltaAVigiar(); return true;

    case 'L': movePan(PAN_ESQUERDA, "Esquerda"); return true;
    case 'C': movePan(PAN_CENTRO,   "Centro");   return true;
    case 'R': movePan(PAN_DIREITA,  "Direita");  return true;

    case '4': movePan(angPan + PASSO, "Esquerda"); return true;
    case '6': movePan(angPan - PASSO, "Direita");  return true;

    case 'F':
      paraVarredura("Fogo");
      fogo = true;
      digitalWrite(PINO_LED, HIGH);
      if (!bombaLigada) ligaBomba();
      atualizaLCD();
      Serial.printf("FOGO! Parado em P:%d, LED e agua ligados\n", angPan);
      return true;

    case 'X':
      voltaAVigiar();
      Serial.println(F("Cancelado"));
      return true;

    case 'B':
      Serial.println(F("Teste de bomba"));
      ligaBomba();
      atualizaLCD();
      return true;

    case 'H': ajuda(); return true;
  }
  return false;
}


// ------------------------------------------------------------ HTTP
void rotaCmd() {
  if (!servidor.hasArg("c")) { servidor.send(400, "text/plain", "falta c"); return; }
  char c = servidor.arg("c").charAt(0);
  bool ok = executaComando(c);
  servidor.send(ok ? 200 : 400, "text/plain", ok ? "ok" : "comando invalido");
}

void rotaStatus() {
  char json[160];
  snprintf(json, sizeof(json),
           "{\"pan\":%d,\"vigiando\":%s,\"fogo\":%s,\"bomba\":%s}",
           angPan,
           vigiando    ? "true" : "false",
           fogo        ? "true" : "false",
           bombaLigada ? "true" : "false");
  servidor.send(200, "application/json", json);
}


// ------------------------------------------------------------ setup
void setup() {
  Serial.begin(115200);
  delay(300);

  // Rele PRIMEIRO, e o nivel antes do pinMode, senao a bomba da um
  // esguicho sozinha no instante em que a placa liga.
  digitalWrite(PINO_RELE, RELE_DESLIGA);
  pinMode(PINO_RELE, OUTPUT);
  digitalWrite(PINO_RELE, RELE_DESLIGA);

  pinMode(PINO_LED, OUTPUT);
  digitalWrite(PINO_LED, LOW);

  Wire.begin(PINO_SDA, PINO_SCL);
  lcd.init();
  lcd.backlight();
  escreveLinha(0, "Sistema pronto");
  escreveLinha(1, "Centralizando...");

  ESP32PWM::allocateTimer(0);
  ESP32PWM::allocateTimer(1);
  ESP32PWM::allocateTimer(2);
  ESP32PWM::allocateTimer(3);

  servoPan.setPeriodHertz(50);
  servoPan.attach(PINO_PAN, 500, 2400);
  servoPan.write(angPan);
  delay(600);

  if (USAR_TILT) {
    servoTilt.setPeriodHertz(50);
    servoTilt.attach(PINO_TILT, 500, 2400);
    servoTilt.write(angTilt);
    delay(600);
  }

  Serial.println();
  Serial.println(F("=== VIGIA KGB em ESP32-S3 ==="));
  Serial.printf("Pan GPIO %d, LED GPIO %d, Rele GPIO %d\n",
                PINO_PAN, PINO_LED, PINO_RELE);
  Serial.printf("Varrendo de %d a %d graus\n", PAN_DIREITA, PAN_ESQUERDA);

  WiFi.mode(WIFI_STA);
  WiFi.begin(SSID, SENHA);
  unsigned long inicio = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - inicio < 20000) delay(200);

  if (WiFi.status() == WL_CONNECTED) {
    Serial.print(F("WiFi OK: http://"));
    Serial.println(WiFi.localIP());
    servidor.on("/cmd", rotaCmd);
    servidor.on("/status", rotaStatus);
    servidor.begin();
  } else {
    Serial.println(F("Sem WiFi. Seguindo pela serial, que e o que importa."));
  }

  ajuda();
  ultimoComando = millis();
  voltaAVigiar();
}


// ------------------------------------------------------------ loop
void loop() {
  verificaBomba();
  atualizaVarredura();
  verificaRetorno();

  if (WiFi.status() == WL_CONNECTED) servidor.handleClient();

  if (Serial.available()) {
    char c = Serial.read();
    if (c == '\n' || c == '\r' || c == ' ') return;
    if (!executaComando(c)) {
      Serial.print(F("Comando invalido: "));
      Serial.println(c);
    }
  }
}
