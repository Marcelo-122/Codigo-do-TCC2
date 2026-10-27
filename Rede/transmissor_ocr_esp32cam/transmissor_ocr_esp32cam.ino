// ============================================================
// transmissor_ocr_esp32cam.ino
// Transmissor do fluxo "OCR na borda": captura um quadro cinza, le os digitos do
// medidor na propria ESP32-CAM (segmentacao + classificador de digito, TFLite Micro)
// e envia so a leitura (poucos bytes) pelo Radioenge RD49C. Depois dorme.
//
// Irmao do transmissor_esp32cam.ino (fluxo de IMAGEM): mesmo radio, mesmos pinos,
// mesmo deep sleep e mesma linha [CICLO_FIM], para as medicoes dos dois fluxos
// (corrente.py, latencia_ponta_a_ponta.py) serem comparaveis. O OCR vem do
// test_images/debug_ocr_esp32cam/debug_ocr_esp32cam.ino (mesmos modelos e mesma
// logica); aqui nao ha desenho nem envio de imagem pela serial.
//
// Esta versao MANTEM a segmentacao a cada leitura (~15,6 s). Quando a ROI fixa for
// implementada (ver README, "Tirar a segmentacao do firmware"), so executarOcr() muda.
//
// Arquivos do sketch: modelo.h e modelo_digito.h sao COPIAS dos de
// test_images/debug_ocr_esp32cam/ (o Arduino so enxerga arquivos desta pasta). Se os
// modelos forem retreinados, copie de novo.
//
// Compilar como no debug_ocr_esp32cam: placa "AI Thinker ESP32-CAM", PSRAM habilitada,
// biblioteca TensorFlow Lite Micro instalada.
//
// Configuracao de radio (a mesma do transmissor_esp32cam.ino e do receptor_lora32.ino):
//   AU915, canal 64 fixo (915,9 MHz), DR6 = SF8 / BW 500 kHz, sem hopping.
//
// Comandos pela Serial (115200):
//   LER                              le o medidor e envia a leitura (um uplink)
//   AUTO[:<s>]                       modo autonomo: acorda, le, envia a leitura e entra
//                                    em deep sleep por <s> segundos (padrao 600).
//                                    Repete ate receber STOP.
//   STOP                             sai do modo autonomo (so e lido na janela de
//                                    JANELA_STOP_MS logo apos cada despertar)
//   SLEEP:<s>                        deep sleep unico de <s> segundos, sem leitura
//   AT...                            qualquer outra linha vai direto ao Radioenge
//
// Formato do payload (FPort 2, AT+SENDB=02:<hex>), bytes:
//   [id hi][id lo][flags][d0][d1]...[dN-1]
//   flags: bit 7 = caixa dos digitos achada; bits 0-6 = numero de digitos N
//   d0..dN-1: ASCII do digito ('0'-'9'); '?' = fatia nao classificada; '-' = sem caixa
// O fluxo de imagem usa FPort 1 (cabecalho de 6 bytes). No PC, enlace.parse_leitura() le este
// formato; o reconstrutor.py (transmissao_ocr.csv) e o latencia_ponta_a_ponta.py (--fluxo ocr)
// aceitam a FPort 2. Linhas que o PC procura na serial: "[ocr] leitura=...",
// "[ocr] enviando leitura id N" e "[uplink tent N] ...".
// ============================================================
#include "esp_camera.h"
#include "driver/rtc_io.h"
#include "esp_sleep.h"
#include "esp_heap_caps.h"

#include "modelo.h"         // array modelo_tflite[] (segmentacao)
#include "modelo_digito.h"  // array modelo_digito_tflite[] (classificador de digito)

// ---- TensorFlow Lite Micro ----
#include "tensorflow/lite/micro/micro_interpreter.h"
#include "tensorflow/lite/micro/micro_mutable_op_resolver.h"
#include "tensorflow/lite/micro/micro_log.h"
#include "tensorflow/lite/schema/schema_generated.h"

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

// --- Captura e modelos (mesmos valores do debug_ocr_esp32cam) ---
static const int CAM_W = 160;
static const int CAM_H = 120;
static const int MODEL_W = 192;   // entrada da segmentacao: 192x192x1 int8
static const int MODEL_H = 192;
static const int DIGIT_W = 28;    // entrada do classificador: 28x28x1 int8
static const int DIGIT_H = 28;

// Numero de rodinhas do medidor alvo (so afeta o fatiamento da caixa, nao o treino).
static const int N_FATIAS = 6;

