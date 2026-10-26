import argparse
import csv
import json
import os
import sys
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
ap.add_argument("--epocas", type=int, default=600, help="máximo de épocas (há parada antecipada no Dice de validação)")
ap.add_argument("--lote", type=int, default=16, help="tamanho do lote do treino")
ap.add_argument("--paciencia", type=int, default=60, help="épocas sem melhorar o Dice de validação antes de parar")
ap.add_argument("--perda", choices=["bce", "bce_dice"], default="bce_dice",
                help="bce_dice soma a entropia cruzada e 1 - Dice suave: a janela ocupa poucos pixels e só a entropia "
                     "cruzada fica no platô de 'tudo fundo' por centenas de épocas")
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

os.makedirs(DIR_RELATORIOS, exist_ok=True)


class Tee:
    """Espelha o que vai para o console em relatorios/treino_segmentacao.log."""

    def __init__(self, *fluxos):
        self.fluxos = fluxos

    def write(self, texto):
        for f in self.fluxos:
            f.write(texto)
            f.flush()

    def flush(self):
        for f in self.fluxos:
            f.flush()


_log = open(os.path.join(DIR_RELATORIOS, "treino_segmentacao.log"), "w", encoding="utf-8")
sys.stdout = Tee(sys.__stdout__, _log)
T_INICIO = time.time()


def tempo():
    s = int(time.time() - T_INICIO)
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


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
    """Dice por imagem (média do lote) com a saída binarizada em 0,5. O fundo domina a imagem, então
    a acurácia por pixel não diz se a janela foi achada; Dice e IoU olham só a região da janela."""
    p = tf.cast(y_pred > 0.5, tf.float32)
    inter = tf.reduce_sum(y_true * p, axis=[1, 2, 3])
    soma = tf.reduce_sum(y_true, axis=[1, 2, 3]) + tf.reduce_sum(p, axis=[1, 2, 3])
    return tf.reduce_mean(tf.math.divide_no_nan(2.0 * inter, soma))


def iou(y_true, y_pred):
    p = tf.cast(y_pred > 0.5, tf.float32)
    inter = tf.reduce_sum(y_true * p, axis=[1, 2, 3])
    uniao = tf.reduce_sum(y_true, axis=[1, 2, 3]) + tf.reduce_sum(p, axis=[1, 2, 3]) - inter
    return tf.reduce_mean(tf.math.divide_no_nan(inter, uniao))


def construir(batch_shape=None):
    """Mesma rede para o treino (lote livre) e para a conversão (lote fixo em 1, que é o que o ESP32 usa).
    O batch_shape estático garante tamanho fixo de tensores na memória do ESP32; treinar com ele obrigava
    batch_size=1, então o treino usa a versão de lote livre e os pesos são copiados para a estática."""
    if batch_shape is not None:
        inputs = layers.Input(batch_shape=batch_shape)
    else:
        inputs = layers.Input(shape=(IMG_SIZE[0], IMG_SIZE[1], 1))

    c1 = layers.Conv2D(8, (3, 3), activation='relu', padding='same')(inputs)
    p1 = layers.MaxPooling2D((2, 2))(c1)

    c2 = layers.Conv2D(16, (3, 3), activation='relu', padding='same')(p1)
    p2 = layers.MaxPooling2D((2, 2))(c2)

    u1 = layers.Conv2DTranspose(16, (3, 3), strides=(2, 2), padding='same', activation='relu')(p2)
    u2 = layers.Conv2DTranspose(8, (3, 3), strides=(2, 2), padding='same', activation='relu')(u1)

    outputs = layers.Conv2D(1, (1, 1), activation='sigmoid', padding='same')(u2)
    return models.Model(inputs=[inputs], outputs=[outputs])


def perda_bce_dice(y_true, y_pred):
    bce = tf.reduce_mean(tf.keras.losses.binary_crossentropy(y_true, y_pred))
    inter = tf.reduce_sum(y_true * y_pred, axis=[1, 2, 3])
    soma = tf.reduce_sum(y_true, axis=[1, 2, 3]) + tf.reduce_sum(y_pred, axis=[1, 2, 3])
    return bce + tf.reduce_mean(1.0 - (2.0 * inter + 1.0) / (soma + 1.0))


