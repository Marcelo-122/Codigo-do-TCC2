#include <stdio.h>
#include "tensorflow/lite/micro/micro_mutable_op_resolver.h"
#include "tensorflow/lite/micro/micro_interpreter.h"
#include "tensorflow/lite/micro/micro_log.h"
#include "tensorflow/lite/schema/schema_generated.h"

#include "modelo_medidor.h"

constexpr int kTensorArenaSize = 25 * 1024 * 1024;
uint8_t tensor_arena[kTensorArenaSize];

int main(int argc, char* argv[]) {
    MicroPrintf("-> Iniciando Teste do Novo Modelo no WSL (Linux Nativo)\n");

    // NOME DA VARIÁVEL ATUALIZADO AQUI:
    const tflite::Model* model = tflite::GetModel(Modelos_modelo_medidor_tflite);

    if (model->version() != TFLITE_SCHEMA_VERSION) {
        MicroPrintf("ERRO: Versao do schema %d nao suportada.", model->version());
        return 1;
    }

    tflite::MicroMutableOpResolver<25> resolver;
    resolver.AddConv2D();
    resolver.AddMaxPool2D();
    resolver.AddReshape();
    resolver.AddFullyConnected();
    resolver.AddSoftmax();
    resolver.AddRelu();
    resolver.AddAdd();
    resolver.AddConcatenation();
    resolver.AddLogistic();
    resolver.AddResizeBilinear();
    resolver.AddResizeNearestNeighbor();
    resolver.AddQuantize();
    resolver.AddDequantize();
    resolver.AddPad();
    resolver.AddTransposeConv();

    resolver.AddMul();
    resolver.AddSub();
    resolver.AddPack();
    resolver.AddUnpack();
    resolver.AddStridedSlice();
    resolver.AddMean();
    resolver.AddShape();

    tflite::MicroInterpreter interpreter(model, resolver, tensor_arena, kTensorArenaSize);

    if (interpreter.AllocateTensors() != kTfLiteOk) {
        MicroPrintf("ERRO FATAL: Falha ao alocar memoria (Arena pequena demais).");
        return 1;
    }

    TfLiteTensor* input = interpreter.input(0);
    TfLiteTensor* output = interpreter.output(0);

    if (input == nullptr || output == nullptr) {
        MicroPrintf("ERRO: Ponteiros de entrada ou saida nulos!");
        return 1;
    }

    MicroPrintf("-> Modelo pronto!");
    MicroPrintf("   - Entrada esperada: %d bytes (Tipo: %d)", (int)input->bytes, (int)input->type);
    MicroPrintf("   - Saida esperada: %d bytes (Tipo: %d)\n", (int)output->bytes, (int)output->type);

    MicroPrintf("-> Executando inferencia com matriz de teste...");
    for (int i = 0; i < input->bytes; i++) {
        input->data.int8[i] = 0;
    }

    if (interpreter.Invoke() != kTfLiteOk) {
        MicroPrintf("ERRO: Falha ao invocar o modelo.");
        return 1;
    }

    MicroPrintf("-> Inferencia concluida com sucesso!");

    if (output->type == kTfLiteInt8) {
        MicroPrintf("-> Amostra Saida (Pixel 0): %d", output->data.int8[0]);
    }
    else {
        MicroPrintf("-> Amostra Saida (Pixel 0): [Lido com sucesso. Tipo original: %d]", (int)output->type);
    }

    return 0;
}