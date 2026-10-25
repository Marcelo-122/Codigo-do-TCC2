// ============================================================
// teste_esp32cam_pipeline_a.ino
//
// Testa, numa ESP32-CAM real, se os modelos do Pipeline A (TreinoEModelosOCRNaBorda/)
// rodam no TFLite Micro: o detector (U-Net 384x384) e os dois leitores CRNN+CTC (48x224).
// Não usa a câmera: o objetivo é só responder
//   1) cabe na PSRAM?             (AllocateTensors passa? quantos bytes a arena usa?)
//   2) os operadores existem?     (a biblioteca TFLM registra todos os ops do modelo?)
//   3) quanto tempo leva?         (Invoke com entrada sintética, só se a alocação passar)
//
// A entrada é sintética, então a LEITURA impressa não tem significado: o que vale é
// o status, os bytes de arena e o tempo.
//
// ------------------------------------------------------------------
// COMO USAR
// ------------------------------------------------------------------
// 1) Nesta pasta:  python gerar_headers.py   (cria a_detector.h, a_ctc.h, a_ctc_sint.h;
//    eles não ficam no Git)
// 2) Arduino IDE, board "AI Thinker ESP32-CAM", com
//      PSRAM: Enabled
//      Partition Scheme: Huge APP (3MB No OTA/1MB SPIFFS)   <-- obrigatório: os modelos
//                                                               + a TFLM passam do 1,2 MB padrão
//    A TFLM usada é a que vem junto do core ESP32 (esp-tflite-micro, com ESP-NN), a mesma
//    do firmware debug_ocr_esp32cam.
// 3) Serial Monitor a 115200. Aperte RESET depois de abrir o monitor. Copie TUDO que
//    aparecer, do banner até a linha "FIM".
//
// Logs de erro do próprio TFLM (ex.: "Failed to resize buffer. Requested: ...",
// "Failed to get registration from op code ...") saem na mesma Serial, antes da linha
// [RESULTADO] do modelo correspondente. Eles são a parte mais importante: não os apague.
//
// O detector pode levar vários minutos no Invoke se a alocação passar. Não é travamento.
// ============================================================

#include "esp_heap_caps.h"

#include "a_detector.h"  // a_detector_tflite[]
#include "a_ctc.h"       // a_ctc_tflite[]
#include "a_ctc_sint.h"  // a_ctc_sint_tflite[]

#include "tensorflow/lite/micro/micro_interpreter.h"
#include "tensorflow/lite/micro/micro_mutable_op_resolver.h"
#include "tensorflow/lite/micro/micro_log.h"
#include "tensorflow/lite/schema/schema_generated.h"

// Folga deixada fora da arena para o resto do programa (pilha das tarefas, buffers do driver).
static const size_t MARGEM_PSRAM = 64 * 1024;

struct Resultado {
  const char *nome;
  bool alocou;
  bool invocou;
  unsigned arena_oferecida;
  unsigned arena_usada;
  unsigned long invoke_ms;
  char leitura[64];
};
static Resultado resultados[3];
static int n_resultados = 0;

static void memoria(const char *tag) {
  Serial.printf("[mem] %s: heap_livre=%u psram_livre=%u maior_bloco_psram=%u psram_total=%u\n", tag,
                (unsigned)ESP.getFreeHeap(), (unsigned)ESP.getFreePsram(),
                (unsigned)heap_caps_get_largest_free_block(MALLOC_CAP_SPIRAM),
                (unsigned)ESP.getPsramSize());
}

static void imprimirForma(const char *rotulo, TfLiteTensor *t) {
  Serial.printf("[tflite] %s: tipo=%d dims=[", rotulo, (int)t->type);
  for (int i = 0; i < t->dims->size; i++) {
    Serial.printf(i ? ",%d" : "%d", t->dims->data[i]);
  }
  Serial.printf("] escala=%g zero_point=%d\n", t->params.scale, (int)t->params.zero_point);
}

