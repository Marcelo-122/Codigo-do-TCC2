import os
import shutil
os.environ['TF_USE_LEGACY_KERAS'] = '1'

import math
import random
from collections import Counter
import cv2
import numpy as np
import pandas as pd
import tensorflow as tf
from tensorflow.keras import layers, models
import tensorflow_model_optimization as tfmot
from diagnostico_colapso_ctc import diagnosticar_colapso

for gpu in tf.config.list_physical_devices('GPU'):
    tf.config.experimental.set_memory_growth(gpu, True)

SEED = 42
random.seed(SEED)
np.random.seed(SEED)
tf.random.set_seed(SEED)

AUTOTUNE = tf.data.AUTOTUNE

# ==========================================
# 1. CONFIGURAÇÕES
# ==========================================
DIRETORIO_ATUAL = os.path.dirname(os.path.abspath(__file__))

DIR_DATASET_REAL = os.path.join(DIRETORIO_ATUAL, "dataset", "visores_blackout")
DIR_DATASET_SINT = os.path.join(DIRETORIO_ATUAL, "dataset", "visores_sinteticos")
DIR_CSVS = os.path.join(DIRETORIO_ATUAL, "CSVs")
DIR_SAIDA = os.path.join(DIRETORIO_ATUAL, "Modelos")
DIR_BACKUPS = os.path.join(DIRETORIO_ATUAL, "Backups")

FRACAO_SINTETICA = 0.4
FRACAO_SINTETICA_QAT = 0.15     
SUFIXO_SAIDA = "_ctc_sint" if FRACAO_SINTETICA > 0.0 else "_ctc"

IMG_HEIGHT = 48                 
IMG_WIDTH = 224                 
TIMESTEPS = IMG_WIDTH // 4      

MAX_DIGITOS = 8                 
N_CLASSES = 11                  
BLANK = 10
PAD = -1                        

BATCH_SIZE = 32
EPOCAS_FLOAT = 600
EPOCAS_QAT = 100

os.makedirs(DIR_CSVS, exist_ok=True)
os.makedirs(DIR_SAIDA, exist_ok=True)
os.makedirs(DIR_BACKUPS, exist_ok=True)

# ==========================================
# 2. MAPEAMENTO DOS DOIS DATASETS
# ==========================================
def mapear_diretorio(diretorio):
    imagens_por_rotulo = {}
    for root, dirs, files in os.walk(diretorio):
        nome_pasta = os.path.basename(root)
        if not nome_pasta or nome_pasta.startswith('.') or "visores" in nome_pasta:
            continue
        imgs = [os.path.join(root, f) for f in files if f.lower().endswith(('.png', '.jpg', '.jpeg'))]
        if not imgs: continue
        
        rotulo = nome_pasta.strip().upper().rstrip('X')
        if not (1 <= len(rotulo) <= MAX_DIGITOS) or not all(c in '0123456789' for c in rotulo):
            continue
        imagens_por_rotulo.setdefault(rotulo, []).extend(imgs)
    return imagens_por_rotulo

def montar_listas(dicionario):
    caminhos, labels = [], []
    for r in dicionario.keys():
        codificado = [int(c) for c in r] + [PAD] * (MAX_DIGITOS - len(r))
        for caminho in dicionario[r]:
            caminhos.append(caminho)
            labels.append(codificado)
    return caminhos, np.array(labels, dtype=np.int32)

print("-> Mapeando dados reais e sintéticos...")
mapa_reais = mapear_diretorio(DIR_DATASET_REAL)
mapa_sinteticos = mapear_diretorio(DIR_DATASET_SINT)

if not mapa_reais: raise ValueError("Nenhuma imagem real encontrada.")
if not mapa_sinteticos: print("   [AVISO] Nenhuma imagem sintética encontrada. Treinando apenas com reais.")

rotulos_reais = sorted(mapa_reais.keys())
random.shuffle(rotulos_reais)

# Separa apenas os DADOS REAIS para a validação (para termos uma métrica honesta do mundo real)
corte = int(len(rotulos_reais) * 0.8)
rotulos_treino_reais, rotulos_val_reais = rotulos_reais[:corte], rotulos_reais[corte:]

mapa_treino_real = {k: mapa_reais[k] for k in rotulos_treino_reais}
mapa_val_real = {k: mapa_reais[k] for k in rotulos_val_reais}

cam_treino_real, lbl_treino_real = montar_listas(mapa_treino_real)
cam_val, lbl_val = montar_listas(mapa_val_real)
cam_treino_sint, lbl_treino_sint = montar_listas(mapa_sinteticos)

print(f"-> Treino: {len(cam_treino_real)} imagens reais | {len(cam_treino_sint)} imagens sintéticas.")
print(f"-> Validação: {len(cam_val)} imagens reais.")