// Arenas na PSRAM (a camera ja foi desligada quando os modelos sao alocados).
static const int TENSOR_ARENA_SIZE = 2 * 1024 * 1024;  // segmentacao: usa ~1,62 MB
static const int DIGIT_ARENA_SIZE  = 768 * 1024;       // digito: usa ~28 KB
static uint8_t* tensor_arena = nullptr;
static uint8_t* digit_arena  = nullptr;

// --- Envio da leitura ---
const int MAX_TENT = 5;                     // tentativas se o modulo responder ocupado
const unsigned long RETRY_MS = 7000;        // espera entre tentativas

// --- Deep sleep (modo autonomo) ---
// Desligue o flash (GPIO4) e a camera (PWDN, GPIO32, ativo em nivel alto) antes de
// dormir e segure esses niveis com hold. O Radioenge continua alimentado (so o ESP32
// dorme), entao a sessao LoRaWAN e o contador de quadros ficam no modulo.
#define FLASH_LED_GPIO GPIO_NUM_4
#define AUTO_AO_LIGAR  0                      // 1 = modo autonomo ja no power-on
const uint32_t INTERVALO_PADRAO_S = 30;       // dormida padrao do AUTO (igual ao teste de imagem)
const uint32_t INTERVALO_MIN_S    = 10;
const unsigned long JANELA_STOP_MS = 1500;    // tempo acordado esperando STOP; ponha 0
                                              // (e AUTO_AO_LIGAR 1) para medir o consumo de producao

// RTC_DATA_ATTR sobrevive ao deep sleep (nao ao power-on reset).
RTC_DATA_ATTR static bool     autoAtivo      = (AUTO_AO_LIGAR != 0);
RTC_DATA_ATTR static uint32_t autoIntervaloS = INTERVALO_PADRAO_S;
RTC_DATA_ATTR static uint32_t cicloN         = 0;

static bool camPronta = false;
static bool segOk = false;     // modelo de segmentacao inicializado neste boot
static bool digOk = false;     // classificador de digito inicializado neste boot

// Definido antes de qualquer funcao: o Arduino gera os prototipos acima da primeira funcao.
struct ResultadoOcr {
  bool ok;       // captura, modelos e segmentacao rodaram (o envio faz sentido)
  bool achou;    // a segmentacao achou a caixa dos digitos
  char leitura[N_FATIAS + 1];
  unsigned long t_captura, t_modelos, t_seg, t_digitos;  // ms
};

namespace {
const tflite::Model* modelo = nullptr;
tflite::MicroInterpreter* interpreter = nullptr;
TfLiteTensor* input = nullptr;
TfLiteTensor* output = nullptr;

const tflite::Model* modeloDigito = nullptr;
tflite::MicroInterpreter* interpreterDigito = nullptr;
TfLiteTensor* inputDigito = nullptr;
TfLiteTensor* outputDigito = nullptr;
}  // namespace

// ----------------------------------------------------------------
bool iniciarModelo() {
  modelo = tflite::GetModel(modelo_tflite);
  if (modelo->version() != TFLITE_SCHEMA_VERSION) {
    Serial.printf("[tflite] versao do schema incompativel: modelo=%d lib=%d\n",
                  (int)modelo->version(), TFLITE_SCHEMA_VERSION);
    return false;
  }

  tensor_arena = (uint8_t*)heap_caps_malloc(TENSOR_ARENA_SIZE, MALLOC_CAP_SPIRAM);
  if (!tensor_arena) {
    Serial.println("[tflite] falha ao alocar tensor_arena na PSRAM");
    return false;
  }

  // Operadores da segmentacao (CONV_2D, MAX_POOL_2D, TRANSPOSE_CONV, LOGISTIC).
  static tflite::MicroMutableOpResolver<4> resolver;
  resolver.AddConv2D();
  resolver.AddMaxPool2D();
  resolver.AddTransposeConv();
  resolver.AddLogistic();

  static tflite::MicroInterpreter static_interpreter(
      modelo, resolver, tensor_arena, TENSOR_ARENA_SIZE);
  interpreter = &static_interpreter;

  if (interpreter->AllocateTensors() != kTfLiteOk) {
    Serial.println("[tflite] AllocateTensors falhou (tensor_arena pequeno?)");
    return false;
  }

  input = interpreter->input(0);
  output = interpreter->output(0);
  Serial.printf("[tflite] segmentacao pronta. arena_usado=%u bytes\n",
                (unsigned)interpreter->arena_used_bytes());
  return true;
}

