/*
  Projeto Sompo / grupo KGB - Deteccao de fogo
  Controlador Pan-Tilt em ESP32-S3, substituindo o Arduino Uno

  Aceita comando por DOIS caminhos, e os dois funcionam ao mesmo tempo:

    1) SERIAL, as mesmas letras do sketch do Uno.
       O sistema_completo.py funciona sem mudar nada, so apontando
       para a porta COM do S3.

    2) WI-FI, por rotas HTTP. E o que permite tirar o cabo da mesa:
         http://<ip>/cmd?c=F              uma letra, igual a serial
         http://<ip>/angulo?pan=90&tilt=75  angulo absoluto
         http://<ip>/status               devolve o estado em JSON

  LIGACOES (ESP32-S3-DevKitC)
    Servo PAN  (o de baixo, gira esquerda/direita) -> sinal no GPIO 4
    Servo TILT (o de cima, sobe/desce)             -> sinal no GPIO 5
    LED vermelho -> GPIO 6, com resistor de 220R para o GND
    LCD 16x2 I2C -> SDA no GPIO 8, SCL no GPIO 9

    Os servos NAO podem ser alimentados pela placa. Vermelho em uma fonte
    externa de 5V, marrom no GND dessa fonte, e o GND dela ligado ao GND
    do S3. Sem esse GND comum o servo ignora o sinal.

  CONFIGURACAO NA ARDUINO IDE
    Placa: ESP32S3 Dev Module
    USB CDC On Boot: Enabled      <- sem isso o Serial.print nao sai
    PSRAM: OPI PSRAM              <- porque a sua e N16R8
    Flash Size: 16MB

  COMANDOS
    L = pan esquerda (150)      U = tilt cima  (50)
    C = pan centro   (90)       M = tilt meio  (90)
    R = pan direita  (30)       D = tilt baixo (130)
    F = fogo detectado, acende o LED e mantem a posicao
    X = apaga o LED e volta pra Rastreando
    H = imprime a lista de comandos
    4 6 8 2 = ajuste fino de 10 graus
*/

#include <WiFi.h>
#include <WebServer.h>
#include <Wire.h>
#include <LiquidCrystal_I2C.h>
#include <ESP32Servo.h>

// ---------------------------------------------------------------
// A rede precisa ser de 2.4GHz. No iPhone, "Maximizar Compatibilidade"
// tem que estar ligado, senao o roteamento sobe em 5GHz e o ESP32 nem
// enxerga a rede.
const char *SSID  = "IPHONE V";
const char *SENHA = "COLOQUE_A_SENHA_DO_ROTEAMENTO";
// ---------------------------------------------------------------

const byte PINO_PAN     = 4;
const byte PINO_TILT    = 5;
const byte PINO_LED     = 6;
const byte PINO_SDA     = 8;
const byte PINO_SCL     = 9;

// posicoes fixas, iguais as do sketch do Uno
const int PAN_ESQUERDA = 150;
const int PAN_CENTRO   = 90;
const int PAN_DIREITA  = 30;

// O servo de tilt fica montado espelhado no suporte, entao o angulo
// MENOR e que levanta. Por isso CIMA = 50 e BAIXO = 130.
const int TILT_CIMA  = 50;
const int TILT_MEIO  = 90;
const int TILT_BAIXO = 130;

// limites de seguranca do suporte Pan-Tilt
const int PAN_MIN  = 10;
const int PAN_MAX  = 170;
const int TILT_MIN = 40;
const int TILT_MAX = 140;

const int PASSO = 10;

// simbolo de grau no LCD. Se aparecer um caractere estranho no lugar
// da bolinha, troca o 223 por 176 (depende da ROM do modulo)
#define GRAU 223

LiquidCrystal_I2C lcd(0x27, 16, 2);
WebServer servidor(80);

Servo servoPan;
Servo servoTilt;

int  angPan  = PAN_CENTRO;
int  angTilt = TILT_MEIO;
bool fogo    = false;
char rotulo[12] = "Centro";


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
  char l0[20];
  char l1[20];

  if (fogo) {
    snprintf(l0, sizeof(l0), "FOGO DETECTADO");
    snprintf(l1, sizeof(l1), "CO2 P%d%c T%d%c", angPan, GRAU, angTilt, GRAU);
  } else {
    snprintf(l0, sizeof(l0), "Rast: %s", rotulo);
    snprintf(l1, sizeof(l1), "P:%d%c T:%d%c", angPan, GRAU, angTilt, GRAU);
  }

  escreveLinha(0, l0);
  escreveLinha(1, l1);
}


// --------------------------------------------------------- movimento
// Rampa suave, para os comandos de posicao fixa. Da o movimento
// bonito da demo e limita o pico de corrente dos servos.
void moveSuave(Servo &s, int &atual, int destino) {
  int passo = (destino > atual) ? 1 : -1;
  while (atual != destino) {
    atual += passo;
    s.write(atual);
    delay(8);
  }
}

