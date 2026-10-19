// ============================================================
// debug_ocr_esp32cam.ino
//
// Ferramenta de DEBUG/CALIBRAÇÃO FÍSICA da câmera: captura uma imagem,
// roda o modelo de SEGMENTAÇÃO (modelo.h, via TFLite Micro) pra achar a
// janela de dígitos, fatia essa janela em N_FATIAS pedaços (ajustado pro
// medidor-alvo desta calibração — ver comentário de N_FATIAS mais abaixo)
// e roda o modelo CLASSIFICADOR DE DÍGITO (modelo_digito.h)
// em cada fatia, montando a leitura completa (ex.: "007704"). Desenha o
// retângulo + linhas-guia sobre a própria imagem e manda tudo (imagem +
// leitura + métricas) pela Serial a cada 5s.
//
// NÃO É O FIRMWARE FINAL DE PRODUÇÃO — é uma ferramenta pra você ajustar a
// posição física da ESP32CAM até a janela real de dígitos do hidrômetro
// cair dentro do retângulo/linhas desenhados.
//
// Arquivo NOVO, não mexe em nenhum .ino já existente no repositório.
//
// ------------------------------------------------------------------
// COMO USAR
// ------------------------------------------------------------------
// 1) Instale a biblioteca TensorFlow Lite Micro para Arduino/ESP32.
//    Existem duas famílias de biblioteca com nomes/headers diferentes:
//      a) "TensorFlowLite_ESP32" (tanakamasayuki) - mais antiga, mais fácil
//         de achar no Library Manager do Arduino IDE.
//      b) "Chirale_TensorFlowLite" ou o port oficial "tflite-micro" da
//         Espressif - mais atual.
//    Os #include abaixo assumem os caminhos de header mais comuns entre
//    essas bibliotecas (tensorflow/lite/micro/...). Se o compilador
//    reclamar de "file not found", é o primeiro lugar pra olhar: pode
//    precisar ajustar os caminhos dos #include conforme a biblioteca que
//    você instalou.
// 2) Board: "AI Thinker ESP32-CAM" no Arduino IDE, com PSRAM habilitada
//    ("PSRAM: Enabled"). Os dois modelos juntos (segmentação ~1,6 MB +
//    classificador de dígito ~110 KB de ativação intermediária, medido em
//    Python) não cabem na RAM interna (~520 KB) - os dois tensor arenas
//    são alocados da PSRAM de propósito (TENSOR_ARENA_SIZE e
//    DIGIT_ARENA_SIZE abaixo).
// 3) Ligue a ESP32CAM na mesma porta serial que você já usa com
//    grab_image.py, mas rode o NOVO script Python
//    (grab_image_debug.py, no mesmo diretório) em vez do grab_image.py
//    original - ele espera tanto a imagem quanto a linha de métricas.
// ------------------------------------------------------------------

#include "esp_camera.h"
#include "img_converters.h"  // fmt2jpg()

#include "modelo.h"         // gerado por gerar_header.py; array modelo_tflite[]
#include "modelo_digito.h"  // idem; array modelo_digito_tflite[]

// ---- TensorFlow Lite Micro ----
#include "tensorflow/lite/micro/micro_interpreter.h"
#include "tensorflow/lite/micro/micro_mutable_op_resolver.h"
#include "tensorflow/lite/micro/micro_log.h"
#include "tensorflow/lite/schema/schema_generated.h"

// ================================================================
// Pinos da câmera (AI-Thinker ESP32-CAM) - iguais aos outros .ino do repo
// ================================================================
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

// ================================================================
// Configuração de captura
// ================================================================
// Captura em QQVGA cinza (160x120) - a PSRAM (4 MB) e apertada dividida
// entre buffer de camera + tensor arena do TFLite + heap do programa; o
// modelo redimensiona pra 192x192 de qualquer forma, entao nao ha ganho
// real em capturar maior. Se sobrar folga de PSRAM (ver metricas na
// Serial), pode subir pra FRAMESIZE_QVGA (320x240) e atualizar aqui.
static const int CAM_W = 160;
static const int CAM_H = 120;

