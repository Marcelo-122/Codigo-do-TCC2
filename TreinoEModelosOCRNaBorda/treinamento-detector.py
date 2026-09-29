import os
os.environ['TF_USE_LEGACY_KERAS'] = '1' 

import time
import random
import numpy as np
import pandas as pd
import tensorflow as tf
from tensorflow.keras import layers, models
from tensorflow.keras.utils import load_img, img_to_array
import tensorflow_model_optimization as tfmot
import tensorflow.keras.backend as K

gpus = tf.config.list_physical_devices('GPU')
for gpu in gpus:
    tf.config.experimental.set_memory_growth(gpu, True)

# Trava as sementes matemáticas para garantir validações idênticas entre diferentes treinos
SEED = 42
random.seed(SEED)
np.random.seed(SEED)
tf.random.set_seed(SEED)

def dice_coef(y_true, y_pred, smooth=1e-6):
    y_true_f = K.flatten(tf.cast(y_true, tf.float32))
    y_pred_f = K.flatten(y_pred)
    intersection = K.sum(y_true_f * y_pred_f)
    return (2. * intersection + smooth) / (K.sum(y_true_f) + K.sum(y_pred_f) + smooth)

def dice_loss(y_true, y_pred):
    return 1.0 - dice_coef(y_true, y_pred)

def bce_dice_loss(y_true, y_pred):
    bce = tf.keras.losses.binary_crossentropy(y_true, y_pred)
    bce = tf.reduce_mean(bce)
    return bce + dice_loss(y_true, y_pred)

# ==========================================
# 1. CONFIGURAÇÕES
# ========================================== 
DIRETORIO_ATUAL = os.path.dirname(os.path.abspath(__file__))

DIR_IMG = os.path.join(DIRETORIO_ATUAL, "dataset", "images")
DIR_MASK = os.path.join(DIRETORIO_ATUAL, "dataset", "masks")
DIR_CSVS = os.path.join(DIRETORIO_ATUAL, "CSVs")
IMG_SIZE = (384, 384)

EPOCAS_PRETREINO_FLOAT = 250
EPOCAS_FINETUNE_QAT = 100

os.makedirs(DIR_CSVS, exist_ok=True)

# ==========================================
# 2. CARREGAMENTO DOS DADOS E SEPARAÇÃO
# ==========================================
print("-> Carregando imagens e máscaras...")
arquivos = sorted(os.listdir(DIR_IMG))
X, Y = [], []

for arquivo in arquivos:
    if not arquivo.endswith(('.png', '.jpg', '.jpeg')): continue

    caminho_img = os.path.join(DIR_IMG, arquivo)
    caminho_mask = os.path.join(DIR_MASK, arquivo)

    img_array = img_to_array(load_img(caminho_img, color_mode="grayscale", target_size=IMG_SIZE)) / 255.0
    mask_array = img_to_array(load_img(caminho_mask, color_mode="grayscale", target_size=IMG_SIZE)) / 255.0

    mask_array = np.where(mask_array > 0.5, 1.0, 0.0)

    X.append(img_array)
    Y.append(mask_array)

X_train_full = np.array(X)
Y_train_full = np.array(Y)
print(f"Dataset carregado! Total: {len(X_train_full)} amostras.")

split_idx = int(len(X_train_full) * 0.8)
X_train, X_val = X_train_full[:split_idx], X_train_full[split_idx:]
Y_train, Y_val = Y_train_full[:split_idx], Y_train_full[split_idx:]

# ==========================================
# 3. DATA AUGMENTATION UNIFICADO
# ==========================================
def augment(image, mask):
    if tf.random.uniform(()) > 0.5:
        image = tf.image.flip_left_right(image)
        mask = tf.image.flip_left_right(mask)
    return image, mask

dataset_treino = tf.data.Dataset.from_tensor_slices((X_train, Y_train))
dataset_treino = dataset_treino.map(augment, num_parallel_calls=tf.data.AUTOTUNE)
dataset_treino = dataset_treino.batch(1).prefetch(tf.data.AUTOTUNE)

dataset_val = tf.data.Dataset.from_tensor_slices((X_val, Y_val))
dataset_val = dataset_val.batch(1).prefetch(tf.data.AUTOTUNE)

# ==========================================
# 4. ARQUITETURA DO MODELO (U-NET COM SKIP CONNECTIONS)
# ==========================================
print("\n-> Criando modelo...")
inputs = layers.Input(batch_shape=(1, IMG_SIZE[0], IMG_SIZE[1], 1))

# --- Encoder ---
c1 = layers.Conv2D(16, (3, 3), activation='relu', padding='same')(inputs)
c1 = layers.Conv2D(16, (3, 3), activation='relu', padding='same')(c1)
p1 = layers.MaxPooling2D((2, 2))(c1)

c2 = layers.Conv2D(32, (3, 3), activation='relu', padding='same')(p1)
c2 = layers.Conv2D(32, (3, 3), activation='relu', padding='same')(c2)
p2 = layers.MaxPooling2D((2, 2))(c2)

c3 = layers.Conv2D(64, (3, 3), activation='relu', padding='same')(p2)
c3 = layers.Conv2D(64, (3, 3), activation='relu', padding='same')(c3)
p3 = layers.MaxPooling2D((2, 2))(c3)

# --- Bottleneck ---
cb = layers.Conv2D(128, (3, 3), activation='relu', padding='same')(p3)
cb = layers.Conv2D(128, (3, 3), activation='relu', padding='same')(cb)

