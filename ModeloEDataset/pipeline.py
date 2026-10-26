import argparse
import csv
import json
import os
import time
import numpy as np
import tensorflow as tf
from tensorflow.keras import layers, models
from tensorflow.keras.utils import load_img, img_to_array

# ==========================================
# 1. CONFIGURAÇÕES
# ==========================================
DIRETORIO_ATUAL = os.path.dirname(os.path.abspath(__file__))

ap = argparse.ArgumentParser(description="Treina o modelo de segmentação da janela de dígitos (Kaggle, 1244 fotos).")
ap.add_argument("--dados", default=os.path.join(DIRETORIO_ATUAL, "dataset"), help="pasta com images/ e masks/")
ap.add_argument("--epocas", type=int, default=10000)
ap.add_argument("--saida", default=DIRETORIO_ATUAL, help="pasta onde ficam modelos/ e relatorios/")
args = ap.parse_args()

DIR_IMG = os.path.join(args.dados, "images")
DIR_MASK = os.path.join(args.dados, "masks")
DIR_MODELOS = os.path.join(args.saida, "modelos")
DIR_RELATORIOS = os.path.join(args.saida, "relatorios")
IMG_SIZE = (192, 192)

SEED = 42
FRACAO_VALIDACAO = 0.15
FRACAO_TESTE = 0.15  # separada antes de qualquer treino; só entra na avaliação final

tf.keras.utils.set_random_seed(SEED)

# ==========================================
# 2. CARREGAMENTO DOS DADOS
# ==========================================
print("-> Carregando imagens e máscaras...")
arquivos = sorted(os.listdir(DIR_IMG))
X, Y, nomes = [], [], []

for arquivo in arquivos:
    if not arquivo.endswith(('.png', '.jpg', '.jpeg')): continue

    # Carrega Imagem e Máscara
    caminho_img = os.path.join(DIR_IMG, arquivo)
    caminho_mask = os.path.join(DIR_MASK, arquivo)

    img_array = img_to_array(load_img(caminho_img, color_mode="grayscale", target_size=IMG_SIZE)) / 255.0
    mask_array = img_to_array(load_img(caminho_mask, color_mode="grayscale", target_size=IMG_SIZE)) / 255.0

    # Binariza a máscara
    mask_array = np.where(mask_array > 0.5, 1.0, 0.0)

    X.append(img_array)
    Y.append(mask_array)
    nomes.append(arquivo)

X = np.array(X)
Y = np.array(Y)
print(f"Dataset carregado! Total: {len(X)} amostras.")

# Divisão fixa treino/validação/teste (embaralhada com seed), gravada em relatorios/ para ser auditável.
# Antes, a validação era o fim da lista ordenada por nome (validation_split do Keras) e não havia teste.
ordem = np.random.default_rng(SEED).permutation(len(X))
n_teste = int(len(X) * FRACAO_TESTE)
n_val = int(len(X) * FRACAO_VALIDACAO)
idx_teste, idx_val, idx_treino = ordem[:n_teste], ordem[n_teste:n_teste + n_val], ordem[n_teste + n_val:]
X_train, Y_train = X[idx_treino], Y[idx_treino]
X_val, Y_val = X[idx_val], Y[idx_val]
X_test, Y_test = X[idx_teste], Y[idx_teste]
print(f"Treino: {len(X_train)} | validação: {len(X_val)} | teste: {len(X_test)}")