// Entrada do modelo de segmentação (fixa, vem do modelo.h): 192x192x1 int8.
static const int MODEL_W = 192;
static const int MODEL_H = 192;

// Entrada do modelo classificador de dígito (fixa, vem do modelo_digito.h):
// 28x28x1 int8, saida 10 classes (softmax quantizado).
static const int DIGIT_W = 28;
static const int DIGIT_H = 28;

// Numero de rodinhas de digito do medidor ALVO desta calibracao. O
// pipeline de treino (preparar_dataset_digitos.py) usa a hipotese generica
// "5 inteiros + 3 fracionarios = 8" pro dataset Kaggle, mas isso e so o
// dataset de treino do CLASSIFICADOR - o classificador em si so le um
// digito por vez (28x28 -> 0-9), entao esse numero e puramente sobre como
// FATIAMOS a caixa detectada, nao precisa bater com o que foi usado no
// treino. O medidor fotografado nos testes (marca Tianjin, "046663") tem
// 6 rodinhas pretas e nenhuma vermelha de fracao - ajustado pra 6. Se
// trocar de medidor-alvo, e so contar as rodinhas na imagem de debug e
// atualizar este numero (sem precisar retreinar nada).
static const int N_FATIAS = 6;

static const unsigned long INTERVALO_MS = 5000;  // pedido: a cada 5s

// ================================================================
// TensorFlow Lite Micro - globais
// ================================================================
// Tensor arena: a estimativa inicial de 1 MB (so olhando o maior tensor
// intermediario, ~288 KB) ficou pequena na pratica -- o log real de
// AllocateTensors() (via "Failed to resize buffer") mostrou que o
// interpretador precisa de ~1.622.016 bytes (~1,55 MB), provavelmente
// porque o TFLite Micro reserva espaco extra pra manter varios tensores
// intermediarios vivos ao mesmo tempo (arquitetura tipo U-Net, com uma
// "skip connection" implicita entre as camadas conv e as transpose-conv).
// 2 MB da folga confortavel sobre esse valor medido, dentro dos 4 MB de
// PSRAM disponiveis (camera QQVGA consome só ~19 KB, ver log de
// "psram livre apos esp_camera_init").
// ISSO NÃO CABE NA RAM INTERNA (~520 KB, boa parte já em uso pelo WiFi/
// stack) - por isso alocamos explicitamente da PSRAM abaixo.
static const int TENSOR_ARENA_SIZE = 2 * 1024 * 1024;  // 2 MB
static uint8_t *tensor_arena = nullptr;

// Tensor arena do classificador de digito: maior tensor intermediario
// medido em Python = 112.896 elementos (bytes, int8) = ~110 KB. Usando a
// mesma margem de seguranca que descobrimos na pratica pro modelo de
// segmentacao (~5,5x o maior tensor), 768 KB da folga confortavel. Ainda
// NAO TESTADO em hardware real -- se "AllocateTensors falhou" aparecer pro
// classificador, e so aumentar esta constante (o log avisa qual dos dois
// modelos falhou).
static const int DIGIT_ARENA_SIZE = 768 * 1024;  // 768 KB
static uint8_t *digit_arena = nullptr;

namespace {
const tflite::Model *modelo = nullptr;
tflite::MicroInterpreter *interpreter = nullptr;
TfLiteTensor *input = nullptr;
TfLiteTensor *output = nullptr;

const tflite::Model *modeloDigito = nullptr;
tflite::MicroInterpreter *interpreterDigito = nullptr;
TfLiteTensor *inputDigito = nullptr;
TfLiteTensor *outputDigito = nullptr;
}  // namespace

