/*
  Projeto Sompo - Deteccao de fogo
  Arduino Uno + LCD 16x2 I2C (0x27) + LED + Pan-Tilt 2x SG90 + BOMBA via rele

  NOVIDADE desta versao: o comando F, alem de acender o LED, LIGA A BOMBA
  d'agua por um tempo limitado. X cancela na hora. B testa a bomba sozinha.

  Ligacoes:
    LCD I2C  -> SDA = A4 | SCL = A5 | VCC = 5V | GND = GND
    LED      -> pino 8 (+ resistor 220R) -> GND
    Servo PAN  (o de baixo, esquerda/direita) -> sinal no pino 9
    Servo TILT (o de cima, sobe/desce)        -> sinal no pino 10
    RELE     -> IN1 no pino 7 | VCC = 5V | GND = GND

    Servos: vermelho no trilho 5V, marrom no trilho GND.
    Capacitor 1000uF entre os trilhos 5V e GND (faixa preta no GND).

    ATENCAO, a parte que mais da errado:
    A BOMBA NAO PASSA PELO ARDUINO. Ela tem a fonte propria dela (powerbank
    ou porta-pilhas). Voce corta o fio POSITIVO dessa fonte e as duas pontas
    vao nos bornes COM e NO do rele. O rele so fecha o contato, igual a um
    interruptor. Se voce alimentar a bomba pelo 5V do Arduino, o Uno reinicia
    no momento do disparo, que foi exatamente o que aconteceu na apresentacao.

  Comandos pela serial, 9600 baud (aceita maiuscula ou minuscula):
    L = pan esquerda (150)      U = tilt cima  (50)
    C = pan centro   (90)       M = tilt meio  (90)
    R = pan direita  (30)       D = tilt baixo (130)
    F = fogo detectado: acende o LED e DISPARA A BOMBA
    X = cancela tudo (apaga LED e desliga a bomba na hora)
    B = testa so a bomba, sem simular fogo
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
const byte PINO_RELE = 7;

// A maioria dos modulos com optoacoplador aciona em nivel BAIXO.
// Se a bomba ligar sozinha ao energizar e desligar quando voce manda F,
// e porque o seu modulo e o contrario: troca os dois valores abaixo.
const byte RELE_LIGA    = LOW;
const byte RELE_DESLIGA = HIGH;

// Quanto tempo a bomba fica ligada em cada disparo, em milissegundos.
// 5000 = 5 segundos. Ajusta aqui depois de ver quanto rende no video.
const unsigned long TEMPO_BOMBA_MS = 5000;

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

bool          bombaLigada = false;
unsigned long bombaInicio = 0;

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

// Chamada o tempo todo, inclusive no meio do movimento dos servos, pra
// garantir que a bomba nunca passe do tempo limite nem fique ligada
// esquecida se o Python travar.
void verificaBomba() {
  if (bombaLigada && (millis() - bombaInicio >= TEMPO_BOMBA_MS)) {
    desligaBomba();
    atualizaLCD();
  }
}

// Cancela o estado de fogo: apaga o LED e corta a agua.
void cancelaFogo() {
  fogo = false;
  digitalWrite(PINO_LED, LOW);
  desligaBomba();
}

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
  Serial.println(F("F = fogo (LED + bomba)   X = cancela tudo"));
  Serial.println(F("B = testa so a bomba"));
  Serial.println(F("4 6 8 2    = ajuste fino de 10 graus"));
}

void setup() {
  Serial.begin(9600);

  // O rele PRIMEIRO de tudo. Escreve o nivel de desligado antes de virar
  // saida, senao o pino fica flutuando por alguns microssegundos no boot
  // e a bomba da um esguicho sozinha toda vez que o Arduino liga.
  digitalWrite(PINO_RELE, RELE_DESLIGA);
  pinMode(PINO_RELE, OUTPUT);
  digitalWrite(PINO_RELE, RELE_DESLIGA);

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
  Serial.println(F("Pronto. Pan 9, Tilt 10, LED 8, Rele 7."));
  ajuda();
}

void loop() {
  verificaBomba();

  if (!Serial.available()) return;

  char c = Serial.read();
  if (c == '\n' || c == '\r' || c == ' ') return;
  c = toupper(c);

  switch (c) {
    case 'L': cancelaFogo(); movePan(PAN_ESQUERDA, "Esquerda"); break;
    case 'C': cancelaFogo(); movePan(PAN_CENTRO,   "Centro");   break;
    case 'R': cancelaFogo(); movePan(PAN_DIREITA,  "Direita");  break;

    case 'U': cancelaFogo(); moveTilt(TILT_CIMA,  "Cima");  break;
    case 'M': cancelaFogo(); moveTilt(TILT_MEIO,  "Meio");  break;
    case 'D': cancelaFogo(); moveTilt(TILT_BAIXO, "Baixo"); break;

    case '4': cancelaFogo(); movePan(angPan + PASSO,   "Esquerda"); break;
    case '6': cancelaFogo(); movePan(angPan - PASSO,   "Direita");  break;
    case '8': cancelaFogo(); moveTilt(angTilt - PASSO, "Cima");     break;
    case '2': cancelaFogo(); moveTilt(angTilt + PASSO, "Baixo");    break;

    case 'F':
      fogo = true;
      digitalWrite(PINO_LED, HIGH);
      if (!bombaLigada) ligaBomba();
      atualizaLCD();
      Serial.print(F("FOGO! LED + agua, mirando em P:"));
      Serial.print(angPan);
      Serial.print(F(" T:"));
      Serial.println(angTilt);
      break;

    case 'X':
      cancelaFogo();
      atualizaLCD();
      Serial.println(F("Cancelado, voltando a rastrear"));
      break;

    case 'B':
      Serial.println(F("Teste de bomba"));
      ligaBomba();
      atualizaLCD();
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
