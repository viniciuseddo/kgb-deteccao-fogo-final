/*
  Projeto Sompo - Deteccao de fogo
  Arduino Uno + LCD 16x2 I2C (0x27) + LED vermelho + Pan-Tilt com 2x SG90

  Ligacoes:
    LCD I2C  -> SDA = A4 | SCL = A5 | VCC = 5V | GND = GND
    LED      -> pino 8 (+ resistor 220R) -> GND
    Servo PAN  (o de baixo, gira esquerda/direita) -> sinal no pino 9
    Servo TILT (o de cima, sobe/desce)             -> sinal no pino 10
    Os dois servos: fio vermelho no trilho 5V, marrom no trilho GND
    Capacitor 1000uF entre os trilhos 5V e GND (perna da faixa preta no GND)

  Comandos pela serial, 9600 baud (aceita maiuscula ou minuscula):
    L = pan esquerda (150)      U = tilt cima  (50)
    C = pan centro   (90)       M = tilt meio  (90)
    R = pan direita  (30)       D = tilt baixo (130)
    F = fogo detectado, acende o LED e mantem a posicao
    X = apaga o LED e volta pra Rastreando
    H = imprime a lista de comandos na serial

  Ajuste fino, 10 graus por toque:
    4 = pan p/ esquerda   6 = pan p/ direita
    8 = tilt p/ cima      2 = tilt p/ baixo
*/

#include <Wire.h>
#include <LiquidCrystal_I2C.h>
#include <Servo.h>

LiquidCrystal_I2C lcd(0x27, 16, 2);

Servo servoPan;
Servo servoTilt;

const byte PINO_PAN  = 9;
const byte PINO_TILT = 10;
const byte PINO_LED  = 8;

// posicoes fixas
const int PAN_ESQUERDA = 150;
const int PAN_CENTRO   = 90;
const int PAN_DIREITA  = 30;

// O servo de tilt esta montado espelhado no suporte, entao o angulo
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

int  angPan  = PAN_CENTRO;
int  angTilt = TILT_MEIO;
bool fogo    = false;
char rotulo[12] = "Centro";

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
  Serial.print(F("PAN  -> "));
  Serial.print(nome);
  Serial.print(F(" ("));
  Serial.print(angPan);
  Serial.println(F(" graus)"));
}

void moveTilt(int destino, const char *nome) {
  destino = constrain(destino, TILT_MIN, TILT_MAX);
  moveSuave(servoTilt, angTilt, destino);
  strncpy(rotulo, nome, sizeof(rotulo) - 1);
  rotulo[sizeof(rotulo) - 1] = '\0';
  atualizaLCD();
  Serial.print(F("TILT -> "));
  Serial.print(nome);
  Serial.print(F(" ("));
  Serial.print(angTilt);
  Serial.println(F(" graus)"));
}

void ajuda() {
  Serial.println(F("--- comandos ---"));
  Serial.println(F("L / C / R  = pan esquerda / centro / direita"));
  Serial.println(F("U / M / D  = tilt cima / meio / baixo"));
  Serial.println(F("F = fogo (acende LED)   X = apaga LED"));
  Serial.println(F("4 6 8 2    = ajuste fino de 10 graus"));
}

void setup() {
  Serial.begin(9600);

  pinMode(PINO_LED, OUTPUT);
  digitalWrite(PINO_LED, LOW);

  lcd.init();
  lcd.backlight();
  escreveLinha(0, "Sistema pronto");
  escreveLinha(1, "Centralizando...");

  servoPan.attach(PINO_PAN);
  servoPan.write(angPan);
  delay(600);

  servoTilt.attach(PINO_TILT);
  servoTilt.write(angTilt);
  delay(600);

  atualizaLCD();
  Serial.println(F("Pronto. Pan no pino 9, Tilt no pino 10, LED no 8."));
  ajuda();
}

void loop() {
  if (!Serial.available()) return;

  char c = Serial.read();
  if (c == '\n' || c == '\r' || c == ' ') return;
  c = toupper(c);

  switch (c) {
    case 'L': fogo = false; digitalWrite(PINO_LED, LOW); movePan(PAN_ESQUERDA, "Esquerda"); break;
    case 'C': fogo = false; digitalWrite(PINO_LED, LOW); movePan(PAN_CENTRO,   "Centro");   break;
    case 'R': fogo = false; digitalWrite(PINO_LED, LOW); movePan(PAN_DIREITA,  "Direita");  break;

    case 'U': fogo = false; digitalWrite(PINO_LED, LOW); moveTilt(TILT_CIMA,  "Cima");  break;
    case 'M': fogo = false; digitalWrite(PINO_LED, LOW); moveTilt(TILT_MEIO,  "Meio");  break;
    case 'D': fogo = false; digitalWrite(PINO_LED, LOW); moveTilt(TILT_BAIXO, "Baixo"); break;

    case '4': fogo = false; digitalWrite(PINO_LED, LOW); movePan(angPan + PASSO,   "Esquerda"); break;
    case '6': fogo = false; digitalWrite(PINO_LED, LOW); movePan(angPan - PASSO,   "Direita");  break;
    case '8': fogo = false; digitalWrite(PINO_LED, LOW); moveTilt(angTilt - PASSO, "Cima");     break;
    case '2': fogo = false; digitalWrite(PINO_LED, LOW); moveTilt(angTilt + PASSO, "Baixo");    break;

    case 'F':
      fogo = true;
      digitalWrite(PINO_LED, HIGH);
      atualizaLCD();
      Serial.print(F("FOGO! LED aceso, mirando em P:"));
      Serial.print(angPan);
      Serial.print(F(" T:"));
      Serial.println(angTilt);
      break;

    case 'X':
      fogo = false;
      digitalWrite(PINO_LED, LOW);
      atualizaLCD();
      Serial.println(F("LED apagado, voltando a rastrear"));
      break;

    case 'H':
      ajuda();
      break;

    default:
      escreveLinha(0, "Comando invalido");
      Serial.print(F("Comando invalido: "));
      Serial.println(c);
      delay(800);
      atualizaLCD();
      break;
  }
}