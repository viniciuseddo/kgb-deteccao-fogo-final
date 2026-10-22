/**
 * ESP32-CAM - Firmware Universal de Coleta de Imagens/Vídeo
 * 
 * Modos Suportados:
 * 1. WiFi Ponto de Acesso (AP): Cria a rede 'ESP32CAM-FOGO' (senha: 12345678).
 *    Acesse http://192.168.4.1 de qualquer celular ou notebook!
 * 2. WiFi Estação (Opcional): Conecta ao roteador local se preenchido abaixo.
 * 3. Serial USB: Envia frames via UART a 460800 baud caso conectado via cabo.
 */

#include "esp_camera.h"
#include "soc/rtc_cntl_reg.h"
#include <WebServer.h>
#include <WiFi.h>
#include "config.h"

// =======================================================
// CONFIGURAÇÃO DE REDE (OPCIONAL)
// Se deixar vazio (""), ele cria automaticamente a rede própria 'ESP32CAM-FOGO'
// =======================================================
const char* WIFI_SSID = "";         // Ex: "MinhaRedeWiFi" (ou deixe vazio)
const char* WIFI_PASS = "";         // Ex: "MinhaSenha123" (ou deixe vazio)

// Configurações do Ponto de Acesso (AP) quando não conectado ao roteador
const char* AP_SSID = "ESP32CAM-FOGO";
const char* AP_PASS = "12345678";

#define FLASH_LED_PIN 4
int led_val = 0;

WebServer server(80);

void setFlash(int val) {
  led_val = constrain(val, 0, 40); // Limite seguro para não queimar
  analogWrite(FLASH_LED_PIN, led_val);
}

void sendFrameSerial(camera_fb_t *fb) {
  uint8_t hdr[8];
  hdr[0] = 0xAA;
  hdr[1] = 0x55;
  hdr[2] = 0xAA;
  hdr[3] = 0x55;
  uint32_t len = fb->len;
  hdr[4] = (uint8_t)(len & 0xFF);
  hdr[5] = (uint8_t)((len >> 8) & 0xFF);
  hdr[6] = (uint8_t)((len >> 16) & 0xFF);
  hdr[7] = (uint8_t)((len >> 24) & 0xFF);

  Serial.write(hdr, 8);
  Serial.write(fb->buf, fb->len);
  Serial.flush();
}

void handleStream() {
  WiFiClient client = server.client();
  client.println("HTTP/1.1 200 OK");
  client.println("Content-Type: multipart/x-mixed-replace; boundary=frame");
  client.println("Access-Control-Allow-Origin: *");
  client.println("Cache-Control: no-cache");
  client.println("Connection: close");
  client.println();

  while (client.connected()) {
    camera_fb_t *fb = esp_camera_fb_get();
    if (!fb) {
      delay(10);
      continue;
    }

    client.println("--frame");
    client.println("Content-Type: image/jpeg");
    client.printf("Content-Length: %u\r\n\r\n", fb->len);
    client.write(fb->buf, fb->len);
    client.println();

    esp_camera_fb_return(fb);
    delay(40);
  }
}

void handleCapture() {
  camera_fb_t *fb = esp_camera_fb_get();
  if (!fb) {
    server.send(500, "text/plain", "Falha na captura");
    return;
  }
  server.sendHeader("Access-Control-Allow-Origin", "*");
  server.send_P(200, "image/jpeg", (const char *)fb->buf, fb->len);
  esp_camera_fb_return(fb);
}

void handleFlash() {
  if (server.hasArg("val")) {
    int v = server.arg("val").toInt();
    setFlash(v);
  }
  server.sendHeader("Access-Control-Allow-Origin", "*");
  server.send(200, "text/plain", String(led_val));
}

