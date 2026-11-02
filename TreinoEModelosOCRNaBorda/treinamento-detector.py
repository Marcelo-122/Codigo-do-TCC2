import os
os.environ['TF_USE_LEGACY_KERAS'] = '1'

import time
import random
import numpy as np
import pandas as pd
import tensorflow as tf
from tensorflow.keras import layers, models
import tensorflow_model_optimization as tfmot
import tensorflow.keras.backend as K

from config_detector import (IMG_SIZE, PERFIL_DETECTOR, PERFIS, NOME_MODELO,
                             carregar_imagem, carregar_mascara,
                             bbox_da_prob, iou_bbox, dice_np)
from estimar_memoria_modelo import estimar_memoria_grafo

for gpu in tf.config.list_physical_devices('GPU'):
    tf.config.experimental.set_memory_growth(gpu, True)

SEED = 42
random.seed(SEED)
np.random.seed(SEED)
tf.random.set_seed(SEED)

AUTOTUNE = tf.data.AUTOTUNE


def dice_coef(y_true, y_pred, smooth=1e-6):
    y_true_f = K.flatten(tf.cast(y_true, tf.float32))
    y_pred_f = K.flatten(y_pred)
    intersection = K.sum(y_true_f * y_pred_f)
    return (2. * intersection + smooth) / (K.sum(y_true_f) + K.sum(y_pred_f) + smooth)

def dice_loss(y_true, y_pred):
    return 1.0 - dice_coef(y_true, y_pred)

def bce_dice_loss(y_true, y_pred):
    bce = tf.reduce_mean(tf.keras.losses.binary_crossentropy(y_true, y_pred))
    return bce + dice_loss(y_true, y_pred)

# ==========================================
# 1. CONFIGURAÇÕES
# ==========================================
DIRETORIO_ATUAL = os.path.dirname(os.path.abspath(__file__))
DIR_IMG = os.path.join(DIRETORIO_ATUAL, "dataset", "images")
DIR_MASK = os.path.join(DIRETORIO_ATUAL, "dataset", "masks")
DIR_CSVS = os.path.join(DIRETORIO_ATUAL, "CSVs")
DIR_SAIDA = os.path.join(DIRETORIO_ATUAL, "Modelos")

BATCH_SIZE = 8                 
EPOCAS_PRETREINO_FLOAT = 250
EPOCAS_FINETUNE_QAT = 100

os.makedirs(DIR_CSVS, exist_ok=True)
os.makedirs(DIR_SAIDA, exist_ok=True)

print(f"-> Detector: perfil '{PERFIL_DETECTOR}' @ {IMG_SIZE[0]}x{IMG_SIZE[1]}  ({NOME_MODELO})")

# ==========================================
# 2. CARREGAMENTO DOS DADOS E SEPARAÇÃO
# ==========================================
print("-> Carregando imagens e máscaras...")
arquivos = sorted(f for f in os.listdir(DIR_IMG) if f.lower().endswith(('.png', '.jpg', '.jpeg')))
X, Y, sem_mascara = [], [], 0

for arquivo in arquivos:
    caminho_mask = os.path.join(DIR_MASK, arquivo)
    if not os.path.exists(caminho_mask):
        sem_mascara += 1
        continue
    X.append(carregar_imagem(os.path.join(DIR_IMG, arquivo)))
    Y.append(carregar_mascara(caminho_mask))

X_full = np.array(X, dtype=np.float32)
Y_full = np.array(Y, dtype=np.float32)
print(f"Dataset carregado! {len(X_full)} amostras" + (f" ({sem_mascara} sem máscara, ignoradas)." if sem_mascara else "."))

split_idx = int(len(X_full) * 0.8)
X_train, X_val = X_full[:split_idx], X_full[split_idx:]
Y_train, Y_val = Y_full[:split_idx], Y_full[split_idx:]