# --- Decoder (com skip connections vindas do encoder) ---
u3 = layers.Conv2DTranspose(64, (3, 3), strides=(2, 2), padding='same', activation='relu')(cb)
u3 = layers.concatenate([u3, c3])
u3 = layers.Conv2D(64, (3, 3), activation='relu', padding='same')(u3)

u2 = layers.Conv2DTranspose(32, (3, 3), strides=(2, 2), padding='same', activation='relu')(u3)
u2 = layers.concatenate([u2, c2])
u2 = layers.Conv2D(32, (3, 3), activation='relu', padding='same')(u2)

u1 = layers.Conv2DTranspose(16, (3, 3), strides=(2, 2), padding='same', activation='relu')(u2)
u1 = layers.concatenate([u1, c1])
u1 = layers.Conv2D(16, (3, 3), activation='relu', padding='same')(u1)

outputs = layers.Conv2D(1, (1, 1), activation='sigmoid', padding='same')(u1)

base_model = models.Model(inputs=[inputs], outputs=[outputs])

# ==========================================
# 5. CALLBACKS DE PROTEÇÃO
# ==========================================
class TempoEstimadoCallback(tf.keras.callbacks.Callback):
    def on_train_begin(self, logs=None):
        self.tempo_inicio = time.time()

    def on_epoch_end(self, epoch, logs=None):
        epocas_feitas = epoch + 1
        epocas_totais = self.params['epochs']
        epocas_restantes = epocas_totais - epocas_feitas

        tempo_decorrido = time.time() - self.tempo_inicio
        tempo_medio_por_epoca = tempo_decorrido / epocas_feitas
        tempo_restante_seg = tempo_medio_por_epoca * epocas_restantes

        h = int(tempo_restante_seg // 3600)
        m = int((tempo_restante_seg % 3600) // 60)
        s = int(tempo_restante_seg % 60)

        if epocas_restantes > 0:
            print(f"\n[ETA] Faltam {epocas_restantes} épocas. Fim estimado em: {h}h {m}m {s}s\n")

def build_callbacks(nome_checkpoint):
    return [
        TempoEstimadoCallback(),
        tf.keras.callbacks.ModelCheckpoint(nome_checkpoint, save_best_only=True, monitor='val_loss'),
        tf.keras.callbacks.EarlyStopping(monitor='val_loss', patience=25, restore_best_weights=True)
    ]

# ==========================================
# 6. FASE 1 — TREINO EM PONTO FLUTUANTE
# ==========================================
print("\n-> Fase 1: treinando modelo em ponto flutuante (sem quantização)")
base_model.compile(
    optimizer=tf.keras.optimizers.Adam(learning_rate=1e-3),
    loss=bce_dice_loss,
    metrics=[dice_coef, 'accuracy']
)

history_float = base_model.fit(
    dataset_treino,
    validation_data=dataset_val,
    epochs=EPOCAS_PRETREINO_FLOAT,
    callbacks=build_callbacks('backup_medidor_float.keras')
)

# ==========================================
# 7. FASE 2 — FINE-TUNING COM QAT
# ==========================================
print("\n-> Fase 2: aplicando QAT e fazendo fine-tuning com taxa de aprendizagem baixa")
qat_model = tfmot.quantization.keras.quantize_model(base_model)

qat_model.compile(
    optimizer=tf.keras.optimizers.Adam(learning_rate=1e-5),  # LR bem menor: é só ajuste fino
    loss=bce_dice_loss,
    metrics=[dice_coef, 'accuracy']
)

history_qat = qat_model.fit(
    dataset_treino,
    validation_data=dataset_val,
    epochs=EPOCAS_FINETUNE_QAT,
    callbacks=build_callbacks('backup_medidor_qat.keras')
)

# ================== EXPORTAÇÃO DO HISTÓRICO ==================
print("\n-> Exportando métricas de treino para CSV...")
df_float = pd.DataFrame(history_float.history)
df_float['fase'] = 'float'
df_qat = pd.DataFrame(history_qat.history)
df_qat['fase'] = 'qat'
df_historico = pd.concat([df_float, df_qat], ignore_index=True)
caminho_csv = os.path.join(DIR_CSVS, "historico_treino_detector.csv")
df_historico.to_csv(caminho_csv, index_label="Epoca")
print(f"-> Arquivo CSV salvo em: {caminho_csv}")
# ================================================

DIR_SAIDA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Modelos")
os.makedirs(DIR_SAIDA, exist_ok=True)

caminho_unet_h5 = os.path.join(DIR_SAIDA, "modelo_medidor.h5")
qat_model.save(caminho_unet_h5)

# ==========================================
# 8. CONVERSÃO E QUANTIZAÇÃO (TFLITE INT8)
# ==========================================
print("\n-> Iniciando Conversão")

def representative_dataset():
    for amostra, _ in dataset_treino.take(100):
        yield [amostra.numpy()]

converter = tf.lite.TFLiteConverter.from_keras_model(qat_model)
converter.optimizations = [tf.lite.Optimize.DEFAULT]
converter.representative_dataset = representative_dataset

converter.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
converter.inference_input_type = tf.int8
converter.inference_output_type = tf.int8

tflite_quant_model = converter.convert()

caminho_unet_tflite = os.path.join(DIR_SAIDA, "modelo_medidor.tflite")
with open(caminho_unet_tflite, "wb") as f:
    f.write(tflite_quant_model)

print(f"\n-> Modelos do detector salvos na pasta: {DIR_SAIDA}")