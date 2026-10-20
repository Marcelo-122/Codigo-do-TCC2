// ============================================================
// transmissor_esp32cam.ino
// Transmissor unico do enlace: captura a imagem, divide em chunks e envia
// pelo Radioenge RD49C.
//
// Configuracao de radio (a mesma do receptor_lora32.ino):
//   AU915, canal 64 fixo (915,9 MHz), DR6 = SF8 / BW 500 kHz, sem hopping.
//   Enquadramento: item 10.3 do Ato 14.448/Anatel (BW >= 500 kHz).
//   No Radioenge:  AT+CHMASK=0000:0000:0000:0000:0001:0000  e  AT+DR=6
//   NUNCA use CHMASK com menos de 35 canais em BW = 125 kHz (nao se enquadra
//   em nenhum dos itens do Ato).
//
// Comandos pela Serial (115200):
//   CAPTURE                          captura uma foto e envia todos os chunks
//   RESEND:<i1>,<i2>,...             reenvia so esses chunks da ultima captura
//   SEND:<indice>:<total>:<hex>      envia UM chunk com dados vindos do PC
//                                    (usado pelo orchestrator.py)
//   SENDALL:<n>                      teste de enlace SEM camera: envia n chunks
//                                    com payload fixo
//   AT...                            qualquer outra linha vai direto ao Radioenge
//
// Formato do payload (FPort 1): [index hi][index lo][total hi][total lo][dados...]
// (cabecalho binario de 4 bytes, big-endian). Quem monta o numero do indice
// (0 ou 1 como base) e o chamador; o firmware so repassa.
// ============================================================
#include "esp_camera.h"
#include "img_converters.h"  // fmt2jpg()

// --- Pinos camera (AI Thinker ESP32-CAM) ---
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
#define LORA_RX_PIN 15   // Radioenge TX -> ESP32-CAM RX
#define LORA_TX_PIN 14   // Radioenge RX <- ESP32-CAM TX

HardwareSerial LoRaSerial(1);

// --- Configuracao de chunks ---
// Payload maximo DR6 (AU915, SF8/500kHz): 222 bytes (manual Radioenge, Tabela 8)
// Header binario: 4 bytes (uint16 index + uint16 total, big-endian)
// Dados por chunk: 100 bytes -> payload total 104 bytes (118 B de folga).
// Escolha validada no hardware; blocos menores perdem menos dados por pacote
// perdido. Tempo no ar por pacote: ~87 ms (SF8/500 kHz).
const int CHUNK_DATA_SIZE = 100;

// Intervalo entre chunks (ms). O item 10.3 do Ato 14.448 nao define intervalo
// minimo no canal fixo de 500 kHz; 7000 ms e um valor conservador.
const unsigned long SEND_INTERVAL_MS = 7000;

// --- Captura: cinza 160x120 -> JPEG ---
// O sensor entrega 1 byte/pixel (19.200 B) e o JPEG e gerado por software.
// ATENCAO: a escala de JPEG_QUALITY e a do fmt2jpg (1-100, MAIOR = melhor),
// ao contrario do jpeg_quality da camera (0-63, menor = melhor).
// Tamanho esperado do JPEG (PoC em poc_diminuicao_imagem/output.txt):
// ~1,6 KB (q30), ~2,0 KB (q50), ~2,6 KB (q80).
const int CAM_W = 160;
const int CAM_H = 120;
const int JPEG_QUALITY = 80;

// --- Buffer de imagem ---
static uint8_t* imgBuf  = nullptr;
static size_t   imgSize = 0;

// ----------------------------------------------------------------
bool initCamera() {
  // Zerado explicitamente: campos nao setados (fb_location, grab_mode...)
  // ficariam com lixo da pilha e o driver se comportaria de forma imprevisivel.
  camera_config_t cfg = {};
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

  // Cinza 160x120 direto do sensor (1 byte/pixel). O JPEG e gerado depois,
  // em captureImage(), com fmt2jpg().
  cfg.pixel_format = PIXFORMAT_GRAYSCALE;
  cfg.frame_size   = FRAMESIZE_QQVGA;  // 160x120
  cfg.fb_count     = 1;
  cfg.fb_location  = CAMERA_FB_IN_PSRAM;
  cfg.grab_mode    = CAMERA_GRAB_WHEN_EMPTY;

  esp_err_t err = esp_camera_init(&cfg);
  if (err != ESP_OK) {
    Serial.printf("[camera] erro: 0x%x\n", err);
    return false;
  }

  // NAO chamar sensor->set_framesize() depois do init: em modo cinza isso
  // fazia o driver falhar com "Failed to resize buffer" (a PSRAM nao tem folga
  // para o buffer antigo e o novo ao mesmo tempo). O frame_size do config
  // ja vale. Mesmo padrao do debug_ocr_esp32cam.ino.
  Serial.println("[camera] sensor configurado: GRAYSCALE QQVGA 160x120");
  delay(300); // aguarda o sensor estabilizar
  return true;
}

