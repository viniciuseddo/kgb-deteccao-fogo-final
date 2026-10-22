/*
  Projeto Sompo / grupo KGB - Deteccao de fogo
  Controlador Pan-Tilt + BOMBA D'AGUA em ESP32-S3, substituindo o Arduino Uno

  Aceita comando por DOIS caminhos, e os dois funcionam ao mesmo tempo:

    1) SERIAL, as mesmas letras de sempre.
       O sistema_completo.py funciona sem mudar nada, so apontando
       para a porta COM do S3.

    2) WI-FI, por rotas HTTP:
         http://<ip>/cmd?c=F                uma letra, igual a serial
         http://<ip>/angulo?pan=90&tilt=75  angulo absoluto, sem cortar a agua
         http://<ip>/status                 devolve o estado em JSON

  LIGACOES (placa ESP32-S3-N16R8 na base de bornes)
    Servo PAN  (o de baixo, gira esquerda/direita) -> sinal no GPIO 4
    Servo TILT (o de cima, sobe/desce)             -> sinal no GPIO 5
    LED vermelho -> GPIO 6, com resistor de 220R para o GND (opcional)
    LCD 16x2 I2C -> SDA no GPIO 8, SCL no GPIO 9   (opcional)
    RELE IN1     -> GPIO 7

    CUIDADO COM A PSRAM: essa placa e N16R8, ou seja, tem PSRAM OPI, que
    consome os GPIO 33 a 37 por dentro. A base expoe 35, 36 e 37 nos
    bornes, mas eles NAO podem ser usados. Se encostar neles a placa
    nao sobe.

  ALIMENTACAO, a parte que derrubou a apresentacao
    Os servos NAO saem da placa. Vermelho no trilho de 5V da fonte
    externa, marrom no GND dela, e esse GND ligado a um GND do S3.
    Sem esse GND comum o servo ignora o sinal.

    A BOMBA NAO PASSA PELA PLACA NEM PELA MESMA FONTE DOS SERVOS.
    Ela tem fonte propria (powerbank). Corta o fio POSITIVO dessa fonte
    e as duas pontas vao nos bornes COM e NO do rele. O rele so fecha
    o contato, igual a um interruptor.

  RELE COM LOGICA DE 3,3V
    O S3 e 3,3V e as bobinas dos reles sao de 5V. Por isso:
    TIRA O JUMPER J1 do modulo e liga VCC no 3V3 da placa e RY-VCC no
    5V da fonte, com o GND comum. Assim o optoacoplador chaveia limpo.

  CONFIGURACAO NA ARDUINO IDE
    Placa: ESP32S3 Dev Module
    USB CDC On Boot: Enabled      <- sem isso o Serial.print nao sai
    PSRAM: OPI PSRAM              <- porque a sua e N16R8
    Flash Size: 16MB

  COMANDOS
    L = pan esquerda (150)      U = tilt cima  (50)
    C = pan centro   (90)       M = tilt meio  (90)
    R = pan direita  (30)       D = tilt baixo (130)
    F = fogo detectado: acende o LED e DISPARA A BOMBA
    X = para tudo na hora (LED apaga e a agua corta)
    B = testa so a bomba, sem simular fogo
    H = imprime a lista de comandos
    4 6 8 2 = ajuste fino de 10 graus

  COMPORTAMENTO DA AGUA, pensado pro video
    Uma vez disparada, a bomba roda TEMPO_BOMBA_MS e nada interrompe,
    a nao ser o X. Comandos de movimento durante o disparo so corrigem
    a mira, a agua continua saindo. E o que faz a cena do jato seguindo
    o alvo funcionar.
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
const byte PINO_RELE    = 7;
const byte PINO_SDA     = 8;
const byte PINO_SCL     = 9;

// A maioria dos modulos com optoacoplador aciona em nivel BAIXO.
// Se a bomba ligar sozinha ao energizar e desligar quando voce manda F,
// e porque o seu modulo e o contrario: troca os dois valores abaixo.
const byte RELE_LIGA    = LOW;
const byte RELE_DESLIGA = HIGH;

// Quanto tempo a bomba fica ligada em cada disparo, em milissegundos.
// 5000 = 5 segundos. Ajusta depois de ver quanto rende de agua no video.
const unsigned long TEMPO_BOMBA_MS = 5000;

// posicoes fixas
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

bool          bombaLigada = false;
unsigned long bombaInicio = 0;


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

  if (fogo || bombaLigada) {
    snprintf(l0, sizeof(l0), "FOGO DETECTADO");
    if (bombaLigada) {
      snprintf(l1, sizeof(l1), "AGUA P%d%c T%d%c", angPan, GRAU, angTilt, GRAU);
    } else {
      snprintf(l1, sizeof(l1), "Mira P%d%c T%d%c", angPan, GRAU, angTilt, GRAU);
    }
  } else {
    snprintf(l0, sizeof(l0), "Rast: %s", rotulo);
    snprintf(l1, sizeof(l1), "P:%d%c T:%d%c", angPan, GRAU, angTilt, GRAU);
  }

  escreveLinha(0, l0);
  escreveLinha(1, l1);
}


// ----------------------------------------------------------- bomba
void ligaBomba() {
  digitalWrite(PINO_RELE, RELE_LIGA);
  bombaLigada = true;
  bombaInicio = millis();
  Serial.println(F("BOMBA LIGADA"));
}

void desligaBomba() {
  digitalWrite(PINO_RELE, RELE_DESLIGA);
  if (bombaLigada) Serial.println(F("BOMBA DESLIGADA"));
  bombaLigada = false;
}

// Chamada o tempo todo, inclusive no meio do movimento dos servos e
// entre requisicoes HTTP. Garante que a bomba nunca passe do tempo
// limite nem fique ligada esquecida se o Python travar ou cair a rede.
void verificaBomba() {
  if (bombaLigada && (millis() - bombaInicio >= TEMPO_BOMBA_MS)) {
    desligaBomba();
    atualizaLCD();
  }
}

// So apaga o LED e sai do estado de fogo. NAO corta a agua de proposito:
// corrigir a mira durante o disparo e o comportamento desejado.
void cancelaFogo() {
  fogo = false;
  digitalWrite(PINO_LED, LOW);
}

// Parada de emergencia de verdade, usada pelo X.
void paraTudo() {
  cancelaFogo();
  desligaBomba();
}


// --------------------------------------------------------- movimento
// Rampa suave, para os comandos de posicao fixa. Da o movimento
// bonito da demo e limita o pico de corrente dos servos.
void moveSuave(Servo &s, int &atual, int destino) {
  int passo = (destino > atual) ? 1 : -1;
  while (atual != destino) {
    atual += passo;
    s.write(atual);
    verificaBomba();
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
  if (!fogo && !bombaLigada) {
    strncpy(rotulo, "Rastreando", sizeof(rotulo) - 1);
    rotulo[sizeof(rotulo) - 1] = '\0';
  }
  atualizaLCD();
}


void ajuda() {
  Serial.println(F("--- comandos ---"));
  Serial.println(F("L / C / R  = pan esquerda / centro / direita"));
  Serial.println(F("U / M / D  = tilt cima / meio / baixo"));
  Serial.println(F("F = fogo (LED + bomba)   X = para tudo"));
  Serial.println(F("B = testa so a bomba"));
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
    case 'L': cancelaFogo(); movePan(PAN_ESQUERDA, "Esquerda"); return true;
    case 'C': cancelaFogo(); movePan(PAN_CENTRO,   "Centro");   return true;
    case 'R': cancelaFogo(); movePan(PAN_DIREITA,  "Direita");  return true;

    case 'U': cancelaFogo(); moveTilt(TILT_CIMA,  "Cima");  return true;
    case 'M': cancelaFogo(); moveTilt(TILT_MEIO,  "Meio");  return true;
    case 'D': cancelaFogo(); moveTilt(TILT_BAIXO, "Baixo"); return true;

    case '4': cancelaFogo(); movePan(angPan + PASSO,   "Esquerda"); return true;
    case '6': cancelaFogo(); movePan(angPan - PASSO,   "Direita");  return true;
    case '8': cancelaFogo(); moveTilt(angTilt - PASSO, "Cima");     return true;
    case '2': cancelaFogo(); moveTilt(angTilt + PASSO, "Baixo");    return true;

    case 'F':
      fogo = true;
      digitalWrite(PINO_LED, HIGH);
      if (!bombaLigada) ligaBomba();
      atualizaLCD();
      Serial.printf("FOGO! LED + agua, mirando em P:%d T:%d\n", angPan, angTilt);
      return true;

    case 'X':
      paraTudo();
      atualizaLCD();
      Serial.println(F("Parado, voltando a rastrear"));
      return true;

    case 'B':
      Serial.println(F("Teste de bomba"));
      ligaBomba();
      atualizaLCD();
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
  html += "<p>P: " + String(angPan) + "  T: " + String(angTilt);
  html += bombaLigada ? "  <b>AGUA</b>" : "";
  html += "</p>";
  html += "<div><a href='/cmd?c=U'>cima</a></div>";
  html += "<div><a href='/cmd?c=L'>esq</a>";
  html += "<a href='/cmd?c=C'>centro</a>";
  html += "<a href='/cmd?c=R'>dir</a></div>";
  html += "<div><a href='/cmd?c=D'>baixo</a></div>";
  html += "<div><a href='/cmd?c=F'>FOGO</a>";
  html += "<a href='/cmd?c=X'>parar</a></div>";
  html += "<div><a href='/cmd?c=B'>testar bomba</a></div>";
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

// Correcao de mira pura. NAO mexe no estado de fogo nem corta a agua,
// justamente pro rastreamento poder acompanhar o alvo enquanto molha.
void rotaAngulo() {
  if (!servidor.hasArg("pan") || !servidor.hasArg("tilt")) {
    servidor.send(400, "text/plain", "falta pan ou tilt");
    return;
  }
  moveDireto(servidor.arg("pan").toInt(), servidor.arg("tilt").toInt());
  servidor.send(200, "text/plain", "ok");
}

void rotaStatus() {
  char json[160];
  snprintf(json, sizeof(json),
           "{\"pan\":%d,\"tilt\":%d,\"fogo\":%s,\"bomba\":%s,\"rotulo\":\"%s\"}",
           angPan, angTilt,
           fogo ? "true" : "false",
           bombaLigada ? "true" : "false",
           rotulo);
  servidor.send(200, "application/json", json);
}


// ------------------------------------------------------------ setup
void setup() {
  Serial.begin(115200);
  delay(300);

  // O rele PRIMEIRO de tudo. Escreve o nivel de desligado antes de virar
  // saida, senao o pino fica flutuando por alguns microssegundos no boot
  // e a bomba da um esguicho sozinha toda vez que a placa liga.
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
  Serial.println(F("=== Pan-Tilt + Bomba KGB em ESP32-S3 ==="));
  Serial.printf("Pan GPIO %d, Tilt GPIO %d, LED GPIO %d, Rele GPIO %d\n",
                PINO_PAN, PINO_TILT, PINO_LED, PINO_RELE);

  // ------------------------------------------------------ Wi-Fi
  // O sistema funciona pela serial mesmo sem rede. O Wi-Fi e um extra,
  // entao se nao conectar em 3 segundos ele segue a vida.
  WiFi.mode(WIFI_STA);
  WiFi.begin(SSID, SENHA);
  Serial.printf("Conectando em %s", SSID);

  unsigned long inicio = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - inicio < 3000) {
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
  verificaBomba();

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