bool iniciarModeloDigito() {
  modeloDigito = tflite::GetModel(modelo_digito_tflite);
  if (modeloDigito->version() != TFLITE_SCHEMA_VERSION) {
    Serial.printf("[tflite] digito: versao do schema incompativel: modelo=%d lib=%d\n",
                  (int)modeloDigito->version(), TFLITE_SCHEMA_VERSION);
    return false;
  }

  digit_arena = (uint8_t*)heap_caps_malloc(DIGIT_ARENA_SIZE, MALLOC_CAP_SPIRAM);
  if (!digit_arena) {
    Serial.println("[tflite] digito: falha ao alocar digit_arena na PSRAM");
    return false;
  }

  // Operadores do classificador (CONV_2D, MAX_POOL_2D, SHAPE, STRIDED_SLICE, PACK,
  // RESHAPE, FULLY_CONNECTED, SOFTMAX).
  static tflite::MicroMutableOpResolver<8> resolverDigito;
  resolverDigito.AddConv2D();
  resolverDigito.AddMaxPool2D();
  resolverDigito.AddShape();
  resolverDigito.AddStridedSlice();
  resolverDigito.AddPack();
  resolverDigito.AddReshape();
  resolverDigito.AddFullyConnected();
  resolverDigito.AddSoftmax();

  static tflite::MicroInterpreter static_interpreter_digito(
      modeloDigito, resolverDigito, digit_arena, DIGIT_ARENA_SIZE);
  interpreterDigito = &static_interpreter_digito;

  if (interpreterDigito->AllocateTensors() != kTfLiteOk) {
    Serial.println("[tflite] digito: AllocateTensors falhou (digit_arena pequeno?)");
    return false;
  }

  inputDigito = interpreterDigito->input(0);
  outputDigito = interpreterDigito->output(0);
  Serial.printf("[tflite] digito pronto. arena_usado=%u bytes\n",
                (unsigned)interpreterDigito->arena_used_bytes());
  return true;
}

// ----------------------------------------------------------------
bool initCamera() {
  // Zerado explicitamente: campos nao setados ficariam com lixo da pilha.
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

  // Cinza 160x120 direto do sensor (1 byte/pixel): e o formato que o modelo le.
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

  // NAO chamar sensor->set_framesize() depois do init (causa "Failed to resize buffer").
  Serial.println("[camera] sensor configurado: GRAYSCALE QQVGA 160x120");
  delay(300); // aguarda o sensor estabilizar
  return true;
}

// Desliga a camera (driver + power-down do sensor) assim que o quadro foi copiado: a
// inferencia dura ~18 s e nao precisa dela. Sem hold: dormir() segura o nivel do pino e
// o setup() o libera antes do proximo esp_camera_init.
void desligarCamera() {
  esp_camera_deinit();
  pinMode(PWDN_GPIO_NUM, OUTPUT);
  digitalWrite(PWDN_GPIO_NUM, HIGH);  // PWDN ativo em nivel alto
  camPronta = false;
  Serial.println("[camera] desligada apos a captura");
}

// ----------------------------------------------------------------
// Redimensiona (vizinho mais proximo) CAM_WxCAM_H -> MODEL_WxMODEL_H direto no tensor
// de entrada (pixel 0-255 -> int8 com zero_point -128).
void prepararEntradaModelo(const uint8_t* frame) {
  for (int y = 0; y < MODEL_H; y++) {
    int ySrc = (y * CAM_H) / MODEL_H;
    for (int x = 0; x < MODEL_W; x++) {
      int xSrc = (x * CAM_W) / MODEL_W;
      uint8_t pixel = frame[ySrc * CAM_W + xSrc];
      input->data.int8[y * MODEL_W + x] = (int8_t)((int)pixel - 128);
    }
  }
}

// Caixa dos digitos a partir da mascara de saida (int8 > 0 == probabilidade > 0,5),
// em coordenadas do quadro CAM_WxCAM_H. Retorna false se a mascara estiver vazia.
bool acharCaixaDigitos(int* bx0, int* by0, int* bx1, int* by1) {
  int minX = MODEL_W, minY = MODEL_H, maxX = -1, maxY = -1;
  int8_t* saida = output->data.int8;

  for (int y = 0; y < MODEL_H; y++) {
    for (int x = 0; x < MODEL_W; x++) {
      if (saida[y * MODEL_W + x] > 0) {
        if (x < minX) minX = x;
        if (x > maxX) maxX = x;
        if (y < minY) minY = y;
        if (y > maxY) maxY = y;
      }
    }
  }

  if (maxX < 0) return false;

  *bx0 = (minX * CAM_W) / MODEL_W;
  *bx1 = (maxX * CAM_W) / MODEL_W;
  *by0 = (minY * CAM_H) / MODEL_H;
  *by1 = (maxY * CAM_H) / MODEL_H;
  return true;
}