# ==========================================
# 3. PIPELINE tf.data (CARREGAMENTO DO DISCO)
# ==========================================
def carregar(caminho, rotulo):
    img = tf.io.read_file(caminho)
    img = tf.image.decode_image(img, channels=1, expand_animations=False)
    img = tf.cast(img, tf.float32)

    altura, largura = tf.cast(tf.shape(img)[0], tf.float32), tf.cast(tf.shape(img)[1], tf.float32)
    escala = tf.minimum(float(IMG_HEIGHT) / altura, float(IMG_WIDTH) / largura)
    nova_h = tf.maximum(1, tf.cast(tf.round(altura * escala), tf.int32))
    nova_w = tf.maximum(1, tf.cast(tf.round(largura * escala), tf.int32))
    
    img = tf.image.resize(img, [nova_h, nova_w])
    img = tf.pad(img, [[0, IMG_HEIGHT - nova_h], [0, IMG_WIDTH - nova_w], [0, 0]], constant_values=0.0)
    img = tf.reshape(img, [IMG_HEIGHT, IMG_WIDTH, 1])
    return tf.cast(tf.round(img), tf.uint8), rotulo

def normalizar(img, rotulo):
    return tf.cast(img, tf.float32) / 255.0, rotulo

def augmentar(img, rotulo):
    img = tf.image.random_brightness(img, 0.20)
    img = tf.image.random_contrast(img, 0.7, 1.3)
    img = tf.pad(img, [[4, 4], [4, 4], [0, 0]], constant_values=0.0)
    img = tf.image.random_crop(img, [IMG_HEIGHT, IMG_WIDTH, 1])
    img = img + tf.random.normal(tf.shape(img), mean=0.0, stddev=0.03)

    if tf.random.uniform(()) < 0.3:
        ch, cw = tf.random.uniform((), 4, 10, dtype=tf.int32), tf.random.uniform((), 4, 14, dtype=tf.int32)
        y0, x0 = tf.random.uniform((), 0, IMG_HEIGHT - ch, dtype=tf.int32), tf.random.uniform((), 0, IMG_WIDTH - cw, dtype=tf.int32)
        mascara_corte = tf.ones([IMG_HEIGHT, IMG_WIDTH, 1])
        atualizacao = tf.zeros([ch, cw, 1])
        mascara_corte = tf.tensor_scatter_nd_update(
            mascara_corte,
            tf.reshape(tf.stack(tf.meshgrid(tf.range(y0, y0 + ch), tf.range(x0, x0 + cw), indexing='ij'), axis=-1), [-1, 2]),
            tf.reshape(atualizacao, [-1, 1]))
        img = img * mascara_corte

    return tf.clip_by_value(img, 0.0, 1.0), rotulo

def criar_dataset(caminhos, labels, em_cache=True):
    ds = tf.data.Dataset.from_tensor_slices((caminhos, labels))
    ds = ds.map(carregar, num_parallel_calls=AUTOTUNE)
    if em_cache: ds = ds.cache()
    return ds

ds_real_treino = criar_dataset(cam_treino_real, lbl_treino_real)
ds_sint_treino = criar_dataset(cam_treino_sint, lbl_treino_sint) if len(cam_treino_sint) > 0 else None

def montar_dataset_treino(fracao_sintetica):
    ds_real = ds_real_treino.shuffle(len(cam_treino_real), seed=SEED).repeat()
    
    if fracao_sintetica > 0.0 and ds_sint_treino is not None:
        ds_sint = ds_sint_treino.shuffle(len(cam_treino_sint), seed=SEED).repeat()
        ds = tf.data.Dataset.sample_from_datasets([ds_real, ds_sint], weights=[1.0 - fracao_sintetica, fracao_sintetica], seed=SEED)
    else:
        ds = ds_real

    ds = ds.map(normalizar, num_parallel_calls=AUTOTUNE).map(augmentar, num_parallel_calls=AUTOTUNE).batch(BATCH_SIZE).prefetch(AUTOTUNE)
    passos = math.ceil(len(cam_treino_real) / (BATCH_SIZE * (1.0 - fracao_sintetica)))
    return ds, passos

dataset_val = criar_dataset(cam_val, lbl_val).map(normalizar, num_parallel_calls=AUTOTUNE).batch(BATCH_SIZE).prefetch(AUTOTUNE)

# ==========================================
# 4. LOSS CTC, DECODIFICAÇÃO E MÉTRICA
# ==========================================
def ctc_loss(y_true, y_pred):
    y_true = tf.cast(y_true, tf.int32)
    tamanho_label = tf.reduce_sum(tf.cast(tf.not_equal(y_true, PAD), tf.int32), axis=1)
    labels = tf.where(tf.equal(y_true, PAD), tf.zeros_like(y_true), y_true)
    tamanho_logits = tf.fill([tf.shape(y_pred)[0]], tf.shape(y_pred)[1])
    return tf.nn.ctc_loss(labels=labels, logits=tf.cast(y_pred, tf.float32),
                          label_length=tamanho_label, logit_length=tamanho_logits,
                          logits_time_major=False, blank_index=-1)     

