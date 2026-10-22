#include "esp_camera.h"
#include <WiFi.h>
#include "esp_http_server.h"

const char* SSID  = "FIAP-IOT";   // o mesmo do sketch do grupo
const char* SENHA = "COLOQUE_A_SENHA";

static esp_err_t capture_handler(httpd_req_t *req) {
  camera_fb_t *fb = esp_camera_fb_get();
  if (fb) esp_camera_fb_return(fb);   // descarta o primeiro frame
  fb = esp_camera_fb_get();
  if (!fb) { httpd_resp_send_500(req); return ESP_FAIL; }
  httpd_resp_set_type(req, "image/jpeg");
  esp_err_t res = httpd_resp_send(req, (const char *)fb->buf, fb->len);
  esp_camera_fb_return(fb);
  return res;
}

void setup() {
  Serial.begin(115200);
  delay(1000);

  camera_config_t c;
  c.ledc_channel = LEDC_CHANNEL_0;
  c.ledc_timer   = LEDC_TIMER_0;
  c.pin_d0=5;  c.pin_d1=18; c.pin_d2=19; c.pin_d3=21;
  c.pin_d4=36; c.pin_d5=39; c.pin_d6=34; c.pin_d7=35;
  c.pin_xclk=0; c.pin_pclk=22; c.pin_vsync=25; c.pin_href=23;
  c.pin_sscb_sda=26; c.pin_sscb_scl=27;
  c.pin_pwdn=32; c.pin_reset=-1;
  c.xclk_freq_hz=20000000;
  c.pixel_format=PIXFORMAT_JPEG;
  c.frame_size=FRAMESIZE_VGA;
  c.jpeg_quality=10;
  c.fb_count=2;
  c.fb_location=CAMERA_FB_IN_PSRAM;
  c.grab_mode=CAMERA_GRAB_WHEN_EMPTY;

  if (esp_camera_init(&c) != ESP_OK) { Serial.println("camera falhou"); return; }

  sensor_t *s = esp_camera_sensor_get();
  Serial.printf("Sensor PID: 0x%04x\n", s->id.PID);

  s->set_whitebal(s, 1);
  s->set_awb_gain(s, 1);
  s->set_wb_mode(s, 0);
  s->set_exposure_ctrl(s, 1);
  s->set_aec2(s, 1);
  s->set_gain_ctrl(s, 1);

  // ajuste anti-estouro: a chama para de virar um borrao branco
  s->set_ae_level(s, -2);
  s->set_gainceiling(s, GAINCEILING_2X);
  s->set_brightness(s, 0);

  WiFi.mode(WIFI_STA);
  WiFi.begin(SSID, SENHA);
  while (WiFi.status() != WL_CONNECTED) { delay(500); Serial.print("."); }
  Serial.printf("\nPRONTO. IP da camera: http://%s\n", WiFi.localIP().toString().c_str());

  httpd_config_t hc = HTTPD_DEFAULT_CONFIG();
  httpd_uri_t uri = { "/capture", HTTP_GET, capture_handler, NULL };
  httpd_handle_t server = NULL;
  if (httpd_start(&server, &hc) == ESP_OK) httpd_register_uri_handler(server, &uri);
}

void loop() { delay(1000); }