// ----------------------------------------------------------------
bool captureImage() {
  if (imgBuf) { free(imgBuf); imgBuf = nullptr; imgSize = 0; }

  camera_fb_t* fb = esp_camera_fb_get();
  if (!fb) { Serial.println("[camera] falha ao capturar"); return false; }

  // Sanidade: tem que ser exatamente 160x120. Se vier outra resolucao, aborta
  // para nao mandar centenas de chunks por engano.
  if (fb->width != CAM_W || fb->height != CAM_H) {
    Serial.printf("[ERRO] quadro %dx%d, esperado %dx%d. Verifique a inicializacao.\n",
                  (int)fb->width, (int)fb->height, CAM_W, CAM_H);
    esp_camera_fb_return(fb);
    return false;
  }

  // Comprime o quadro cinza em JPEG; fmt2jpg aloca o buffer de saida (free()).
  uint8_t* jpgBuf = nullptr;
  size_t   jpgLen = 0;
  bool ok = fmt2jpg(fb->buf, fb->len, fb->width, fb->height,
                    PIXFORMAT_GRAYSCALE, JPEG_QUALITY, &jpgBuf, &jpgLen);
  esp_camera_fb_return(fb);

  if (!ok || !jpgBuf || jpgLen == 0) {
    Serial.println("[camera] fmt2jpg falhou");
    return false;
  }
  imgBuf  = jpgBuf;
  imgSize = jpgLen;

  Serial.printf("[camera] JPEG cinza %dx%d qualidade %d: %d bytes\n",
                CAM_W, CAM_H, JPEG_QUALITY, (int)imgSize);

  Serial.printf("[camera] ok: %d chunks de %d bytes serao enviados\n",
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
// Converte um hex ("A1B2...") em bytes. Retorna o numero de bytes, ou -1 se
// o texto for invalido ou nao couber em `maxLen`.
int fromHex(const String& hex, uint8_t* out, int maxLen) {
  int n = hex.length();
  if (n % 2 != 0 || n / 2 > maxLen) return -1;
  for (int i = 0; i < n / 2; i++) {
    char pair[3] = { hex[2 * i], hex[2 * i + 1], 0 };
    char* end;
    long v = strtol(pair, &end, 16);
    if (*end != 0) return -1;
    out[i] = (uint8_t)v;
  }
  return n / 2;
}

// ----------------------------------------------------------------
// Envia um chunk com retry automatico em caso de BUSY_ERROR
bool sendChunk(int idx, int total, const uint8_t* data, int dataLen) {
  // Payload binario: [idx_hi][idx_lo][total_hi][total_lo][dados...]
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
                  idx, total, t, 4 + dataLen);

    // Aguarda resposta real do modulo (TX_OK ou ERROR)
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

    Serial.printf("[aviso] chunk %d ocupado, aguardando...\n", idx);
    delay(SEND_INTERVAL_MS);
  }

  Serial.printf("[ERRO] chunk %d falhou apos %d tentativas\n", idx, MAX_TENT);
  return false;
}

// ----------------------------------------------------------------
// Envia o chunk `idx` (base 0) da imagem capturada.
bool sendImageChunk(int idx) {
  int total = (imgSize + CHUNK_DATA_SIZE - 1) / CHUNK_DATA_SIZE;
  if (idx < 0 || idx >= total) {
    Serial.printf("[ERRO] chunk %d fora do intervalo 0..%d\n", idx, total - 1);
    return false;
  }
  int offset  = idx * CHUNK_DATA_SIZE;
  int dataLen = min(CHUNK_DATA_SIZE, (int)(imgSize - offset));
  return sendChunk(idx, total, imgBuf + offset, dataLen);
}