// Decodificação CTC gulosa sobre a saída [1, T, C] (último símbolo = blank).
static void decodificarCtc(TfLiteTensor *saida, char *dest, size_t n) {
  dest[0] = 0;
  if (saida->type != kTfLiteInt8 || saida->dims->size != 3) return;
  const int T = saida->dims->data[1];
  const int C = saida->dims->data[2];
  const int8_t *d = saida->data.int8;
  size_t k = 0;
  int anterior = -1;
  for (int t = 0; t < T && k + 1 < n; t++) {
    int melhor = 0;
    for (int c = 1; c < C; c++) {
      if (d[t * C + c] > d[t * C + melhor]) melhor = c;
    }
    if (melhor != anterior && melhor != C - 1) dest[k++] = (char)('0' + melhor);
    anterior = melhor;
  }
  dest[k] = 0;
}

static void testarModelo(const char *nome, const unsigned char *dados, unsigned tamanho_arquivo,
                         const tflite::MicroOpResolver &resolver, bool detector) {
  Resultado &r = resultados[n_resultados++];
  r = {nome, false, false, 0, 0, 0, {0}};

  Serial.printf("\n==== %s (%u bytes no arquivo) ====\n", nome, tamanho_arquivo);
  memoria("antes");

  const tflite::Model *modelo = tflite::GetModel(dados);
  if (modelo->version() != TFLITE_SCHEMA_VERSION) {
    Serial.printf("[tflite] versao do schema incompativel: modelo=%d lib=%d\n", modelo->version(),
                  TFLITE_SCHEMA_VERSION);
    return;
  }

  size_t maior = heap_caps_get_largest_free_block(MALLOC_CAP_SPIRAM);
  size_t arena_bytes = maior > MARGEM_PSRAM ? maior - MARGEM_PSRAM : 0;
  uint8_t *arena = arena_bytes ? (uint8_t *)heap_caps_malloc(arena_bytes, MALLOC_CAP_SPIRAM) : nullptr;
  if (!arena) {
    Serial.println("[tflite] nao foi possivel reservar arena na PSRAM");
    return;
  }
  r.arena_oferecida = (unsigned)arena_bytes;
  Serial.printf("[tflite] arena oferecida: %u bytes (todo o maior bloco livre da PSRAM menos %u)\n",
                (unsigned)arena_bytes, (unsigned)MARGEM_PSRAM);

  tflite::MicroInterpreter *interp = new tflite::MicroInterpreter(modelo, resolver, arena, arena_bytes);
  TfLiteStatus st = interp->AllocateTensors();
  r.arena_usada = (unsigned)interp->arena_used_bytes();
  r.alocou = (st == kTfLiteOk);
  Serial.printf("[tflite] AllocateTensors: %s | arena_used_bytes=%u\n", r.alocou ? "OK" : "FALHOU",
                r.arena_usada);

  if (r.alocou) {
    TfLiteTensor *in = interp->input(0);
    TfLiteTensor *out = interp->output(0);
    imprimirForma("entrada", in);
    imprimirForma("saida", out);

    if (in->type == kTfLiteInt8) {
      const int zp = in->params.zero_point;
      for (size_t i = 0; i < in->bytes; i++) {
        int v = zp + (int)((i * 7) % 64) - 32;  // padrão sintético determinístico
        in->data.int8[i] = (int8_t)(v < -128 ? -128 : (v > 127 ? 127 : v));
      }
    }
    memoria("apos alocar");
    Serial.println("[tflite] rodando Invoke...");
    unsigned long t0 = millis();
    TfLiteStatus si = interp->Invoke();
    r.invoke_ms = millis() - t0;
    r.invocou = (si == kTfLiteOk);
    Serial.printf("[tflite] Invoke: %s em %lu ms\n", r.invocou ? "OK" : "FALHOU", r.invoke_ms);

    if (r.invocou) {
      if (detector && out->type == kTfLiteInt8) {
        size_t acima = 0, total = out->bytes;
        for (size_t i = 0; i < total; i++) {
          float p = (out->data.int8[i] - out->params.zero_point) * out->params.scale;
          if (p > 0.5f) acima++;
        }
        snprintf(r.leitura, sizeof(r.leitura), "pixels>0.5: %u de %u", (unsigned)acima, (unsigned)total);
      } else if (!detector) {
        decodificarCtc(out, r.leitura, sizeof(r.leitura));
      }
      Serial.printf("[saida sintetica, sem significado] %s\n", r.leitura);
    }
  }

  Serial.printf("[RESULTADO] modelo=%s alocou=%s invocou=%s arena_oferecida=%u arena_usada=%u invoke_ms=%lu\n",
                nome, r.alocou ? "sim" : "nao", r.invocou ? "sim" : "nao", r.arena_oferecida,
                r.arena_usada, r.invoke_ms);

  // O interpretador NÃO é destruído de propósito: chamar o destrutor depois de um
  // AllocateTensors() que falhou derruba o ESP32 (LoadProhibited), o que impedia testar os
  // modelos seguintes. Vaza-se só o objeto (poucas centenas de bytes no heap interno);
  // a arena da PSRAM é devolvida para o próximo modelo e o interpretador nunca mais é usado.
  (void)interp;
  heap_caps_free(arena);
}