bool iniciarModelo() {
  modelo = tflite::GetModel(modelo_tflite);
  if (modelo->version() != TFLITE_SCHEMA_VERSION) {
    Serial.printf("[tflite] versao do schema incompativel: modelo=%d lib=%d\n",
                  modelo->version(), TFLITE_SCHEMA_VERSION);
    return false;
  }

  // Aloca o tensor arena na PSRAM (precisa de "PSRAM: Enabled" na board).
  tensor_arena = (uint8_t *)heap_caps_malloc(TENSOR_ARENA_SIZE, MALLOC_CAP_SPIRAM);
  if (!tensor_arena) {
    Serial.println("[tflite] falha ao alocar tensor_arena na PSRAM");
    return false;
  }

  // Operadores usados pelo modelo de segmentacao (conferido em
  // modelo_esp32.tflite via introspeccao do flatbuffer): CONV_2D,
  // MAX_POOL_2D, TRANSPOSE_CONV, LOGISTIC. Se adicionar/trocar o modelo,
  // reconfira essa lista (script rapido em Python, ver ModeloEDataset).
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

  Serial.printf("[tflite] segmentacao pronta. input=[%d,%d,%d,%d] output=[%d,%d,%d,%d] "
                "arena_usado=%u bytes\n",
                input->dims->data[0], input->dims->data[1], input->dims->data[2], input->dims->data[3],
                output->dims->data[0], output->dims->data[1], output->dims->data[2], output->dims->data[3],
                (unsigned)interpreter->arena_used_bytes());
  return true;
}

bool iniciarModeloDigito() {
  modeloDigito = tflite::GetModel(modelo_digito_tflite);
  if (modeloDigito->version() != TFLITE_SCHEMA_VERSION) {
    Serial.printf("[tflite] digito: versao do schema incompativel: modelo=%d lib=%d\n",
                  modeloDigito->version(), TFLITE_SCHEMA_VERSION);
    return false;
  }

  digit_arena = (uint8_t *)heap_caps_malloc(DIGIT_ARENA_SIZE, MALLOC_CAP_SPIRAM);
  if (!digit_arena) {
    Serial.println("[tflite] digito: falha ao alocar digit_arena na PSRAM");
    return false;
  }

  // Operadores usados pelo classificador de digito (conferido em
  // modelo_digito.tflite via introspeccao do flatbuffer): CONV_2D,
  // MAX_POOL_2D, SHAPE, STRIDED_SLICE, PACK, RESHAPE, FULLY_CONNECTED,
  // SOFTMAX. Se re-treinar o modelo com outra arquitetura, reconfira essa
  // lista (mesmo script Python usado pro modelo de segmentacao).
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

  Serial.printf("[tflite] digito pronto. input=[%d,%d,%d,%d] output=[%d,%d] "
                "arena_usado=%u bytes\n",
                inputDigito->dims->data[0], inputDigito->dims->data[1],
                inputDigito->dims->data[2], inputDigito->dims->data[3],
                outputDigito->dims->data[0], outputDigito->dims->data[1],
                (unsigned)interpreterDigito->arena_used_bytes());
  return true;
}