void movePan(int destino, const char *nome) {
  destino = constrain(destino, PAN_MIN, PAN_MAX);
  moveSuave(servoPan, angPan, destino);
  strncpy(rotulo, nome, sizeof(rotulo) - 1);
  rotulo[sizeof(rotulo) - 1] = '\0';
  atualizaLCD();
  Serial.printf("PAN  -> %s (%d graus)\n", nome, angPan);
}

void moveTilt(int destino, const char *nome) {
  destino = constrain(destino, TILT_MIN, TILT_MAX);
  moveSuave(servoTilt, angTilt, destino);
  strncpy(rotulo, nome, sizeof(rotulo) - 1);
  rotulo[sizeof(rotulo) - 1] = '\0';
  atualizaLCD();
  Serial.printf("TILT -> %s (%d graus)\n", nome, angTilt);
}

// Movimento direto, sem rampa. E o que o rastreamento continuo usa:
// correcoes de poucos graus que precisam sair na hora.
void moveDireto(int destinoPan, int destinoTilt) {
  angPan  = constrain(destinoPan,  PAN_MIN,  PAN_MAX);
  angTilt = constrain(destinoTilt, TILT_MIN, TILT_MAX);
  servoPan.write(angPan);
  servoTilt.write(angTilt);
  strncpy(rotulo, "Rastreando", sizeof(rotulo) - 1);
  rotulo[sizeof(rotulo) - 1] = '\0';
  atualizaLCD();
}


void ajuda() {
  Serial.println(F("--- comandos ---"));
  Serial.println(F("L / C / R  = pan esquerda / centro / direita"));
  Serial.println(F("U / M / D  = tilt cima / meio / baixo"));
  Serial.println(F("F = fogo (acende LED)   X = apaga LED"));
  Serial.println(F("4 6 8 2    = ajuste fino de 10 graus"));
  Serial.println(F("--- rotas HTTP ---"));
  Serial.println(F("/cmd?c=F                uma letra"));
  Serial.println(F("/angulo?pan=90&tilt=75  angulo absoluto"));
  Serial.println(F("/status                 estado em JSON"));
}


// ------------------------------------------------------ interpretador
// Uma unica funcao trata o comando, venha ele da serial ou do Wi-Fi.
// Isso garante que os dois caminhos se comportem exatamente igual.
bool executaComando(char c) {
  c = toupper(c);

  switch (c) {
    case 'L': fogo = false; digitalWrite(PINO_LED, LOW); movePan(PAN_ESQUERDA, "Esquerda"); return true;
    case 'C': fogo = false; digitalWrite(PINO_LED, LOW); movePan(PAN_CENTRO,   "Centro");   return true;
    case 'R': fogo = false; digitalWrite(PINO_LED, LOW); movePan(PAN_DIREITA,  "Direita");  return true;

    case 'U': fogo = false; digitalWrite(PINO_LED, LOW); moveTilt(TILT_CIMA,  "Cima");  return true;
    case 'M': fogo = false; digitalWrite(PINO_LED, LOW); moveTilt(TILT_MEIO,  "Meio");  return true;
    case 'D': fogo = false; digitalWrite(PINO_LED, LOW); moveTilt(TILT_BAIXO, "Baixo"); return true;

    case '4': fogo = false; digitalWrite(PINO_LED, LOW); movePan(angPan + PASSO,   "Esquerda"); return true;
    case '6': fogo = false; digitalWrite(PINO_LED, LOW); movePan(angPan - PASSO,   "Direita");  return true;
    case '8': fogo = false; digitalWrite(PINO_LED, LOW); moveTilt(angTilt - PASSO, "Cima");     return true;
    case '2': fogo = false; digitalWrite(PINO_LED, LOW); moveTilt(angTilt + PASSO, "Baixo");    return true;

    case 'F':
      fogo = true;
      digitalWrite(PINO_LED, HIGH);
      atualizaLCD();
      Serial.printf("FOGO! LED aceso, mirando em P:%d T:%d\n", angPan, angTilt);
      return true;

    case 'X':
      fogo = false;
      digitalWrite(PINO_LED, LOW);
      atualizaLCD();
      Serial.println(F("LED apagado, voltando a rastrear"));
      return true;

    case 'H':
      ajuda();
      return true;
  }
  return false;
}