// Classifica UMA fatia (sx0..sx1, sy0..sy1 do quadro) como digito 0-9, ou -1 se falhar.
int classificarFatia(const uint8_t* frame, int sx0, int sy0, int sx1, int sy1) {
  int larguraFatia = sx1 - sx0;
  int alturaFatia = sy1 - sy0;
  if (larguraFatia <= 0) larguraFatia = 1;
  if (alturaFatia <= 0) alturaFatia = 1;

  for (int y = 0; y < DIGIT_H; y++) {
    int ySrc = sy0 + (y * alturaFatia) / DIGIT_H;
    for (int x = 0; x < DIGIT_W; x++) {
      int xSrc = sx0 + (x * larguraFatia) / DIGIT_W;
      uint8_t pixel = frame[ySrc * CAM_W + xSrc];
      inputDigito->data.int8[y * DIGIT_W + x] = (int8_t)((int)pixel - 128);
    }
  }

  if (interpreterDigito->Invoke() != kTfLiteOk) return -1;

  int8_t* saida = outputDigito->data.int8;
  int melhorClasse = 0;
  int8_t melhorValor = saida[0];
  for (int c = 1; c < 10; c++) {
    if (saida[c] > melhorValor) {
      melhorValor = saida[c];
      melhorClasse = c;
    }
  }
  return melhorClasse;
}

// Fatia a caixa em N_FATIAS pedacos de largura igual e classifica cada um.
// "saida" precisa ter N_FATIAS+1 chars.
void lerDigitos(const uint8_t* frame, int x0, int y0, int x1, int y1, char* saida) {
  int largura = x1 - x0;
  for (int i = 0; i < N_FATIAS; i++) {
    int sx0 = x0 + (largura * i) / N_FATIAS;
    int sx1 = x0 + (largura * (i + 1)) / N_FATIAS;
    int digito = classificarFatia(frame, sx0, y0, sx1, y1);
    saida[i] = (digito >= 0 && digito <= 9) ? ('0' + digito) : '?';
  }
  saida[N_FATIAS] = '\0';
}