model = construir()
model.compile(optimizer='adam', loss=perda_bce_dice if args.perda == "bce_dice" else 'binary_crossentropy',
              metrics=['accuracy', dice, iou])


class Progresso(tf.keras.callbacks.Callback):
    """Uma linha a cada `a_cada` épocas (e na melhor até agora), com tempo decorrido e estimativa de fim."""

    def __init__(self, a_cada=5):
        super().__init__()
        self.a_cada = a_cada
        self.melhor = -1.0

    def on_train_begin(self, logs=None):
        self.t0 = time.time()

    def on_epoch_end(self, epoch, logs=None):
        feitas, totais = epoch + 1, self.params['epochs']
        melhorou = logs['val_dice'] > self.melhor
        self.melhor = max(self.melhor, logs['val_dice'])
        if feitas % self.a_cada == 0 or melhorou or feitas == totais:
            restante = (time.time() - self.t0) / feitas * (totais - feitas)
            print(f"[{tempo()}] época {feitas}/{totais} loss={logs['loss']:.4f} dice={logs['dice']:.4f} iou={logs['iou']:.4f} "
                  f"| val_loss={logs['val_loss']:.4f} val_dice={logs['val_dice']:.4f} val_iou={logs['val_iou']:.4f}"
                  f"{' *' if melhorou else ''} | no máximo mais ~{restante / 60:.0f} min", flush=True)


# ==========================================
# 4. TREINAMENTO
# ==========================================
# Antes: 10.000 épocas com batch_size=1 e a "acurácia" por pixel como métrica (o fundo domina a imagem e
# ela passava de 98 % sem a janela estar certa), sem parada antecipada nem histórico. Agora: lote de
# `--lote`, parada antecipada no Dice de validação (restaura a melhor época) e histórico por época no CSV.
print(f"\n[{tempo()}] -> Iniciando Treinamento (lote {args.lote}, máx. {args.epocas} épocas, paciência {args.paciencia})", flush=True)
os.makedirs(DIR_MODELOS, exist_ok=True)
historico = tf.keras.callbacks.CSVLogger(os.path.join(DIR_RELATORIOS, "historico_treino_segmentacao.csv"))
# start_from_epoch: no começo a rede prevê só fundo (Dice 0) por dezenas de épocas; sem essa folga a parada
# antecipada encerraria o treino antes de ele sair do platô.
parada = tf.keras.callbacks.EarlyStopping(monitor="val_dice", mode="max", patience=args.paciencia,
                                          restore_best_weights=True, start_from_epoch=100)
hist = model.fit(X_train, Y_train, validation_data=(X_val, Y_val), epochs=args.epocas, batch_size=args.lote,
                 verbose=0, callbacks=[Progresso(), historico, parada])
epocas_feitas = len(hist.history["loss"])
melhor_epoca = int(np.argmax(hist.history["val_dice"])) + 1
print(f"[{tempo()}] Treino parou na época {epocas_feitas}; melhor val_dice={max(hist.history['val_dice']):.4f} "
      f"(época {melhor_epoca}, pesos restaurados)", flush=True)

# a versão estática (lote 1) recebe os pesos treinados; é ela que vira .tflite
model_estatico = construir(batch_shape=(1, IMG_SIZE[0], IMG_SIZE[1], 1))
model_estatico.set_weights(model.get_weights())

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
model_estatico.export(CAMINHO_SAVEDMODEL)
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

resultado = {"n_teste": len(X_test), "seed": SEED, "lote": args.lote, "perda": args.perda, "epocas_executadas": epocas_feitas,
             "melhor_epoca": melhor_epoca,
             "float": media_dice_iou(prev_float), "int8": media_dice_iou(prev_int8),
             "mascara_vazia_int8": int(sum(not p.any() for p in prev_int8)),
             "duracao_s": int(time.time() - T_INICIO)}
with open(os.path.join(DIR_RELATORIOS, "segmentacao_teste.json"), "w", encoding="utf-8") as f:
    json.dump(resultado, f, indent=2)
print(json.dumps(resultado, indent=2))
