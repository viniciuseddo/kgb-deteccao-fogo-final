#include <Servo.h>

Servo servoBaixo;
const int PINO_SERVO = 9;
const int PINO_LED   = 8;
int anguloAtual = 90;

void moverSuave(int alvo) {
  int passo = (alvo > anguloAtual) ? 1 : -1;
  while (anguloAtual != alvo) {
    anguloAtual += passo;
    servoBaixo.write(anguloAtual);
    delay(8);
  }
}

void setup() {
  Serial.begin(9600);
  pinMode(PINO_LED, OUTPUT);
  servoBaixo.attach(PINO_SERVO);
  servoBaixo.write(90);
  delay(500);
  Serial.println("Pronto. Comandos: L C R F X");
}

void loop() {
  if (!Serial.available()) return;
  char c = Serial.read();
  if (c == '\n' || c == '\r' || c == ' ') return;
  if (c >= 'a' && c <= 'z') c -= 32;

  switch (c) {
    case 'L': moverSuave(150); Serial.println("esquerda"); break;
    case 'C': moverSuave(90);  Serial.println("centro");   break;
    case 'R': moverSuave(30);  Serial.println("direita");  break;
    case 'F': digitalWrite(PINO_LED, HIGH); Serial.println("FOGO");     break;
    case 'X': digitalWrite(PINO_LED, LOW);  Serial.println("apagado");  break;
    default:  Serial.println("comando invalido");          break;
  }
}