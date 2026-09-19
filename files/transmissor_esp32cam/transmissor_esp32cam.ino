// ============================================================
// transmissor_esp32cam.ino
// Pipeline completo: captura imagem → divide em chunks → envia
// via Radioenge RD49C em canal 500 kHz (DR6, item 10.3 Ato 14448)
// ============================================================
#include "esp_camera.h"

// --- Pinos câmera (AI Thinker ESP32-CAM) ---
#define PWDN_GPIO_NUM   32
#define RESET_GPIO_NUM  -1
#define XCLK_GPIO_NUM    0
#define SIOD_GPIO_NUM   26
#define SIOC_GPIO_NUM   27
#define Y9_GPIO_NUM     35
#define Y8_GPIO_NUM     34
#define Y7_GPIO_NUM     39
#define Y6_GPIO_NUM     36
#define Y5_GPIO_NUM     21
#define Y4_GPIO_NUM     19
#define Y3_GPIO_NUM     18
#define Y2_GPIO_NUM      5
#define VSYNC_GPIO_NUM  25
#define HREF_GPIO_NUM   23
#define PCLK_GPIO_NUM   22

// --- Pinos UART para o Radioenge ---
#define LORA_RX_PIN 15   // Radioenge TX → ESP32-CAM RX
#define LORA_TX_PIN 14   // Radioenge RX ← ESP32-CAM TX

HardwareSerial LoRaSerial(1);

// --- Configuração de chunks ---
// Payload máximo DR6 (AU915, SF8/500kHz): 250 bytes
// Header binário: 4 bytes (uint16 index + uint16 total, big-endian)
// Dados por chunk: 100 bytes → payload total 104 bytes (margem confortável)
const int CHUNK_DATA_SIZE   = 100;
const unsigned long SEND_INTERVAL_MS = 7000;

// --- Buffer de imagem ---
static uint8_t* imgBuf  = nullptr;
static size_t   imgSize = 0;

// ----------------------------------------------------------------
bool initCamera() {
  camera_config_t cfg;
  cfg.ledc_channel = LEDC_CHANNEL_0;
  cfg.ledc_timer   = LEDC_TIMER_0;
  cfg.pin_d0 = Y2_GPIO_NUM; cfg.pin_d1 = Y3_GPIO_NUM;
  cfg.pin_d2 = Y4_GPIO_NUM; cfg.pin_d3 = Y5_GPIO_NUM;
  cfg.pin_d4 = Y6_GPIO_NUM; cfg.pin_d5 = Y7_GPIO_NUM;
  cfg.pin_d6 = Y8_GPIO_NUM; cfg.pin_d7 = Y9_GPIO_NUM;
  cfg.pin_xclk  = XCLK_GPIO_NUM;  cfg.pin_pclk  = PCLK_GPIO_NUM;
  cfg.pin_vsync = VSYNC_GPIO_NUM; cfg.pin_href  = HREF_GPIO_NUM;
  cfg.pin_sscb_sda = SIOD_GPIO_NUM; cfg.pin_sscb_scl = SIOC_GPIO_NUM;
  cfg.pin_pwdn  = PWDN_GPIO_NUM;  cfg.pin_reset = RESET_GPIO_NUM;
  cfg.xclk_freq_hz = 20000000;

  // JPEG 160x120, qualidade 12 (~3-6 KB por imagem)
  // Qualidade: 0-63; menor = melhor (arquivo maior). 12 é baixo mas legível.
  cfg.pixel_format = PIXFORMAT_JPEG;
  cfg.frame_size   = FRAMESIZE_QQVGA;  // 160x120
  cfg.jpeg_quality = 12;
  cfg.fb_count     = 1;

  esp_err_t err = esp_camera_init(&cfg);
  if (err != ESP_OK) {
    Serial.printf("[camera] erro: 0x%x\n", err);
    return false;
  }

  // Força QQVGA e qualidade via API do sensor APÓS o init.
  // Necessário porque o driver ignora o frame_size do config quando PSRAM
  // está presente (AI Thinker ESP32-CAM tem 4 MB de PSRAM e sobe em resolução
  // maior silenciosamente se não forçar aqui).
  sensor_t* s = esp_camera_sensor_get();
  if (s) {
    s->set_framesize(s, FRAMESIZE_QQVGA);  // 160x120
    s->set_quality(s, 12);                  // qualidade baixa = arquivo menor
    Serial.println("[camera] sensor configurado: QQVGA 160x120 qualidade 12");
  }
  delay(300); // aguarda o sensor aplicar as novas configurações
  return true;
}