# ==========================================
# 3. DATA AUGMENTATION
# ==========================================
PAD_AUG = max(2, IMG_SIZE[0] // 16)

def augment(image, mask):
    if tf.random.uniform(()) > 0.5:
        image = tf.image.flip_left_right(image)
        mask = tf.image.flip_left_right(mask)

    # Deslocamento aleatório, idêntico em imagem e máscara
    ambos = tf.concat([image, mask], axis=-1)
    ambos = tf.pad(ambos, [[PAD_AUG, PAD_AUG], [PAD_AUG, PAD_AUG], [0, 0]])
    ambos = tf.image.random_crop(ambos, [IMG_SIZE[0], IMG_SIZE[1], 2])
    image, mask = ambos[..., :1], ambos[..., 1:]

    # Variação fotométrica só na imagem
    image = tf.image.random_brightness(image, 0.15)
    image = tf.image.random_contrast(image, 0.8, 1.2)
    image = tf.clip_by_value(image, 0.0, 1.0)
    return image, mask

dataset_treino = (tf.data.Dataset.from_tensor_slices((X_train, Y_train))
                  .shuffle(len(X_train), seed=SEED)          # antes não embaralhava
                  .map(augment, num_parallel_calls=AUTOTUNE)
                  .batch(BATCH_SIZE)
                  .prefetch(AUTOTUNE))

dataset_val = (tf.data.Dataset.from_tensor_slices((X_val, Y_val))
               .batch(BATCH_SIZE)
               .prefetch(AUTOTUNE))

# ==========================================
# 4. ARQUITETURA U-NET COM SKIP CONNECTIONS (PERFIS DE LARGURA)
# ==========================================
def bloco_conv(x, filtros):
    x = layers.Conv2D(filtros, (3, 3), padding='same', use_bias=False)(x)
    x = layers.BatchNormalization()(x)
    return layers.ReLU()(x)

def construir_unet(perfil):
    cfg = PERFIS[perfil]
    c, k_t = cfg["canais"], cfg["k_t"]
    inputs = layers.Input(shape=(IMG_SIZE[0], IMG_SIZE[1], 1))

    x, skips = inputs, []
    for nivel in range(3):
        for _ in range(cfg["convs_alto"] if nivel < 2 else 2):
            x = bloco_conv(x, c[nivel])
        skips.append(x)
        x = layers.MaxPooling2D((2, 2))(x)

    x = bloco_conv(x, c[3])
    x = bloco_conv(x, c[3])

    for nivel in (2, 1, 0):
        x = layers.Conv2DTranspose(c[nivel], (k_t, k_t), strides=(2, 2),
                                   padding='same', activation='relu')(x)
        x = layers.concatenate([x, skips[nivel]])
        x = bloco_conv(x, c[nivel])

    outputs = layers.Conv2D(1, (1, 1), activation='sigmoid', padding='same')(x)
    return models.Model(inputs=inputs, outputs=outputs)

print("\n-> Criando modelo...")
base_model = construir_unet(PERFIL_DETECTOR)
try:
    estimar_memoria_grafo(base_model, nome=f"detector '{PERFIL_DETECTOR}' @{IMG_SIZE[0]}")
except Exception as e:      # a estimativa usa APIs internas do Keras; nunca deve impedir o treino
    print(f"   [AVISO] não foi possível estimar a memória: {e}")

# ==========================================
# 5. CALLBACKS
# ==========================================
class TempoEstimadoCallback(tf.keras.callbacks.Callback):
    def on_train_begin(self, logs=None):
        self.tempo_inicio = time.time()

    def on_epoch_end(self, epoch, logs=None):
        feitas = epoch + 1
        restantes = self.params['epochs'] - feitas
        if restantes > 0:
            seg = (time.time() - self.tempo_inicio) / feitas * restantes
            print(f"\n[ETA] Faltam {restantes} épocas. Fim estimado em: "
                  f"{int(seg // 3600)}h {int((seg % 3600) // 60)}m {int(seg % 60)}s\n")

def build_callbacks(nome_backup):
    return [
        TempoEstimadoCallback(),
        # só pesos: não depende de serializar camadas quantizadas
        tf.keras.callbacks.ModelCheckpoint(nome_backup, save_best_only=True, save_weights_only=True,
                                           monitor='val_loss'),
        tf.keras.callbacks.ReduceLROnPlateau(monitor='val_loss', factor=0.5, patience=8,
                                             min_lr=1e-6, verbose=1),
        tf.keras.callbacks.EarlyStopping(monitor='val_loss', patience=25, restore_best_weights=True)
    ]

# ==========================================
# 6. FASE 1 — TREINO EM PONTO FLUTUANTE
# ==========================================
print("\n-> Fase 1: treinando modelo em ponto flutuante (sem quantização)")
base_model.compile(
    optimizer=tf.keras.optimizers.Adam(learning_rate=1e-3),
    loss=bce_dice_loss,
    metrics=[dice_coef]       
)

history_float = base_model.fit(
    dataset_treino,
    validation_data=dataset_val,
    epochs=EPOCAS_PRETREINO_FLOAT,
    callbacks=build_callbacks(os.path.join(DIR_SAIDA, f"backup_{NOME_MODELO}_float.h5"))
)

# ==========================================
# 7. AVALIAÇÃO POR CAIXA (O QUE IMPORTA PARA O RECORTE)
# ==========================================
def prever_lote(modelo, X):
    saidas = [modelo(X[i:i + BATCH_SIZE], training=False).numpy() for i in range(0, len(X), BATCH_SIZE)]
    return np.concatenate(saidas)[..., 0]

def resumir_deteccao(probs, gts):
    dices, ious = [], []
    for p, g in zip(probs, gts):
        dices.append(dice_np(p > 0.5, g))
        bb_pred, _ = bbox_da_prob(p, 0.5)           
        bb_real, _ = bbox_da_prob(g, 0.5, kernel=0)
        ious.append(iou_bbox(bb_pred, bb_real))
    return np.array(dices), np.array(ious)

def imprimir_deteccao(titulo, dices, ious):
    print(f"   {titulo}  (n={len(dices)})")
    print(f"     Dice médio: {dices.mean():.3f} | mediana: {np.median(dices):.3f}")
    print(f"     IoU da caixa: média {ious.mean():.3f} | mediana {np.median(ious):.3f}")
    print("     Recortes aproveitáveis (IoU da caixa >=): " +
          " | ".join(f"{lim:.2f}: {100 * np.mean(ious >= lim):.1f}%" for lim in (0.50, 0.75, 0.90)))

print("\n-> Avaliação do modelo float na validação...")
imprimir_deteccao("float", *resumir_deteccao(prever_lote(base_model, X_val), Y_val[..., 0]))

# ==========================================
# 8. FASE 2 — FINE-TUNING COM QAT
# ==========================================
print("\n-> Fase 2: aplicando QAT e fazendo fine-tuning com taxa de aprendizagem baixa")
qat_model = tfmot.quantization.keras.quantize_model(base_model)

qat_model.compile(
    optimizer=tf.keras.optimizers.Adam(learning_rate=1e-5),
    loss=bce_dice_loss,
    metrics=[dice_coef]
)

history_qat = qat_model.fit(
    dataset_treino,
    validation_data=dataset_val,
    epochs=EPOCAS_FINETUNE_QAT,
    callbacks=[
        TempoEstimadoCallback(),
        tf.keras.callbacks.EarlyStopping(monitor='val_loss', patience=15, restore_best_weights=True)
    ]
)

print("\n-> Exportando métricas de treino para CSV...")
df_float = pd.DataFrame(history_float.history)
df_float['fase'] = 'float'
df_qat = pd.DataFrame(history_qat.history)
df_qat['fase'] = 'qat'
caminho_csv = os.path.join(DIR_CSVS, f"historico_treino_{NOME_MODELO}.csv")
pd.concat([df_float, df_qat], ignore_index=True).to_csv(caminho_csv, index_label="Epoca")
print(f"-> Arquivo CSV salvo em: {caminho_csv}")

print("\n-> Avaliação do modelo QAT na validação...")
imprimir_deteccao("QAT", *resumir_deteccao(prever_lote(qat_model, X_val), Y_val[..., 0]))

qat_model.save(os.path.join(DIR_SAIDA, f"{NOME_MODELO}.h5"))

# ==========================================
# 9. CONVERSÃO E QUANTIZAÇÃO (TFLITE INT8)
# ==========================================
print("\n-> Iniciando Conversão")

def representative_dataset():
    idx = np.random.default_rng(SEED).choice(len(X_train), size=min(150, len(X_train)), replace=False)
    for i in idx:
        yield [X_train[i:i + 1]]

converter = tf.lite.TFLiteConverter.from_keras_model(qat_model)
converter.optimizations = [tf.lite.Optimize.DEFAULT]
converter.representative_dataset = representative_dataset
converter.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
converter.inference_input_type = tf.int8
converter.inference_output_type = tf.int8

tflite_quant_model = converter.convert()

caminho_tflite = os.path.join(DIR_SAIDA, f"{NOME_MODELO}.tflite")
with open(caminho_tflite, "wb") as f:
    f.write(tflite_quant_model)
print(f"-> Modelo salvo em: {caminho_tflite} ({len(tflite_quant_model) / 1024:.0f} KiB)")

# ==========================================
# 10. VALIDAÇÃO DO .TFLITE (o que roda no dispositivo)
# ==========================================
print("\n-> Validando o .tflite INT8 na validação...")
interpretador = tf.lite.Interpreter(model_content=tflite_quant_model)
interpretador.allocate_tensors()
det_in = interpretador.get_input_details()[0]
det_out = interpretador.get_output_details()[0]
escala_in, zero_in = det_in['quantization']
escala_out, zero_out = det_out['quantization']

def prever_tflite(img):
    q = np.clip(np.round(img / escala_in + zero_in), -128, 127).astype(np.int8)
    interpretador.set_tensor(det_in['index'], q[np.newaxis, ...])
    interpretador.invoke()
    bruto = interpretador.get_tensor(det_out['index'])[0, ..., 0].astype(np.float32)
    return (bruto - zero_out) * escala_out

probs_tflite = np.array([prever_tflite(x) for x in X_val])
imprimir_deteccao("TFLite INT8", *resumir_deteccao(probs_tflite, Y_val[..., 0]))

print(f"\n-> Modelos do detector salvos na pasta: {DIR_SAIDA}")