os.makedirs(DIR_RELATORIOS, exist_ok=True)
with open(os.path.join(DIR_RELATORIOS, "split_segmentacao.csv"), "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["arquivo", "particao"])
    for particao, idx in (("treino", idx_treino), ("validacao", idx_val), ("teste", idx_teste)):
        w.writerows((nomes[i], particao) for i in sorted(idx))

# ==========================================
# 3. ARQUITETURA DO MODELO
# ==========================================
print("\n-> Criando modelo")


def dice(y_true, y_pred):
    """Dice por imagem (o batch é 1) com a saída binarizada em 0,5. O fundo domina a imagem, então
    a acurácia por pixel não diz se a janela foi achada; Dice e IoU olham só a região da janela."""
    p = tf.cast(y_pred > 0.5, tf.float32)
    inter = tf.reduce_sum(y_true * p)
    soma = tf.reduce_sum(y_true) + tf.reduce_sum(p)
    return tf.math.divide_no_nan(2.0 * inter, soma)


def iou(y_true, y_pred):
    p = tf.cast(y_pred > 0.5, tf.float32)
    inter = tf.reduce_sum(y_true * p)
    uniao = tf.reduce_sum(y_true) + tf.reduce_sum(p) - inter
    return tf.math.divide_no_nan(inter, uniao)


# batch_shape garante tamanho estático na memória do ESP32 (por isso o batch_size do treino é 1)
inputs = layers.Input(batch_shape=(1, IMG_SIZE[0], IMG_SIZE[1], 1))

c1 = layers.Conv2D(8, (3, 3), activation='relu', padding='same')(inputs)
p1 = layers.MaxPooling2D((2, 2))(c1)

c2 = layers.Conv2D(16, (3, 3), activation='relu', padding='same')(p1)
p2 = layers.MaxPooling2D((2, 2))(c2)

u1 = layers.Conv2DTranspose(16, (3, 3), strides=(2, 2), padding='same', activation='relu')(p2)
u2 = layers.Conv2DTranspose(8, (3, 3), strides=(2, 2), padding='same', activation='relu')(u1)

outputs = layers.Conv2D(1, (1, 1), activation='sigmoid', padding='same')(u2)

model = models.Model(inputs=[inputs], outputs=[outputs])
model.compile(optimizer='adam', loss='binary_crossentropy', metrics=['accuracy', dice, iou])

# Callback para estimativa de tempo restante
class TempoEstimadoCallback(tf.keras.callbacks.Callback):
    def on_train_begin(self, logs=None):
        self.tempo_inicio = time.time()

    def on_epoch_end(self, epoch, logs=None):
        epocas_feitas = epoch + 1
        epocas_totais = self.params['epochs']
        epocas_restantes = epocas_totais - epocas_feitas

        # Calcula a média de tempo por época até o momento
        tempo_decorrido = time.time() - self.tempo_inicio
        tempo_medio_por_epoca = tempo_decorrido / epocas_feitas

        # Estima o tempo restante
        tempo_restante_seg = tempo_medio_por_epoca * epocas_restantes

        # Converte para horas, minutos e segundos
        h = int(tempo_restante_seg // 3600)
        m = int((tempo_restante_seg % 3600) // 60)
        s = int(tempo_restante_seg % 60)

        if epocas_restantes > 0:
            print(f"\n[ETA Global] Faltam {epocas_restantes} épocas. Fim estimado em: {h}h {m}m {s}s\n")

# ==========================================
# 4. TREINAMENTO
# ==========================================

# coloquei 10000 épocas mas se tornou ineficiente pós as 6000. com acurácia maxima de 98.25%
# (essa acurácia é por pixel e o fundo domina; o histórico com Dice/IoU por época fica no CSV abaixo)
print("\n-> Iniciando Treinamento")
os.makedirs(DIR_MODELOS, exist_ok=True)
historico = tf.keras.callbacks.CSVLogger(os.path.join(DIR_RELATORIOS, "historico_treino_segmentacao.csv"))
model.fit(X_train, Y_train, validation_data=(X_val, Y_val), epochs=args.epocas, batch_size=1,
          callbacks=[TempoEstimadoCallback(), historico])

# isso é só o backup temporário do modelo, não é necessário para o ESP32
model.save(os.path.join(DIR_MODELOS, "modelo_medidor.h5"))

# ==========================================
# 5. CONVERSÃO E QUANTIZAÇÃO (TFLITE INT8)
# ==========================================
print("\n-> Iniciando Conversão para int8")

def representative_dataset():
    # só imagens de treino: a quantização não pode ver o conjunto de teste
    for i in range(min(1244, len(X_train))):
        amostra = np.expand_dims(X_train[i], axis=0).astype(np.float32)
        yield [amostra]

# TFLiteConverter.from_keras_model trava com um erro do MLIR em TF 2.16.1 + Keras 3 (mesmo caso de
# treinar_classificador_digitos.py): exportar como SavedModel e converter a partir dele contorna o problema.
CAMINHO_SAVEDMODEL = os.path.join(args.saida, "_savedmodel_segmentacao")
model.export(CAMINHO_SAVEDMODEL)
converter = tf.lite.TFLiteConverter.from_saved_model(CAMINHO_SAVEDMODEL)
converter.optimizations = [tf.lite.Optimize.DEFAULT]
converter.representative_dataset = representative_dataset

# Quantização completa para int8, incluindo entrada e saída
converter.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
converter.inference_input_type = tf.int8
converter.inference_output_type = tf.int8

tflite_quant_model = converter.convert()

caminho_tflite = os.path.join(DIR_MODELOS, "modelo_esp32.tflite")
with open(caminho_tflite, "wb") as f:
    f.write(tflite_quant_model)

print("\n->Arquivo 'modelos/modelo_esp32.tflite' gerado.")

# ==========================================
# 6. AVALIAÇÃO NO CONJUNTO DE TESTE (Dice/IoU)
# ==========================================
print("\n-> Avaliando Dice/IoU no conjunto de teste")


def dice_iou_np(prevista, real):
    inter = np.logical_and(prevista, real).sum()
    soma = prevista.sum() + real.sum()
    uniao = soma - inter
    return (2 * inter / soma if soma else 1.0), (inter / uniao if uniao else 1.0)


def media_dice_iou(previstas):
    pares = [dice_iou_np(p, y > 0.5) for p, y in zip(previstas, Y_test)]
    return {"dice": float(np.mean([d for d, _ in pares])), "iou": float(np.mean([i for _, i in pares]))}


prev_float = [model.predict(x[np.newaxis], verbose=0)[0] > 0.5 for x in X_test]

interp = tf.lite.Interpreter(model_content=tflite_quant_model)
interp.allocate_tensors()
entrada, saida = interp.get_input_details()[0], interp.get_output_details()[0]
escala_in, zp_in = entrada["quantization"]
prev_int8 = []
for x in X_test:
    q = np.clip(np.round(x / escala_in + zp_in), -128, 127).astype(np.int8)[np.newaxis]
    interp.set_tensor(entrada["index"], q)
    interp.invoke()
    # mesmo limiar do firmware: saída int8 > 0 (com zero_point -128 isso é sigmoide > 0,5)
    prev_int8.append(interp.get_tensor(saida["index"])[0] > 0)

resultado = {"n_teste": len(X_test), "seed": SEED, "epocas": args.epocas,
             "float": media_dice_iou(prev_float), "int8": media_dice_iou(prev_int8),
             "mascara_vazia_int8": int(sum(not p.any() for p in prev_int8))}
with open(os.path.join(DIR_RELATORIOS, "segmentacao_teste.json"), "w", encoding="utf-8") as f:
    json.dump(resultado, f, indent=2)
print(json.dumps(resultado, indent=2))
