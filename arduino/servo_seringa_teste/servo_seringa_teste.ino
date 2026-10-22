/*
  Projeto Sompo / grupo KGB - Deteccao de fogo
  Teste do servo da seringa, no Arduino Uno

  Serve pra ACHAR os dois angulos do gatilho antes de colar qualquer coisa:
  o angulo ARMADO (embolo todo pra fora, seringa cheia) e o angulo de
  DISPARO (embolo empurrado pra dentro).

  LIGACAO
    Servo da seringa -> sinal no pino 6
    Vermelho no 5V, marrom no GND, com o capacitor de 1000uF nos trilhos.
    Os pinos 8, 9 e 10 ficam livres de proposito, sao do LED, do pan e do
    tilt no sketch principal.

  COMO USAR, na ordem
    1. Abre o Serial Monitor em 9600, com final de linha "Nova linha"
    2. Digita numeros de 0 a 180 e ve pra onde a haste aponta
    3. Quando achar a posicao ARMADA, digita  A
    4. Quando achar a posicao de DISPARO, digita  D
    5. Digita  C  pra ver o ciclo completo
    6. Digita  S  e anota os dois numeros. Eles vao pro sketch definitivo

  IMPORTANTE
    Testa PRIMEIRO com a haste solta, sem encostar na seringa. So depois
    de saber os dois angulos voce encaixa. Servo empurrando o que nao
    devia e como se descasca dente de engrenagem.

  COMANDOS
    0 a 180 = vai pra esse angulo
    A = salva o angulo atual como ARMADO
    D = salva o angulo atual como DISPARO
    R = vai pro angulo armado (recua)
    F = dispara, rapido
    C = ciclo completo: arma, espera 2s, dispara
    S = mostra o estado
    H = ajuda
*/

#include <Servo.h>

const byte PINO_SERVO = 6;

// valores iniciais, so um chute pra comecar. Voce vai achar os seus.
int anguloArmado  = 20;
int anguloDisparo = 160;

Servo servo;
int anguloAtual = 90;

char buffer[8];
byte tamanho = 0;


void vaiPara(int destino, bool suave) {
  destino = constrain(destino, 0, 180);
  if (suave) {
    int passo = (destino > anguloAtual) ? 1 : -1;
    while (anguloAtual != destino) {
      anguloAtual += passo;
      servo.write(anguloAtual);
      delay(15);
    }
  } else {
    anguloAtual = destino;
    servo.write(anguloAtual);
  }
  Serial.print(F("angulo = "));
  Serial.println(anguloAtual);
}


void estado() {
  Serial.println(F("--- estado ---"));
  Serial.print(F("atual   : ")); Serial.println(anguloAtual);
  Serial.print(F("ARMADO  : ")); Serial.println(anguloArmado);
  Serial.print(F("DISPARO : ")); Serial.println(anguloDisparo);
  Serial.print(F("curso   : "));
  Serial.print(abs(anguloDisparo - anguloArmado));
  Serial.println(F(" graus"));
}


void ajuda() {
  Serial.println(F("--- comandos ---"));
  Serial.println(F("0 a 180 = vai pra esse angulo (movimento suave)"));
  Serial.println(F("A = salva o angulo atual como ARMADO"));
  Serial.println(F("D = salva o angulo atual como DISPARO"));
  Serial.println(F("R = recua pro armado     F = dispara rapido"));
  Serial.println(F("C = ciclo completo       S = estado"));
}


void setup() {
  Serial.begin(9600);
  servo.attach(PINO_SERVO, 500, 2400);
  vaiPara(anguloArmado, true);

  Serial.println();
  Serial.println(F("=== Teste do servo da seringa ==="));
  Serial.println(F("Servo no pino 6. Testa com a haste SOLTA primeiro."));
  ajuda();
  estado();
}


void loop() {
  if (!Serial.available()) return;

  char c = Serial.read();

  // junta digitos ate vir algo que nao e digito
  if (c >= '0' && c <= '9') {
    if (tamanho < sizeof(buffer) - 1) buffer[tamanho++] = c;
    return;
  }

  if (tamanho > 0) {
    buffer[tamanho] = '\0';
    vaiPara(atoi(buffer), true);
    tamanho = 0;
    return;
  }

  switch (toupper(c)) {
    case 'A':
      anguloArmado = anguloAtual;
      Serial.print(F("ARMADO salvo em ")); Serial.println(anguloArmado);
      break;

    case 'D':
      anguloDisparo = anguloAtual;
      Serial.print(F("DISPARO salvo em ")); Serial.println(anguloDisparo);
      break;

    case 'R':
      Serial.println(F("recuando..."));
      vaiPara(anguloArmado, true);
      break;

    case 'F':
      // disparo e DIRETO, sem rampa. E o empurrao que gera a pressao.
      Serial.println(F("DISPARO"));
      vaiPara(anguloDisparo, false);
      break;

    case 'C':
      Serial.println(F("ciclo: armando..."));
      vaiPara(anguloArmado, true);
      delay(2000);
      Serial.println(F("DISPARO"));
      vaiPara(anguloDisparo, false);
      break;

    case 'S': estado(); break;
    case 'H': ajuda();  break;
  }
}
