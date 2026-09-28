#include <stdio.h>
#include <stdlib.h>
#include <string.h>

// TensorFlow C API
#include <tensorflow/c/c_api.h>

// Bibliotecas STB para processamento de imagem
#define STB_IMAGE_IMPLEMENTATION
#include "stb_image.h"

#define STB_IMAGE_RESIZE_IMPLEMENTATION
#include "stb_image_resize2.h"

#define STB_IMAGE_WRITE_IMPLEMENTATION
#include "stb_image_write.h"

#define CHUNK_IMAGE 6
#define IMG_WIDTH 64
#define IMG_HEIGHT 64
#define VOCAB "0123456789"
#define NUM_CLASSES 10

// Função auxiliar para verificar erros na C API
void check_status(TF_Status* status, const char* msg) {
    if (TF_GetCode(status) != TF_OK) {
        fprintf(stderr, "Erro [%s]: %s\n", msg, TF_Message(status));
        exit(1);
    }
}

// Callback para desalocação de memória do Tensor
void tensor_deallocator(void* data, size_t len, void* arg) {
    (void)len;
    (void)arg;
    free(data);
}

int main(int argc, char** argv) {
    const char* model_dir = "modelo_ocr_savedmodel";
    const char* image_path = "sintetico_97202.jpg";

    // 1. Carregar Imagem Original (Escala de Cinza)
    int img_w, img_h, channels;
    unsigned char* raw_img = stbi_load(image_path, &img_w, &img_h, &channels, 1);
    if (!raw_img) {
        fprintf(stderr, "Erro ao carregar a imagem: %s\n", image_path);
        return 1;
    }

    // 2. Carregar Modelo SavedModel via C API (TF 2.21)
    TF_Status* status = TF_NewStatus();
    TF_SessionOptions* opts = TF_NewSessionOptions();
    TF_Buffer* run_opts = NULL;
    
    const char* tags[] = {"serve"};
    TF_Graph* graph = TF_NewGraph();
    
    TF_Session* session = TF_LoadSessionFromSavedModel(
        opts, run_opts, model_dir, tags, 1, graph, NULL, status
    );
    check_status(status, "Carregando SavedModel");

    // Identificar os nós de Entrada e Saída
    TF_Output input_op = {TF_GraphOperationByName(graph, "input_tensor"), 0};
    
    // Mapeamento dinâmico da saída
    TF_Output output_op = {TF_GraphOperationByName(graph, "StatefulPartitionedCall"), 0};
    if (output_op.oper == NULL) {
        output_op.oper = TF_GraphOperationByName(graph, "Identity");
        output_op.index = 0;
    }

    if (input_op.oper == NULL || output_op.oper == NULL) {
        fprintf(stderr, "Erro ao mapear operacoes de entrada/saida no grafico.\n");
        return 1;
    }

    char texto_reconhecido[CHUNK_IMAGE + 1];
    texto_reconhecido[CHUNK_IMAGE] = '\0';

    float step_x = (float)img_w / CHUNK_IMAGE;

    printf("--- Processando 6 Partes (TensorFlow C API 2.21) ---\n");

    for (int i = 0; i < CHUNK_IMAGE; i++) {
        int left = (int)(i * step_x);
        int right = (i == CHUNK_IMAGE - 1) ? img_w : (int)((i + 1) * step_x);
        int crop_w = right - left;
        int crop_h = img_h;

        // Recorte da imagem
        unsigned char* crop_data = (unsigned char*)malloc(crop_w * crop_h);
        for (int y = 0; y < crop_h; y++) {
            memcpy(crop_data + (y * crop_w), raw_img + (y * img_w + left), crop_w);
        }

        // Salva recorte localmente
        char crop_filename[32];
        snprintf(crop_filename, sizeof(crop_filename), "img_%d.jpg", i);
        stbi_write_jpg(crop_filename, crop_w, crop_h, 1, crop_data, 90);

        // Redimensionar para 64x64
        unsigned char* resized_data = (unsigned char*)malloc(IMG_WIDTH * IMG_HEIGHT);
        stbir_resize_uint8_linear(
            crop_data, crop_w, crop_h, 0,
            resized_data, IMG_WIDTH, IMG_HEIGHT, 0,
            STBIR_1CHANNEL
        );

        // Preparar Tensor [1, 64, 64, 1] em float32
        int64_t dims[] = {1, IMG_HEIGHT, IMG_WIDTH, 1};
        size_t tensor_size = 1 * IMG_HEIGHT * IMG_WIDTH * 1 * sizeof(float);
        
        float* input_buffer = (float*)malloc(tensor_size);
        for (int j = 0; j < IMG_HEIGHT * IMG_WIDTH; j++) {
            input_buffer[j] = (float)resized_data[j] / 255.0f;
        }

        TF_Tensor* input_tensor = TF_NewTensor(
            TF_FLOAT, dims, 4, input_buffer, tensor_size,
            tensor_deallocator, NULL
        );

        // Executar a Inferência
        TF_Tensor* output_tensor = NULL;
        TF_SessionRun(
            session, NULL,
            &input_op, &input_tensor, 1,
            &output_op, &output_tensor, 1,
            NULL, 0, NULL, status
        );
        check_status(status, "Execução (SessionRun)");

        // Ler Predições
        float* preds = (float*)TF_TensorData(output_tensor);

        int best_class = 0;
        float max_confidence = preds[0];
        for (int c = 1; c < NUM_CLASSES; c++) {
            if (preds[c] > max_confidence) {
                max_confidence = preds[c];
                best_class = c;
            }
        }

        char caractere = VOCAB[best_class];
        texto_reconhecido[i] = caractere;
        float confianca = max_confidence * 100.0f;

        printf("Parte %d: Caractere '%c' (Confiança: %.1f%%)\n", i + 1, caractere, confianca);

        free(crop_data);
        free(resized_data);
        TF_DeleteTensor(input_tensor);
        TF_DeleteTensor(output_tensor);
    }

    printf("\nResultado final reconstruído: %s\n", texto_reconhecido);

    // Liberar recursos da C API
    stbi_image_free(raw_img);
    TF_CloseSession(session, status);
    TF_DeleteSession(session, status);
    TF_DeleteGraph(graph);
    TF_DeleteSessionOptions(opts);
    TF_DeleteStatus(status);

    return 0;
}