void setup() {
  Serial.begin(115200);
  delay(3000);
  Serial.println("\n\n########## TESTE PIPELINE A NA ESP32-CAM ##########");
  Serial.printf("cpu_mhz=%u psram_total=%u flash_chip=%u\n", (unsigned)ESP.getCpuFreqMHz(),
                (unsigned)ESP.getPsramSize(), (unsigned)ESP.getFlashChipSize());
  memoria("inicio");
  if (ESP.getPsramSize() == 0) {
    Serial.println("PSRAM nao encontrada: habilite 'PSRAM: Enabled' na board e grave de novo.");
    return;
  }

  // ---- Leitores CTC (48x224 -> [1,56,11]) ----
  // Ops conferidos no flatbuffer: CONV_2D, MAX_POOL_2D, SHAPE, STRIDED_SLICE, PACK, RESHAPE,
  // GATHER, REDUCE_PROD, CONCATENATION, FULLY_CONNECTED, ADD.
  static tflite::MicroMutableOpResolver<16> resolverCtc;
  resolverCtc.AddConv2D();
  resolverCtc.AddMaxPool2D();
  resolverCtc.AddShape();
  resolverCtc.AddStridedSlice();
  resolverCtc.AddPack();
  resolverCtc.AddReshape();
  resolverCtc.AddGather();
  resolverCtc.AddConcatenation();
  resolverCtc.AddFullyConnected();
  resolverCtc.AddAdd();
  // REDUCE_PROD não é registrado: o resolver da TFLM que vem com o core ESP32 3.0.7 não tem
  // AddReduceProd(). A alocação dos leitores CTC deve falhar com
  // "Failed to get registration from op code REDUCE_PROD". Se a sua TFLM tiver
  // AddReduceProd(), acrescente a chamada aqui.
  Serial.println("[ops] REDUCE_PROD NAO registrado (AddReduceProd inexistente nesta TFLM)");

  testarModelo("ctc_original", a_ctc_tflite, a_ctc_tflite_len, resolverCtc, false);
  testarModelo("ctc_sintetico_qat", a_ctc_sint_tflite, a_ctc_sint_tflite_len, resolverCtc, false);

  // ---- Detector U-Net 384x384 ----
  // Ops conferidos no flatbuffer: CONV_2D, MAX_POOL_2D, TRANSPOSE_CONV, CONCATENATION,
  // LOGISTIC, QUANTIZE.
  static tflite::MicroMutableOpResolver<8> resolverDet;
  resolverDet.AddConv2D();
  resolverDet.AddMaxPool2D();
  resolverDet.AddTransposeConv();
  resolverDet.AddConcatenation();
  resolverDet.AddLogistic();
  resolverDet.AddQuantize();

  testarModelo("detector_unet_384", a_detector_tflite, a_detector_tflite_len, resolverDet, true);

  Serial.println("\n---------- RESUMO ----------");
  for (int i = 0; i < n_resultados; i++) {
    Serial.printf("%s | alocou=%s | invocou=%s | arena_usada=%u | invoke_ms=%lu\n", resultados[i].nome,
                  resultados[i].alocou ? "sim" : "nao", resultados[i].invocou ? "sim" : "nao",
                  resultados[i].arena_usada, resultados[i].invoke_ms);
  }
  Serial.println("FIM");
}

void loop() { delay(10000); }