// ----------------------------------------------------------------
// Captura, copia o quadro, desliga a camera, inicializa os modelos (uma vez por boot)
// e le os digitos. Sem caixa, a leitura fica "------" e ok continua true.
ResultadoOcr executarOcr() {
  ResultadoOcr r = {};
  memset(r.leitura, '-', N_FATIAS);
  r.leitura[N_FATIAS] = '\0';

  if (!camPronta) camPronta = initCamera();
  if (!camPronta) { Serial.println("[ocr] camera indisponivel"); return r; }

  unsigned long t0 = millis();
  camera_fb_t* fb = esp_camera_fb_get();
  if (!fb) {
    Serial.println("[camera] falha ao capturar");
    desligarCamera();
    return r;
  }
  if (fb->width != CAM_W || fb->height != CAM_H) {
    Serial.printf("[ERRO] quadro %dx%d, esperado %dx%d\n",
                  (int)fb->width, (int)fb->height, CAM_W, CAM_H);
    esp_camera_fb_return(fb);
    desligarCamera();
    return r;
  }
  // Copia propria: o buffer da camera e devolvido e a camera desligada antes da inferencia.
  uint8_t* frame = (uint8_t*)malloc(CAM_W * CAM_H);
  if (!frame) {
    Serial.println("[ERRO] sem memoria para o quadro");
    esp_camera_fb_return(fb);
    desligarCamera();
    return r;
  }
  memcpy(frame, fb->buf, CAM_W * CAM_H);
  esp_camera_fb_return(fb);
  r.t_captura = millis() - t0;
  desligarCamera();

  t0 = millis();
  if (!segOk) segOk = iniciarModelo();
  if (segOk && !digOk) digOk = iniciarModeloDigito();
  r.t_modelos = millis() - t0;
  if (!segOk || !digOk) {
    Serial.println("[ocr] modelos indisponiveis");
    free(frame);
    return r;
  }

  t0 = millis();
  prepararEntradaModelo(frame);
  bool inferiu = (interpreter->Invoke() == kTfLiteOk);
  int bx0 = 0, by0 = 0, bx1 = 0, by1 = 0;
  if (inferiu) r.achou = acharCaixaDigitos(&bx0, &by0, &bx1, &by1);
  else Serial.println("[tflite] Invoke() (segmentacao) falhou");
  r.t_seg = millis() - t0;

  t0 = millis();
  if (r.achou) lerDigitos(frame, bx0, by0, bx1, by1, r.leitura);
  r.t_digitos = millis() - t0;
  free(frame);

  r.ok = inferiu;
  Serial.printf("[ocr] leitura=%s achou_caixa=%d bx0=%d by0=%d bx1=%d by1=%d\n",
                r.leitura, r.achou ? 1 : 0, bx0, by0, bx1, by1);
  return r;
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
// Envia um uplink na FPort 2 com retry automatico se o modulo responder ocupado.
bool enviarUplink(const uint8_t* dados, int len) {
  String cmd = "AT+SENDB=02:" + toHex(dados, len);

  for (int t = 1; t <= MAX_TENT; t++) {
    while (LoRaSerial.available()) LoRaSerial.read(); // drena lixo

    LoRaSerial.println(cmd);
    Serial.printf("[uplink tent %d] %d bytes payload\n", t, len);

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

    Serial.println("[aviso] modulo ocupado, aguardando...");
    delay(RETRY_MS);
  }

  Serial.printf("[ERRO] uplink falhou apos %d tentativas\n", MAX_TENT);
  return false;
}

// [id hi][id lo][flags][digitos ASCII...] (ver cabecalho do arquivo)
bool enviarLeitura(uint16_t id, const ResultadoOcr& r) {
  Serial.printf("[ocr] enviando leitura id %u\n", (unsigned)id);  // o PC casa o uplink com o disparo
  uint8_t payload[3 + N_FATIAS];
  payload[0] = (uint8_t)(id >> 8);
  payload[1] = (uint8_t)(id & 0xFF);
  payload[2] = (uint8_t)((r.achou ? 0x80 : 0x00) | N_FATIAS);
  memcpy(payload + 3, r.leitura, N_FATIAS);
  return enviarUplink(payload, sizeof(payload));
}

// Segura um pino em nivel fixo durante o deep sleep.
static void pinoSegurar(gpio_num_t pino, int nivel) {
  rtc_gpio_init(pino);
  rtc_gpio_set_direction(pino, RTC_GPIO_MODE_OUTPUT_ONLY);
  rtc_gpio_set_level(pino, nivel);
  rtc_gpio_hold_en(pino);
}

// Devolve o pino ao controle normal (obrigatorio antes de esp_camera_init).
static void pinoLiberar(gpio_num_t pino) {
  rtc_gpio_hold_dis(pino);
  rtc_gpio_deinit(pino);
}

// ----------------------------------------------------------------
// Entra em deep sleep por `segundos`. Nao retorna: ao acordar o ESP32 reinicia
// e executa setup() de novo.
void dormir(uint32_t segundos) {
  esp_camera_deinit();  // erro se a camera ja foi desligada: pode ser ignorado
  pinoSegurar((gpio_num_t)PWDN_GPIO_NUM, 1);  // camera em power-down
  pinoSegurar(FLASH_LED_GPIO, 0);             // flash apagado

  Serial.printf("[sleep] deep sleep por %u s\n", (unsigned)segundos);
  Serial.flush();
  LoRaSerial.flush();

  esp_sleep_enable_timer_wakeup((uint64_t)segundos * 1000000ULL);
  esp_deep_sleep_start();
}

// ----------------------------------------------------------------
// Um ciclo do modo autonomo: le o medidor, envia a leitura e dorme. Mesmo se o OCR ou o
// envio falharem, o no dorme. Tempos em ms contados desde o despertar (millis() zera a
// cada boot); o boot da ROM antes do setup() nao esta incluido.
// Para o corrente.py: --init-s = t_ate_ciclo, --captura-s = captura+modelos+seg+digitos,
// --envio-s = t_envio.
void cicloAutonomo() {
  cicloN++;
  unsigned long t_inicio = millis();

  ResultadoOcr r = executarOcr();

  int falhas = -1;
  unsigned long t_envio = 0;
  if (r.ok) {
    unsigned long t0 = millis();
    falhas = enviarLeitura((uint16_t)esp_random(), r) ? 0 : 1;
    t_envio = millis() - t0;
  } else {
    Serial.println("[ciclo] OCR nao rodou, nada a enviar");
  }

  uint32_t dorme = autoIntervaloS;
  Serial.printf("[CICLO_FIM] ciclo=%u ok=%d chunks=%d falhas=%d leitura=%s achou=%d "
                "t_ate_ciclo_ms=%lu t_captura_ms=%lu t_modelos_ms=%lu t_seg_ms=%lu "
                "t_digitos_ms=%lu t_envio_ms=%lu t_ativo_ms=%lu sleep_s=%u\n",
                (unsigned)cicloN, (falhas == 0) ? 1 : 0, r.ok ? 1 : 0, falhas, r.leitura,
                r.achou ? 1 : 0, t_inicio, r.t_captura, r.t_modelos, r.t_seg, r.t_digitos,
                t_envio, millis(), (unsigned)dorme);
  dormir(dorme);
}

// ----------------------------------------------------------------
// Janela curta apos o despertar para o PC mandar STOP e sair do modo autonomo.
void janelaStop() {
  Serial.printf("[auto] ciclo %u em %lu ms; envie STOP para sair\n",
                (unsigned)(cicloN + 1), JANELA_STOP_MS);
  unsigned long ini = millis();
  while (millis() - ini < JANELA_STOP_MS) {
    if (Serial.available()) {
      String linha = Serial.readStringUntil('\n');
      linha.trim();
      if (linha == "STOP") {
        autoAtivo = false;
        Serial.println("[auto] modo autonomo desligado");
        return;
      }
    }
    delay(10);
  }
}

// ================================================================
void setup() {
  bool acordouDoSleep = (esp_sleep_get_wakeup_cause() == ESP_SLEEP_WAKEUP_TIMER);
  // Os holds do sleep seguram PWDN/flash; precisam sair antes de usar a camera.
  pinoLiberar((gpio_num_t)PWDN_GPIO_NUM);
  pinoLiberar(FLASH_LED_GPIO);

  Serial.begin(115200);
  LoRaSerial.begin(9600, SERIAL_8N1, LORA_RX_PIN, LORA_TX_PIN);
  if (!acordouDoSleep) delay(1000);  // so no power-on: espera o monitor serial abrir

  Serial.println("ESP32-CAM LoRa OCR Sender - TCC");
  Serial.println("Comandos: LER | AUTO[:<s>] | STOP | SLEEP:<s> | AT<cmd>");
  Serial.printf("[boot] causa=%s ciclo=%u auto=%d intervalo=%u s\n",
                acordouDoSleep ? "timer" : "power-on/reset", (unsigned)cicloN,
                autoAtivo ? 1 : 0, (unsigned)autoIntervaloS);

  if (autoAtivo) janelaStop();

  camPronta = initCamera();
  if (camPronta) Serial.println("[camera] pronta.");
  else Serial.println("[camera] falhou - so bridge AT e SLEEP disponiveis.");

  if (autoAtivo) cicloAutonomo();  // nao retorna: termina em deep sleep
}

void loop() {
  // Bridge: repassa respostas do Radioenge pro Serial Monitor
  while (LoRaSerial.available()) Serial.write(LoRaSerial.read());

  if (Serial.available()) {
    String linha = Serial.readStringUntil('\n');
    linha.trim();

    if (linha == "LER") {
      ResultadoOcr r = executarOcr();
      if (r.ok) enviarLeitura((uint16_t)esp_random(), r);
    } else if (linha == "AUTO" || linha.startsWith("AUTO:")) {
      long s = (linha == "AUTO") ? (long)INTERVALO_PADRAO_S : linha.substring(5).toInt();
      autoIntervaloS = (s >= (long)INTERVALO_MIN_S) ? (uint32_t)s : INTERVALO_PADRAO_S;
      autoAtivo = true;
      Serial.printf("[auto] ligado, intervalo %u s\n", (unsigned)autoIntervaloS);
      cicloAutonomo();
    } else if (linha == "STOP") {
      autoAtivo = false;
      Serial.println("[auto] modo autonomo desligado");
    } else if (linha.startsWith("SLEEP:")) {
      long s = linha.substring(6).toInt();
      if (s > 0) dormir((uint32_t)s);
      else Serial.println("[ERRO] use SLEEP:<segundos> com segundos > 0");
    } else {
      LoRaSerial.println(linha);  // passa AT direto ao Radioenge
    }
  }
}