def decodificar_greedy(logits):
    ids = np.argmax(logits, axis=-1)
    saida, anterior = [], BLANK
    for i in ids:
        if i != anterior and i != BLANK:
            saida.append(int(i))
        anterior = i
    return saida

def lista_para_texto(lista):
    return ''.join(str(d) for d in lista)

def avaliar(modelo, dataset):
    resultados = []
    for x, y in dataset:
        logits = modelo(x, training=False).numpy()
        for l, r in zip(logits, y.numpy()):
            real = [int(v) for v in r if v != PAD]
            resultados.append((real, decodificar_greedy(l)))
    return resultados

def acuracia_sequencia(resultados):
    return float(np.mean([real == pred for real, pred in resultados]))

class AcuraciaSequenciaCallback(tf.keras.callbacks.Callback):
    def __init__(self, dataset):
        super().__init__()
        self.dataset = dataset

    def on_epoch_end(self, epoch, logs=None):
        acc = acuracia_sequencia(avaliar(self.model, self.dataset))
        if logs is not None: logs['val_seq_acc'] = acc
        print(f" - val_seq_acc (real): {acc:.4f}")

# ==========================================
# 5. ARQUITETURA CRNN SEM RECORRÊNCIA
# ==========================================
print("\n-> Construindo a rede CRNN (conv-only + CTC)...")

def bloco_conv(x, filtros, kernel=(3, 3), padding='same'):
    x = layers.Conv2D(filtros, kernel, padding=padding, use_bias=False,
                      kernel_regularizer=tf.keras.regularizers.l2(1e-4))(x)
    x = layers.BatchNormalization()(x)
    return layers.ReLU()(x)

inputs = layers.Input(shape=(IMG_HEIGHT, IMG_WIDTH, 1))