// ================================================================
// Câmera
// ================================================================
bool iniciarCamera() {
  // Zerado explicitamente: campos nao setados abaixo (fb_location,
  // grab_mode, jpeg_quality etc) ficariam com lixo da pilha se so
  // declarassemos "camera_config_t config;" sem inicializar, o que pode
  // fazer o driver se comportar de forma imprevisivel (foi um dos
  // suspeitos do erro "Failed to resize buffer" na primeira tentativa).
  uint32_t psram_livre_antes = ESP.getFreePsram();

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

  // Cinza direto da câmera (sem precisar decodificar JPEG depois pra rodar
  // o modelo) - ela ja gera 1 byte/pixel nesse formato.
  config.pixel_format = PIXFORMAT_GRAYSCALE;
  // QQVGA (160x120) em vez de QVGA: a PSRAM e apertada (4 MB) dividida
  // entre buffer de camera + tensor arena (~700 KB-1 MB) + heap do
  // programa. O modelo redimensiona pra 192x192 de qualquer forma, entao
  // a resolucao de captura nao precisa ser grande - so o suficiente pra
  // enxergar o mostrador inteiro. Se sobrar memoria de sobra depois de
  // testar (ver as metricas de psram_free na saida Serial), pode tentar
  // subir pra FRAMESIZE_QVGA de novo.
  config.frame_size   = FRAMESIZE_QQVGA;  // 160x120
  config.fb_count     = 1;
  config.fb_location  = CAMERA_FB_IN_PSRAM;
  config.grab_mode    = CAMERA_GRAB_WHEN_EMPTY;

  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
    Serial.printf("[camera] erro: 0x%x\n", err);
    return false;
  }
  Serial.printf("[psram] livre apos esp_camera_init: %u (era %u antes - camera consumiu %d)\n",
                (unsigned)ESP.getFreePsram(), (unsigned)psram_livre_antes,
                (int)psram_livre_antes - (int)ESP.getFreePsram());

  // NAO chamamos sensor->set_framesize() de novo aqui: config.frame_size ja
  // foi passado pro esp_camera_init acima, e foi exatamente essa chamada
  // redundante de resize (copiada de outro .ino do projeto que faz JPEG,
  // onde ela e necessaria por outro motivo) que causou o "Failed to
  // resize buffer" na primeira tentativa - forcar um resize logo apos o
  // init faz o driver tentar manter o buffer antigo alocado enquanto tenta
  // alocar o novo, e a PSRAM (4 MB) nao tem folga pros dois ao mesmo tempo.
  delay(300);
  return true;
}

// ================================================================
// Redimensiona (nearest-neighbor, simples e rapido) de CAM_W x CAM_H pra
// MODEL_W x MODEL_H, e já escreve direto no tensor de entrada do modelo
// (convertendo pixel 0-255 -> int8 com zero_point=-128, que é a mesma
// convencao usada no treino: img/255.0 antes de quantizar).
// ================================================================
void prepararEntradaModelo(const uint8_t *frame) {
  for (int y = 0; y < MODEL_H; y++) {
    int ySrc = (y * CAM_H) / MODEL_H;
    for (int x = 0; x < MODEL_W; x++) {
      int xSrc = (x * CAM_W) / MODEL_W;
      uint8_t pixel = frame[ySrc * CAM_W + xSrc];
      input->data.int8[y * MODEL_W + x] = (int8_t)((int)pixel - 128);
    }
  }
}

// ================================================================
// Le a mascara de saida (int8, threshold em 0 == probabilidade 0.5,
// ver conta no comentario da funcao) e acha o bounding box (retangulo
// alinhado aos eixos - sem rotacao, diferente do pipeline em Python que
// usa minAreaRect; suficiente pra debug visual) em coordenadas do
// modelo (192x192), depois escala pra coordenadas da imagem capturada
// (CAM_W x CAM_H).
//
// output int8 -> probabilidade = (val + 128) / 256 (ver quantizacao do
// tensor de saida). threshold 0.5 --> val > 0.
// ================================================================
bool acharCaixaDigitos(int *bx0, int *by0, int *bx1, int *by1) {
  int minX = MODEL_W, minY = MODEL_H, maxX = -1, maxY = -1;
  int8_t *saida = output->data.int8;

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

  if (maxX < 0) return false;  // mascara vazia - nao achou nada

  *bx0 = (minX * CAM_W) / MODEL_W;
  *bx1 = (maxX * CAM_W) / MODEL_W;
  *by0 = (minY * CAM_H) / MODEL_H;
  *by1 = (maxY * CAM_H) / MODEL_H;
  return true;
}

