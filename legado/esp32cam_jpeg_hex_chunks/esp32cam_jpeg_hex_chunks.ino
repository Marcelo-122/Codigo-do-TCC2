/*
 * ESP32-CAM: capture a JPEG frame and send it over USB Serial as
 * sequential 85-byte hex-encoded chunks.
 *
 * Board: AI-Thinker ESP32-CAM (adjust pin map below if you're on a
 * different board, e.g. ESP-EYE, M5Stack-CAM, WROVER-KIT).
 *
 * Framing sent over Serial (plain ASCII, one line per message):
 *   BEGIN,<total_bytes>,<total_chunks>
 *   CHUNK,<index>,<len>,<hex_payload>
 *   END,<crc32_hex>
 *
 * <hex_payload> is the chunk's raw bytes encoded as 2 hex chars per
 * byte (so up to 85 bytes -> up to 170 hex chars per line).
 * A trailing chunk shorter than 85 bytes has <len> < 85.
 *
 * A simple CRC32 of the full JPEG is sent at the end so a receiving
 * script can verify reassembly.
 */

#include "esp_camera.h"
#include "esp_crc.h"

// ===== Camera pin map: AI-Thinker ESP32-CAM =====
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

static const size_t CHUNK_SIZE = 85;      // bytes of raw JPEG per chunk
static const uint32_t CHUNK_DELAY_MS = 20; // small gap so the receiver keeps up

static const char HEX_DIGITS[] = "0123456789ABCDEF";

// Encode `len` raw bytes at `src` into a hex string at `dst`.
// `dst` must have room for 2*len + 1 bytes.
static void bytesToHex(const uint8_t *src, size_t len, char *dst) {
  for (size_t i = 0; i < len; i++) {
    dst[i * 2]     = HEX_DIGITS[(src[i] >> 4) & 0x0F];
    dst[i * 2 + 1] = HEX_DIGITS[src[i] & 0x0F];
  }
  dst[len * 2] = '\0';
}

bool initCamera() {
  camera_config_t config;
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer   = LEDC_TIMER_0;
  config.pin_d0 = Y2_GPIO_NUM;
  config.pin_d1 = Y3_GPIO_NUM;
  config.pin_d2 = Y4_GPIO_NUM;
  config.pin_d3 = Y5_GPIO_NUM;
  config.pin_d4 = Y6_GPIO_NUM;
  config.pin_d5 = Y7_GPIO_NUM;
  config.pin_d6 = Y8_GPIO_NUM;
  config.pin_d7 = Y9_GPIO_NUM;
  config.pin_xclk = XCLK_GPIO_NUM;
  config.pin_pclk = PCLK_GPIO_NUM;
  config.pin_vsync = VSYNC_GPIO_NUM;
  config.pin_href = HREF_GPIO_NUM;
  config.pin_sscb_sda = SIOD_GPIO_NUM;
  config.pin_sscb_scl = SIOC_GPIO_NUM;
  config.pin_pwdn = PWDN_GPIO_NUM;
  config.pin_reset = RESET_GPIO_NUM;
  config.xclk_freq_hz = 20000000;
  config.pixel_format = PIXFORMAT_JPEG;

  // Smaller frame + higher jpeg_quality number = more compression,
  // fewer chunks to send. Tune to taste.
  if (psramFound()) {
    config.frame_size = FRAMESIZE_SVGA; // 800x600
    config.jpeg_quality = 12;           // 0-63, lower = better quality
    config.fb_count = 2;
  } else {
    config.frame_size = FRAMESIZE_QVGA; // 320x240
    config.jpeg_quality = 15;
    config.fb_count = 1;
  }

  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
    Serial.printf("Camera init failed: 0x%x\n", err);
    return false;
  }
  return true;
}

void sendFrameAsHexChunks(camera_fb_t *fb) {
  size_t totalBytes = fb->len;
  size_t totalChunks = (totalBytes + CHUNK_SIZE - 1) / CHUNK_SIZE;

  uint32_t crc = esp_crc32_le(0, fb->buf, fb->len);

  Serial.printf("BEGIN,%u,%u\n", (unsigned)totalBytes, (unsigned)totalChunks);

  char hexBuf[CHUNK_SIZE * 2 + 1];
  size_t offset = 0;
  for (size_t i = 0; i < totalChunks; i++) {
    size_t len = min(CHUNK_SIZE, totalBytes - offset);
    bytesToHex(fb->buf + offset, len, hexBuf);
    Serial.printf("CHUNK,%u,%u,%s\n", (unsigned)i, (unsigned)len, hexBuf);
    offset += len;
    delay(CHUNK_DELAY_MS);
  }

  Serial.printf("END,%08X\n", crc);
}

void setup() {
  Serial.begin(115200);
  Serial.setDebugOutput(false);
  delay(1000);

  if (!initCamera()) {
    Serial.println("Halting: camera init failed.");
    while (true) delay(1000);
  }
  Serial.println("Camera ready.");
}

void loop() {
  camera_fb_t *fb = esp_camera_fb_get();
  if (!fb) {
    Serial.println("Capture failed.");
    delay(2000);
    return;
  }

  sendFrameAsHexChunks(fb);
  esp_camera_fb_return(fb);

  delay(5000); // wait before next capture; adjust/remove as needed
}