// ----------------------------------------------------------------
void enviarImagem() {
  if (!imgBuf || imgSize == 0) { Serial.println("Sem imagem."); return; }

  int total = (imgSize + CHUNK_DATA_SIZE - 1) / CHUNK_DATA_SIZE;
  Serial.printf("[envio] %d bytes -> %d chunks de %d bytes\n",
                imgSize, total, CHUNK_DATA_SIZE);

  int ok = 0, fail = 0;
  for (int idx = 0; idx < total; idx++) {
    if (sendImageChunk(idx)) ok++;
    else fail++;
    if (idx < total - 1) delay(SEND_INTERVAL_MS);
  }

  Serial.printf("[envio] concluido: %d ok, %d falhas\n", ok, fail);
}

// ----------------------------------------------------------------
// RESEND:2,7,15 - reenvia so esses indices (base 0) da ultima captura.
void reenviar(const String& lista) {
  if (!imgBuf || imgSize == 0) { Serial.println("Sem imagem. Use CAPTURE antes."); return; }

  Serial.print("Reenviando indices: ");
  Serial.println(lista);

  int start = 0;
  while (start < (int)lista.length()) {
    int comma = lista.indexOf(',', start);
    String token = (comma == -1) ? lista.substring(start) : lista.substring(start, comma);
    token.trim();
    if (token.length() > 0) {
      sendImageChunk(token.toInt());
      delay(SEND_INTERVAL_MS);
    }
    if (comma == -1) break;
    start = comma + 1;
  }

  Serial.println("Reenvio concluido.");
}

// ----------------------------------------------------------------
// SEND:<indice>:<total>:<dados-hex> - dados vindos do PC (orchestrator.py).
void enviarDoPc(const String& resto) {
  int p1 = resto.indexOf(':');
  int p2 = (p1 == -1) ? -1 : resto.indexOf(':', p1 + 1);
  if (p1 == -1 || p2 == -1) {
    Serial.println("[ERRO] formato invalido. Use SEND:<indice>:<total>:<dados-hex>");
    return;
  }

  int idx   = resto.substring(0, p1).toInt();
  int total = resto.substring(p1 + 1, p2).toInt();

  uint8_t dados[CHUNK_DATA_SIZE];
  int dataLen = fromHex(resto.substring(p2 + 1), dados, CHUNK_DATA_SIZE);
  if (dataLen < 0) {
    Serial.printf("[ERRO] dados-hex invalidos ou maiores que %d bytes\n", CHUNK_DATA_SIZE);
    return;
  }
  sendChunk(idx, total, dados, dataLen);
}

// ----------------------------------------------------------------
// SENDALL:<n> - teste de enlace sem camera, com payload fixo.
void enviarTeste(int total) {
  uint8_t dados[CHUNK_DATA_SIZE];
  for (int i = 0; i < CHUNK_DATA_SIZE; i++) dados[i] = (uint8_t)i;

  Serial.printf("Teste de enlace: %d chunks de %d bytes (payload fixo)\n",
                total, CHUNK_DATA_SIZE);
  for (int idx = 0; idx < total; idx++) {
    sendChunk(idx, total, dados, CHUNK_DATA_SIZE);
    if (idx < total - 1) delay(SEND_INTERVAL_MS);
  }
  Serial.println("Teste concluido.");
}

// ================================================================
void setup() {
  Serial.begin(115200);
  LoRaSerial.begin(9600, SERIAL_8N1, LORA_RX_PIN, LORA_TX_PIN);
  delay(1000);

  Serial.println("ESP32-CAM LoRa Image Sender - TCC");
  Serial.println("Comandos: CAPTURE | RESEND:<i,j,...> | SEND:<i>:<total>:<hex> | SENDALL:<n> | AT<cmd>");

  if (initCamera()) Serial.println("[camera] pronta.");
  else Serial.println("[camera] falhou - so bridge AT e SEND/SENDALL disponiveis.");
}

void loop() {
  // Bridge: repassa respostas do Radioenge pro Serial Monitor
  while (LoRaSerial.available()) Serial.write(LoRaSerial.read());

  if (Serial.available()) {
    String linha = Serial.readStringUntil('\n');
    linha.trim();

    if (linha == "CAPTURE") {
      if (captureImage()) enviarImagem();
    } else if (linha.startsWith("RESEND:")) {
      reenviar(linha.substring(7));
    } else if (linha.startsWith("SEND:")) {
      enviarDoPc(linha.substring(5));
    } else if (linha.startsWith("SENDALL:")) {
      enviarTeste(linha.substring(8).toInt());
    } else {
      LoRaSerial.println(linha);  // passa AT direto ao Radioenge
    }
  }
}