void handleIndex() {
  String html = "<!doctype html><html><head><meta charset='utf-8'><title>ESP32-CAM</title>"
                "<meta name='viewport' content='width=device-width, initial-scale=1'>"
                "<style>body{background:#111;color:#fff;font-family:sans-serif;text-align:center;padding:15px;margin:0;}"
                "img{max-width:100%;border-radius:10px;box-shadow:0 10px 30px rgba(0,0,0,0.8);border:2px solid #333;}"
                ".card{background:#222;max-width:640px;margin:auto;padding:15px;border-radius:12px;}"
                "button{background:#ff5722;color:#fff;border:none;padding:10px 18px;border-radius:6px;font-size:16px;cursor:pointer;margin:5px;}"
                "</style></head><body><div class='card'>"
                "<h2>🔥 ESP32-CAM Câmera Ativa</h2>"
                "<img src='/stream' /><br><br>"
                "<button onclick=\"fetch('/flash?val=' + (prompt('Brilho LED (0 a 40):', '20')||0))\">💡 Controlar LED</button>"
                "<p style='color:#888;font-size:13px;'>Para gravar vídeos e datasets, use o aplicativo no seu computador.</p>"
                "</div></body></html>";
  server.send(200, "text/html", html);
}

void setup() {
  WRITE_PERI_REG(RTC_CNTL_BROWN_OUT_REG, 0); // Evita reset por oscilacao de alimentacao
  Serial.begin(460800);
  pinMode(FLASH_LED_PIN, OUTPUT);
  setFlash(0);

  delay(500);
  Serial.println("\n[ESP32-CAM] Inicializando...");

  if (!iniciarCamera(FRAMESIZE_VGA, 12)) {
    Serial.println("[ESP32-CAM] ERRO: Falha ao iniciar sensor da câmera!");
    return;
  }
  Serial.println("[ESP32-CAM] Câmera OV2640 iniciada com sucesso!");

  // Conexão WiFi
  bool wifiConectado = false;
  if (strlen(WIFI_SSID) > 0) {
    Serial.printf("[WiFi] Conectando a %s...", WIFI_SSID);
    WiFi.mode(WIFI_STA);
    WiFi.begin(WIFI_SSID, WIFI_PASS);
    int tentativas = 0;
    while (WiFi.status() != WL_CONNECTED && tentativas < 15) {
      delay(500);
      Serial.print(".");
      tentativas++;
    }
    if (WiFi.status() == WL_CONNECTED) {
      wifiConectado = true;
      Serial.println("\n[WiFi] Conectado com sucesso!");
      Serial.printf("[WiFi] Acesse o IP: http://%s\n", WiFi.localIP().toString().c_str());
    } else {
      Serial.println("\n[WiFi] Nao conectou ao roteador. Iniciando Ponto de Acesso (AP)...");
    }
  }

  // Se não foi configurado ou não conectou, cria o Ponto de Acesso próprio (AP Mode)
  if (!wifiConectado) {
    WiFi.mode(WIFI_AP);
    WiFi.softAP(AP_SSID, AP_PASS);
    IPAddress IP = WiFi.softAPIP();
    Serial.printf("\n===========================================\n");
    Serial.printf(" REDE WIFI CRIADA: %s\n", AP_SSID);
    Serial.printf(" SENHA: %s\n", AP_PASS);
    Serial.printf(" ACESSE NO NAVEGADOR: http://%s\n", IP.toString().c_str());
    Serial.printf("===========================================\n");
  }

  // Rotas HTTP
  server.on("/", HTTP_GET, handleIndex);
  server.on("/stream", HTTP_GET, handleStream);
  server.on("/capture", HTTP_GET, handleCapture);
  server.on("/flash", HTTP_GET, handleFlash);
  server.begin();
  Serial.println("[Servidor Web] Pronto na porta 80!");
}

void loop() {
  server.handleClient();

  // Controle Serial para flash LED: L0 até L40
  if (Serial.available() > 0) {
    char c = Serial.peek();
    if (c == 'L') {
      Serial.read();
      int val = Serial.parseInt();
      setFlash(val);
    }
  }

  // Se estiver enviando via Serial contínuo
  // (Caso alguém esteja usando diretamente o cabo USB)
  static unsigned long lastSerialFrame = 0;
  if (millis() - lastSerialFrame > 65) { // ~15 FPS serial
    camera_fb_t *fb = esp_camera_fb_get();
    if (fb) {
      sendFrameSerial(fb);
      esp_camera_fb_return(fb);
      lastSerialFrame = millis();
    }
  }
}