// ----------------------------------------------------------------
bool captureImage() {
  if (imgBuf) { free(imgBuf); imgBuf = nullptr; imgSize = 0; }

  camera_fb_t* fb = esp_camera_fb_get();
  if (!fb) { Serial.println("[camera] falha ao capturar"); return false; }

  imgSize = fb->len;
  imgBuf  = (uint8_t*)malloc(imgSize);
  if (!imgBuf) {
    Serial.println("[camera] sem memória");
    esp_camera_fb_return(fb);
    return false;
  }
  memcpy(imgBuf, fb->buf, imgSize);
  esp_camera_fb_return(fb);

  Serial.printf("[camera] JPEG capturado: %d bytes\n", imgSize);

  // Sanidade: QQVGA JPEG com qualidade 12 fica entre ~1 KB e ~20 KB.
  // Se passar disso, a câmera não está em QQVGA - aborta pra não mandar
  // centenas de chunks por engano.
  if (imgSize > 30000) {
    Serial.printf("[ERRO] Imagem grande demais (%d bytes) - câmera provavelmente"
                  " não está em QQVGA. Verifique a inicialização.\n", imgSize);
    free(imgBuf); imgBuf = nullptr; imgSize = 0;
    return false;
  }

  Serial.printf("[camera] ok: %d chunks de %d bytes serão enviados\n",
                (imgSize + CHUNK_DATA_SIZE - 1) / CHUNK_DATA_SIZE, CHUNK_DATA_SIZE);
  return true;
}

// ----------------------------------------------------------------
// Converte bytes para string hex (2 chars por byte)
String toHex(const uint8_t* data, int len) {
  String s;
  s.reserve(len * 2);
  char buf[3];
  for (int i = 0; i < len; i++) {
    sprintf(buf, "%02X", data[i]);
    s += buf;
  }
  return s;
}

// ----------------------------------------------------------------
// Envia um chunk com retry automático em caso de BUSY_ERROR
bool sendChunk(int idx, int total, const uint8_t* data, int dataLen) {
  // Payload binário: [idx_hi][idx_lo][total_hi][total_lo][dados...]
  uint8_t header[4] = {
    (uint8_t)(idx   >> 8), (uint8_t)(idx   & 0xFF),
    (uint8_t)(total >> 8), (uint8_t)(total & 0xFF)
  };
  String hexPayload = toHex(header, 4) + toHex(data, dataLen);
  String cmd = "AT+SENDB=01:" + hexPayload;

  const int MAX_TENT = 5;
  for (int t = 1; t <= MAX_TENT; t++) {
    while (LoRaSerial.available()) LoRaSerial.read(); // drena lixo

    LoRaSerial.println(cmd);
    Serial.printf("[chunk %d/%d tent %d] %d bytes payload\n",
                  idx + 1, total, t, 4 + dataLen);

    // Aguarda resposta real do módulo (TX_OK ou ERROR)
    String resp = "";
    unsigned long ini = millis();
    while (millis() - ini < 2000) {
      if (LoRaSerial.available()) {
        char c = LoRaSerial.read();
        Serial.write(c);
        resp += c;
        if (resp.indexOf("OK") != -1 || resp.indexOf("ERROR") != -1) {
          delay(50);
          while (LoRaSerial.available()) { char c2 = LoRaSerial.read(); Serial.write(c2); resp += c2; }
          break;
        }
      }
    }

    bool ok = (resp.indexOf("TX_OK") != -1) ||
              (resp.indexOf("OK") != -1 && resp.indexOf("ERROR") == -1);
    if (ok) return true;

    Serial.printf("[aviso] chunk %d ocupado, aguardando...\n", idx + 1);
    delay(SEND_INTERVAL_MS);
  }

  Serial.printf("[ERRO] chunk %d falhou após %d tentativas\n", idx + 1, MAX_TENT);
  return false;
}

// ----------------------------------------------------------------
void enviarImagem() {
  if (!imgBuf || imgSize == 0) { Serial.println("Sem imagem."); return; }

  int total = (imgSize + CHUNK_DATA_SIZE - 1) / CHUNK_DATA_SIZE;
  Serial.printf("[envio] %d bytes → %d chunks de %d bytes\n",
                imgSize, total, CHUNK_DATA_SIZE);

  int ok = 0, fail = 0;
  for (int idx = 0; idx < total; idx++) {
    int offset  = idx * CHUNK_DATA_SIZE;
    int dataLen = min(CHUNK_DATA_SIZE, (int)(imgSize - offset));
    if (sendChunk(idx, total, imgBuf + offset, dataLen)) ok++;
    else fail++;
    if (idx < total - 1) delay(SEND_INTERVAL_MS);
  }

  Serial.printf("[envio] concluído: %d ok, %d falhas\n", ok, fail);
}

// ================================================================
void setup() {
  Serial.begin(115200);
  LoRaSerial.begin(9600, SERIAL_8N1, LORA_RX_PIN, LORA_TX_PIN);
  delay(1000);

  Serial.println("ESP32-CAM LoRa Image Sender - TCC");
  Serial.println("Comandos: CAPTURE | AT<cmd>");

  if (initCamera()) Serial.println("[camera] pronta.");
  else Serial.println("[camera] falhou - só bridge AT disponível.");
}

void loop() {
  // Bridge: repassa respostas do Radioenge pro Serial Monitor
  while (LoRaSerial.available()) Serial.write(LoRaSerial.read());

  if (Serial.available()) {
    String linha = Serial.readStringUntil('\n');
    linha.trim();

    if (linha == "CAPTURE") {
      if (captureImage()) enviarImagem();
    } else {
      LoRaSerial.println(linha);  // passa AT direto ao Radioenge
    }
  }
}