// ================================================================
// Classifica UMA fatia (regiao sx0..sx1, sy0..sy1 do frame CAM_W x CAM_H)
// como um digito 0-9: redimensiona (nearest-neighbor) pra 28x28, converte
// pixel -> int8 (mesma convencao pixel-128 do modelo de segmentacao) e
// roda o classificador. Retorna 0-9, ou -1 se o Invoke() falhar.
// ================================================================
int classificarFatia(const uint8_t *frame, int sx0, int sy0, int sx1, int sy1) {
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

  int8_t *saida = outputDigito->data.int8;
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

// Fatia a caixa detectada em N_FATIAS pedacos de largura igual (mesma
// convencao do pipeline em Python - ver segment_cells_iguais em
// digitos_comum.py) e classifica cada um, montando a leitura completa
// (ex.: "007704"). "saida" precisa ter espaco pra N_FATIAS+1 chars (inclui
// o terminador nulo).
void lerDigitos(const uint8_t *frame, int x0, int y0, int x1, int y1, char *saida) {
  int largura = x1 - x0;
  for (int i = 0; i < N_FATIAS; i++) {
    int sx0 = x0 + (largura * i) / N_FATIAS;
    int sx1 = x0 + (largura * (i + 1)) / N_FATIAS;
    int digito = classificarFatia(frame, sx0, y0, sx1, y1);
    saida[i] = (digito >= 0 && digito <= 9) ? ('0' + digito) : '?';
  }
  saida[N_FATIAS] = '\0';
}

// ================================================================
// Desenha um pixel branco (255) na imagem em tons de cinza, com limites.
// ================================================================
inline void setPixel(uint8_t *frame, int x, int y, uint8_t valor) {
  if (x < 0 || x >= CAM_W || y < 0 || y >= CAM_H) return;
  frame[y * CAM_W + x] = valor;
}

void desenharLinhaH(uint8_t *frame, int x0, int x1, int y, uint8_t valor) {
  for (int x = x0; x <= x1; x++) setPixel(frame, x, y, valor);
}
void desenharLinhaV(uint8_t *frame, int y0, int y1, int x, uint8_t valor) {
  for (int y = y0; y <= y1; y++) setPixel(frame, x, y, valor);
}

// Desenha o retangulo detectado (borda dupla pra ficar visivel mesmo sobre
// fundo claro) + N_FATIAS-1 linhas verticais internas marcando onde cada
// digito deveria cair.
void desenharCaixaEFatias(uint8_t *frame, int x0, int y0, int x1, int y1) {
  for (int esp = 0; esp < 2; esp++) {
    desenharLinhaH(frame, x0 - esp, x1 + esp, y0 - esp, 255);
    desenharLinhaH(frame, x0 - esp, x1 + esp, y1 + esp, 255);
    desenharLinhaV(frame, y0 - esp, y1 + esp, x0 - esp, 255);
    desenharLinhaV(frame, y0 - esp, y1 + esp, x1 + esp, 255);
  }
  int largura = x1 - x0;
  for (int i = 1; i < N_FATIAS; i++) {
    int x = x0 + (largura * i) / N_FATIAS;
    desenharLinhaV(frame, y0, y1, x, 200);  // um pouco mais escura que a borda
  }
}

// ================================================================
// setup / loop
// ================================================================
void setup() {
  Serial.begin(115200);
  delay(1000);

  Serial.println("=== debug_ocr_esp32cam ===");
  Serial.printf("[psram] tamanho=%u livre=%u\n",
                (unsigned)ESP.getPsramSize(), (unsigned)ESP.getFreePsram());

  if (!iniciarCamera()) {
    Serial.println("Falha na camera. Parando.");
    while (true) delay(1000);
  }
  Serial.println("[camera] pronta.");

  if (!iniciarModelo()) {
    Serial.println("Falha ao iniciar o modelo de segmentacao. Parando.");
    while (true) delay(1000);
  }

  if (!iniciarModeloDigito()) {
    Serial.println("Falha ao iniciar o modelo classificador de digito. Parando.");
    while (true) delay(1000);
  }
}

void loop() {
  unsigned long t_inicio = millis();

  camera_fb_t *fb = esp_camera_fb_get();
  if (!fb) {
    Serial.println("[camera] falha ao capturar frame");
    delay(1000);
    return;
  }
  unsigned long t_captura = millis();

  // fb->buf e um buffer CAM_W*CAM_H bytes (grayscale). Copiamos pra um
  // buffer proprio porque vamos DESENHAR em cima (o buffer da camera e
  // reciclado ao devolver com esp_camera_fb_return).
  uint8_t *frame = (uint8_t *)malloc(CAM_W * CAM_H);
  bool memOk = (frame != nullptr);
  if (memOk) memcpy(frame, fb->buf, CAM_W * CAM_H);
  esp_camera_fb_return(fb);

  if (!memOk) {
    Serial.println("[erro] sem memoria pro frame");
    delay(1000);
    return;
  }

  prepararEntradaModelo(frame);
  unsigned long t_prep = millis();

  TfLiteStatus status = interpreter->Invoke();
  unsigned long t_inferencia = millis();

  int bx0 = 0, by0 = 0, bx1 = 0, by1 = 0;
  bool achou = false;
  if (status == kTfLiteOk) {
    achou = acharCaixaDigitos(&bx0, &by0, &bx1, &by1);
    if (achou) desenharCaixaEFatias(frame, bx0, by0, bx1, by1);
  } else {
    Serial.println("[tflite] Invoke() (segmentacao) falhou");
  }
  unsigned long t_segmentacao = millis();

  // Segundo estagio: classifica cada uma das N_FATIAS dentro da caixa
  // encontrada. So roda se a segmentacao achou alguma coisa - sem caixa,
  // nao ha o que fatiar.
  char leitura[N_FATIAS + 1];
  if (achou) {
    lerDigitos(frame, bx0, by0, bx1, by1, leitura);
  } else {
    for (int i = 0; i < N_FATIAS; i++) leitura[i] = '-';
    leitura[N_FATIAS] = '\0';
  }
  unsigned long t_digitos = millis();

  Serial.printf("Leitura: %s\n", leitura);

  // Converte o frame (ja anotado) pra JPEG pra mandar por Serial.
  uint8_t *jpegBuf = nullptr;
  size_t jpegLen = 0;
  bool jpegOk = fmt2jpg(frame, CAM_W * CAM_H, CAM_W, CAM_H, PIXFORMAT_GRAYSCALE,
                        80, &jpegBuf, &jpegLen);
  unsigned long t_encode = millis();

  free(frame);

  if (jpegOk) {
    // Mesmo protocolo simples que o grab_image.py ja sabe ler.
    Serial.print("<IMG_START>");
    Serial.write(jpegBuf, jpegLen);
    Serial.print("<IMG_END>");
    free(jpegBuf);
  } else {
    Serial.println("[erro] fmt2jpg falhou");
  }

  unsigned long t_fim = millis();

  // Linha de metricas - formato "chave=valor" separado por espaco, facil
  // de parsear no lado Python sem precisar de biblioteca de JSON.
  Serial.print("<METRICS_START>");
  Serial.printf(
      "uptime_ms=%lu heap_free=%u heap_min_free=%u heap_size=%u "
      "psram_free=%u psram_size=%u cpu_mhz=%u temp_c=%.1f "
      "achou_caixa=%d bx0=%d by0=%d bx1=%d by1=%d leitura=%s "
      "t_captura_ms=%lu t_prep_ms=%lu t_inferencia_seg_ms=%lu t_pos_seg_ms=%lu "
      "t_digitos_ms=%lu t_encode_ms=%lu t_total_ms=%lu "
      "jpeg_bytes=%u arena_seg_bytes=%u arena_digito_bytes=%u",
      millis(),
      (unsigned)ESP.getFreeHeap(), (unsigned)ESP.getMinFreeHeap(), (unsigned)ESP.getHeapSize(),
      (unsigned)ESP.getFreePsram(), (unsigned)ESP.getPsramSize(),
      (unsigned)ESP.getCpuFreqMHz(), temperatureRead(),
      achou ? 1 : 0, bx0, by0, bx1, by1, leitura,
      (t_captura - t_inicio), (t_prep - t_captura), (t_inferencia - t_prep),
      (t_segmentacao - t_inferencia), (t_digitos - t_segmentacao), (t_encode - t_digitos),
      (t_fim - t_inicio),
      (unsigned)jpegLen, (unsigned)interpreter->arena_used_bytes(),
      (unsigned)interpreterDigito->arena_used_bytes());
  Serial.print("<METRICS_END>");
  Serial.println();

  delay(INTERVALO_MS);
}