x = bloco_conv(inputs, 32)
x = layers.MaxPooling2D((2, 2))(x)
x = bloco_conv(x, 64)
x = layers.MaxPooling2D((2, 2))(x)
x = bloco_conv(x, 96)
x = layers.MaxPooling2D((2, 1))(x)
x = bloco_conv(x, 128)
x = layers.MaxPooling2D((2, 1))(x)
x = bloco_conv(x, 128)
x = bloco_conv(x, 128, kernel=(IMG_HEIGHT // 16, 1), padding='valid')

# Camadas Temporais 1D para emular contexto sem LSTM
x = bloco_conv(x, 128, kernel=(1, 5), padding='same')
x = bloco_conv(x, 128, kernel=(1, 5), padding='same')

x = layers.Reshape((TIMESTEPS, 128))(x)
x = layers.Dropout(0.35)(x)
logits = layers.Dense(N_CLASSES, name='logits')(x)

base_model = models.Model(inputs=inputs, outputs=logits)

# ==========================================
# 6. FASE 1 — TREINO EM PONTO FLUTUANTE
# ==========================================
frac_float = FRACAO_SINTETICA if ds_sint_treino else 0.0
dataset_treino_float, passos_float = montar_dataset_treino(frac_float)
print(f"\n-> Fase 1: treino em ponto flutuante ({frac_float * 100:.0f}% sintético, {passos_float} passos/época)")

base_model.compile(optimizer=tf.keras.optimizers.Adam(learning_rate=1e-3, clipnorm=1.0), loss=ctc_loss)

history_float = base_model.fit(
    dataset_treino_float, validation_data=dataset_val, epochs=EPOCAS_FLOAT, steps_per_epoch=passos_float,
    callbacks=[
        AcuraciaSequenciaCallback(dataset_val),
        tf.keras.callbacks.ReduceLROnPlateau(monitor='val_loss', factor=0.5, patience=40, min_lr=1e-6, verbose=1),
        tf.keras.callbacks.EarlyStopping(monitor='val_loss', patience=80, restore_best_weights=True)
    ]
)

print("\n-> Exportando modelo Float...")
nome_float_h5 = f"modelo_digitos_float{SUFIXO_SAIDA}.h5"
base_model.save(os.path.join(DIR_SAIDA, nome_float_h5))
shutil.copy(os.path.join(DIR_SAIDA, nome_float_h5), os.path.join(DIR_BACKUPS, nome_float_h5))

print("-> Convertendo modelo Float para TFLite (Sem Quantização)...")
converter_float = tf.lite.TFLiteConverter.from_keras_model(base_model)
tflite_float = converter_float.convert()
nome_float_tflite = f"modelo_digitos_float{SUFIXO_SAIDA}.tflite"
with open(os.path.join(DIR_SAIDA, nome_float_tflite), "wb") as f: f.write(tflite_float)
shutil.copy(os.path.join(DIR_SAIDA, nome_float_tflite), os.path.join(DIR_BACKUPS, nome_float_tflite))

# ==========================================
# 7. FASE 2 — FINE-TUNING COM QAT
# ==========================================
frac_qat = FRACAO_SINTETICA_QAT if ds_sint_treino else 0.0
dataset_treino_qat, passos_qat = montar_dataset_treino(frac_qat)
print(f"\n-> Fase 2: QAT com learning rate baixa ({frac_qat * 100:.0f}% sintético, {passos_qat} passos/época)")

qat_model = tfmot.quantization.keras.quantize_model(base_model)
qat_model.compile(optimizer=tf.keras.optimizers.Adam(learning_rate=5e-5, clipnorm=1.0), loss=ctc_loss)

history_qat = qat_model.fit(
    dataset_treino_qat, validation_data=dataset_val, epochs=EPOCAS_QAT, steps_per_epoch=passos_qat,
    callbacks=[
        AcuraciaSequenciaCallback(dataset_val),
        tf.keras.callbacks.ReduceLROnPlateau(monitor='val_loss', factor=0.5, patience=15, min_lr=1e-6, verbose=1),
        tf.keras.callbacks.EarlyStopping(monitor='val_loss', patience=30, restore_best_weights=True)
    ]
)

# ==========================================
# 8. EXPORTAÇÃO DO HISTÓRICO E AVALIAÇÃO DO MODELO QAT
# ==========================================
print("\n-> Exportando métricas de treino para CSV...")
df_historico = pd.concat([
    pd.DataFrame(history_float.history).assign(fase='float'),
    pd.DataFrame(history_qat.history).assign(fase='qat')
], ignore_index=True)
df_historico.to_csv(os.path.join(DIR_CSVS, f"historico_treino{SUFIXO_SAIDA}.csv"), index_label="Epoca")

print("\n-> Avaliação do modelo QAT na validação (imagens reais)...")
resultados_qat = avaliar(qat_model, dataset_val)
diagnosticar_colapso(resultados_qat)

nome_qat_h5 = f"modelo_digitos_qat{SUFIXO_SAIDA}.h5"
qat_model.save(os.path.join(DIR_SAIDA, nome_qat_h5))
shutil.copy(os.path.join(DIR_SAIDA, nome_qat_h5), os.path.join(DIR_BACKUPS, nome_qat_h5))

# ==========================================
# 9. CONVERSÃO PARA TFLITE INT8
# ==========================================
print("\n-> Convertendo para TFLite (INT8)...")
def representative_dataset():
    amostras_cal = ds_real_treino.shuffle(1000, seed=SEED).map(normalizar).batch(1).take(200)
    for img, _ in amostras_cal: yield [img.numpy()]

converter = tf.lite.TFLiteConverter.from_keras_model(qat_model)
converter.optimizations = [tf.lite.Optimize.DEFAULT]
converter.representative_dataset = representative_dataset
converter.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
converter.inference_input_type = tf.int8
converter.inference_output_type = tf.int8
tflite_model = converter.convert()

nome_qat_tflite = f"modelo_digitos_qat{SUFIXO_SAIDA}.tflite"
caminho_tflite = os.path.join(DIR_SAIDA, nome_qat_tflite)
with open(caminho_tflite, "wb") as f: f.write(tflite_model)
shutil.copy(caminho_tflite, os.path.join(DIR_BACKUPS, nome_qat_tflite))
print(f"-> Modelos (H5 e TFLite INT8) salvos em: {DIR_SAIDA} e copiados para: {DIR_BACKUPS}")

# ==========================================
# 10. VALIDAÇÃO DO .TFLITE
# ==========================================
print("\n-> Validando o .tflite INT8 na validação (imagens reais)...")
interpretador = tf.lite.Interpreter(model_content=tflite_model)
interpretador.allocate_tensors()
det_in, det_out = interpretador.get_input_details()[0], interpretador.get_output_details()[0]
escala_in, zero_in = det_in['quantization']
escala_out, zero_out = det_out['quantization']

def prever_tflite(img):
    q = np.clip(np.round(img / escala_in + zero_in), -128, 127).astype(np.int8)
    interpretador.set_tensor(det_in['index'], q[np.newaxis, ...])
    interpretador.invoke()
    return decodificar_greedy((interpretador.get_tensor(det_out['index'])[0].astype(np.float32) - zero_out) * escala_out)

resultados_tflite = []
for x, y in dataset_val:
    for img, r in zip(x.numpy(), y.numpy()):
        real = [int(v) for v in r if v != PAD]
        resultados_tflite.append((real, prever_tflite(img)))

print(f"   Sequência completa correta (TFLite INT8): {acuracia_sequencia(resultados_tflite) * 100:.2f}%")