// ============================================================
// captura_quadros.ino
//
// Captura QUADROS CRUS 160x120 em tons de cinza, exatamente como o firmware de B
// (test_images/debug_ocr_esp32cam) os entrega ao modelo, e os manda pela Serial sem JPEG e
// sem nenhuma anotação desenhada. Serve para montar o conjunto de teste do experimento
// hibrido_a_b: quadros no modo de operação de B (câmera colada na janela de dígitos), com a leitura
// anotada pelo script capturar_quadros.py.
//
// Por que um sketch novo: o debug_ocr_esp32cam manda o quadro DEPOIS de desenhar o retângulo e as
// linhas-guia e o comprime em JPEG (qualidade 80), então as imagens dele não servem como dado de teste.
//
// Protocolo (115200 baud):
//   PC -> placa:  'C'   captura e envia um quadro
//                 'P'   responde "[pong]" (teste de conexão)
//   placa -> PC:  "[pronto]\n" ao iniciar
//                 "<FRAME_START>" + 19200 bytes crus (linha a linha, 1 byte por pixel) + "<FRAME_END>\n"
//
// Configuração da câmera: a mesma do debug_ocr_esp32cam (QQVGA, cinza, 1 buffer na PSRAM, XCLK 20 MHz).
// Board: "AI Thinker ESP32-CAM" com PSRAM: Enabled. Não precisa de TensorFlow nem da partição Huge APP.
// ============================================================

#include "esp_camera.h"
#include <Preferences.h>

#define PWDN_GPIO_NUM     32
#define RESET_GPIO_NUM    -1
#define XCLK_GPIO_NUM      0
#define SIOD_GPIO_NUM     26
#define SIOC_GPIO_NUM     27
#define Y9_GPIO_NUM       35
#define Y8_GPIO_NUM       34
#define Y7_GPIO_NUM       39
#define Y6_GPIO_NUM       36
#define Y5_GPIO_NUM       21
#define Y4_GPIO_NUM       19
#define Y3_GPIO_NUM       18
#define Y2_GPIO_NUM        5
#define VSYNC_GPIO_NUM    25
#define HREF_GPIO_NUM     23
#define PCLK_GPIO_NUM     22

static const int CAM_W = 160;
static const int CAM_H = 120;
// Quadros descartados antes do que será enviado: o primeiro quadro após um tempo parado pode ser
// antigo ou mal exposto (a exposição automática se ajusta ao longo dos primeiros quadros).
static const int QUADROS_DESCARTADOS = 3;

// Orientacao do quadro gravada pelo calibrar_roi_esp32cam (NVS "roi", chaves "vflip" e "hmirror"),
// para camera montada de cabeca para baixo ou espelhada. Vai no sensor, entao o quadro ja sai de pe
// e a ROI (em pixels) vale igual em todos os firmwares. Sem nada salvo, nao mexe.
void aplicarGiroSalvo() {
  Preferences p;
  bool v = false, h = false;
  if (p.begin("roi", true)) {
    v = p.getBool("vflip", false);
    h = p.getBool("hmirror", false);
    p.end();
  }
  sensor_t* s = esp_camera_sensor_get();
  if (s) {
    s->set_vflip(s, v ? 1 : 0);
    s->set_hmirror(s, h ? 1 : 0);
  }
  Serial.printf("[camera] orientacao: vflip=%d hmirror=%d\n", v ? 1 : 0, h ? 1 : 0);
}

bool iniciarCamera() {
  camera_config_t config = {};
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer   = LEDC_TIMER_0;
  config.pin_d0 = Y2_GPIO_NUM; config.pin_d1 = Y3_GPIO_NUM;
  config.pin_d2 = Y4_GPIO_NUM; config.pin_d3 = Y5_GPIO_NUM;
  config.pin_d4 = Y6_GPIO_NUM; config.pin_d5 = Y7_GPIO_NUM;
  config.pin_d6 = Y8_GPIO_NUM; config.pin_d7 = Y9_GPIO_NUM;
  config.pin_xclk  = XCLK_GPIO_NUM;  config.pin_pclk  = PCLK_GPIO_NUM;
  config.pin_vsync = VSYNC_GPIO_NUM; config.pin_href  = HREF_GPIO_NUM;
  config.pin_sscb_sda = SIOD_GPIO_NUM; config.pin_sscb_scl = SIOC_GPIO_NUM;
  config.pin_pwdn  = PWDN_GPIO_NUM;  config.pin_reset = RESET_GPIO_NUM;
  config.xclk_freq_hz = 20000000;
  config.pixel_format = PIXFORMAT_GRAYSCALE;
  config.frame_size   = FRAMESIZE_QQVGA;  // 160x120
  config.fb_count     = 1;
  config.fb_location  = CAMERA_FB_IN_PSRAM;
  config.grab_mode    = CAMERA_GRAB_WHEN_EMPTY;

  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
    Serial.printf("[camera] erro: 0x%x\n", err);
    return false;
  }
  aplicarGiroSalvo();
  delay(300);
  return true;
}

void enviarQuadro() {
  for (int i = 0; i < QUADROS_DESCARTADOS; i++) {
    camera_fb_t *d = esp_camera_fb_get();
    if (d) esp_camera_fb_return(d);
  }
  camera_fb_t *fb = esp_camera_fb_get();
  if (!fb || fb->len != (size_t)(CAM_W * CAM_H)) {
    Serial.println("[erro] falha ao capturar o quadro");
    if (fb) esp_camera_fb_return(fb);
    return;
  }
  Serial.print("<FRAME_START>");
  Serial.write(fb->buf, fb->len);
  Serial.print("<FRAME_END>");
  Serial.println();
  esp_camera_fb_return(fb);
}

void setup() {
  Serial.begin(115200);
  delay(1000);
  if (!iniciarCamera()) {
    Serial.println("Falha na camera. Parando.");
    while (true) delay(1000);
  }
  Serial.println("[pronto]");
}

void loop() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == 'C') enviarQuadro();
    else if (c == 'P') Serial.println("[pong]");
  }
  delay(5);
}