// ------------------------------------------------------------ HTTP
void rotaRaiz() {
  String html = "<html><head><meta charset='utf-8'>";
  html += "<meta name='viewport' content='width=device-width,initial-scale=1'>";
  html += "<style>body{font-family:sans-serif;text-align:center;padding:20px}";
  html += "a{display:inline-block;margin:6px;padding:14px 20px;background:#222;";
  html += "color:#fff;text-decoration:none;border-radius:8px;font-size:20px}</style>";
  html += "</head><body><h2>Pan-Tilt KGB</h2>";
  html += "<p>P: " + String(angPan) + "  T: " + String(angTilt) + "</p>";
  html += "<div><a href='/cmd?c=U'>cima</a></div>";
  html += "<div><a href='/cmd?c=L'>esq</a>";
  html += "<a href='/cmd?c=C'>centro</a>";
  html += "<a href='/cmd?c=R'>dir</a></div>";
  html += "<div><a href='/cmd?c=D'>baixo</a></div>";
  html += "<div><a href='/cmd?c=F'>FOGO</a>";
  html += "<a href='/cmd?c=X'>apagar</a></div>";
  html += "</body></html>";
  servidor.send(200, "text/html", html);
}

void rotaCmd() {
  if (!servidor.hasArg("c")) {
    servidor.send(400, "text/plain", "falta o parametro c");
    return;
  }
  char c = servidor.arg("c").charAt(0);
  if (executaComando(c)) {
    servidor.send(200, "text/plain", "ok");
  } else {
    servidor.send(400, "text/plain", "comando invalido");
  }
}

void rotaAngulo() {
  if (!servidor.hasArg("pan") || !servidor.hasArg("tilt")) {
    servidor.send(400, "text/plain", "falta pan ou tilt");
    return;
  }
  fogo = false;
  digitalWrite(PINO_LED, LOW);
  moveDireto(servidor.arg("pan").toInt(), servidor.arg("tilt").toInt());
  servidor.send(200, "text/plain", "ok");
}

void rotaStatus() {
  char json[120];
  snprintf(json, sizeof(json),
           "{\"pan\":%d,\"tilt\":%d,\"fogo\":%s,\"rotulo\":\"%s\"}",
           angPan, angTilt, fogo ? "true" : "false", rotulo);
  servidor.send(200, "application/json", json);
}


// ------------------------------------------------------------ setup
void setup() {
  Serial.begin(115200);
  delay(300);

  pinMode(PINO_LED, OUTPUT);
  digitalWrite(PINO_LED, LOW);

  Wire.begin(PINO_SDA, PINO_SCL);
  lcd.init();
  lcd.backlight();
  escreveLinha(0, "Sistema pronto");
  escreveLinha(1, "Centralizando...");

  // O ESP32Servo precisa reservar os timers ANTES de dar attach,
  // senao briga com outros perifericos que usam PWM.
  ESP32PWM::allocateTimer(0);
  ESP32PWM::allocateTimer(1);
  ESP32PWM::allocateTimer(2);
  ESP32PWM::allocateTimer(3);

  servoPan.setPeriodHertz(50);
  servoPan.attach(PINO_PAN, 500, 2400);
  servoPan.write(angPan);
  delay(600);

  servoTilt.setPeriodHertz(50);
  servoTilt.attach(PINO_TILT, 500, 2400);
  servoTilt.write(angTilt);
  delay(600);

  atualizaLCD();
  Serial.println();
  Serial.println(F("=== Pan-Tilt KGB em ESP32-S3 ==="));
  Serial.printf("Pan no GPIO %d, Tilt no GPIO %d, LED no GPIO %d\n",
                PINO_PAN, PINO_TILT, PINO_LED);

  // ------------------------------------------------------ Wi-Fi
  // O sistema funciona pela serial mesmo sem rede. O Wi-Fi e um extra,
  // entao se nao conectar em 15 segundos ele segue a vida.
  WiFi.mode(WIFI_STA);
  WiFi.begin(SSID, SENHA);
  Serial.printf("Conectando em %s", SSID);

  unsigned long inicio = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - inicio < 15000) {
    delay(400);
    Serial.print(".");
  }
  Serial.println();

  if (WiFi.status() == WL_CONNECTED) {
    Serial.println(F("=================================================="));
    Serial.print(F("PRONTO. Controle em: http://"));
    Serial.println(WiFi.localIP());
    Serial.println(F("=================================================="));

    escreveLinha(0, "WiFi OK");
    escreveLinha(1, WiFi.localIP().toString().c_str());
    delay(2500);
    atualizaLCD();

    servidor.on("/", rotaRaiz);
    servidor.on("/cmd", rotaCmd);
    servidor.on("/angulo", rotaAngulo);
    servidor.on("/status", rotaStatus);
    servidor.begin();
  } else {
    Serial.println(F("NAO CONECTOU no WiFi. Seguindo so pela serial."));
    Serial.println(F("Confira nome e senha, e se a rede e de 2.4GHz."));
  }

  ajuda();
}


// ------------------------------------------------------------ loop
void loop() {
  if (WiFi.status() == WL_CONNECTED) {
    servidor.handleClient();
  }

  if (Serial.available()) {
    char c = Serial.read();
    if (c == '\n' || c == '\r' || c == ' ') return;

    if (!executaComando(c)) {
      escreveLinha(0, "Comando invalido");
      Serial.print(F("Comando invalido: "));
      Serial.println(c);
      delay(800);
      atualizaLCD();
    }
  }
}
