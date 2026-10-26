import argparse
import json
import os
import sys
import time

import numpy as np
import tensorflow as tf
from tensorflow.keras import layers, models

from divisao_por_foto import dividir_por_foto

DIRETORIO_ATUAL = os.path.dirname(os.path.abspath(__file__))

ap = argparse.ArgumentParser(description="Treina o classificador de dígito (28x28) e gera o .tflite INT8.")
ap.add_argument("--saida", default=DIRETORIO_ATUAL, help="pasta onde ficam modelos/ e relatorios/")
ap.add_argument("--epocas", type=int, default=60, help="máximo de épocas da Fase A (há parada antecipada)")
ap.add_argument("--sem-fase-b", action="store_true", help="não faz o fine-tuning com as fotos da ESP32-CAM")
args = ap.parse_args()

DIR_DIGITS = os.path.join(DIRETORIO_ATUAL, "dataset", "digits")
DIR_DOMINIO = os.path.join(DIRETORIO_ATUAL, "dataset", "digits_domain")
DIR_MODELOS = os.path.join(args.saida, "modelos")
DIR_RELATORIOS = os.path.join(args.saida, "relatorios")
os.makedirs(DIR_MODELOS, exist_ok=True)
os.makedirs(DIR_RELATORIOS, exist_ok=True)
IMG_SIZE = (28, 28)
SEED = 42
BATCH_SIZE = 128


class Tee:
    """Espelha o que vai para o console em relatorios/treino_classificador.log."""

    def __init__(self, *fluxos):
        self.fluxos = fluxos

    def write(self, texto):
        for f in self.fluxos:
            f.write(texto)
            f.flush()

    def flush(self):
        for f in self.fluxos:
            f.flush()


_log = open(os.path.join(DIR_RELATORIOS, "treino_classificador.log"), "w", encoding="utf-8")
sys.stdout = Tee(sys.__stdout__, _log)
T_INICIO = time.time()


def tempo():
    s = int(time.time() - T_INICIO)
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


tf.keras.utils.set_random_seed(SEED)

# A Fase B (fine-tuning com fotos reais da ESP32CAM) so compensava quando o
# modelo base era fraco (com o dataset pequeno pre-Dryad ela piorava tudo).
# Com o modelo atual (Kaggle+Dryad, ~58k crops) ela ajuda no dominio real por
# um custo pequeno na acuracia geral. `--sem-fase-b` gera o modelo so com a Fase A
# para comparar os dois no teste independente (ocr/avaliar_teste_publico.py).
EXECUTAR_FASE_B = not args.sem_fase_b

# ==========================================
# 1. DATASETS
# ==========================================
# Validacao dividida POR FOTO (ver divisao_por_foto.py). O Dryad `test` NAO entra aqui: fica fora de
# dataset/digits/ e so e usado na avaliacao final (ocr/avaliar_teste_publico.py).
print(f"[{tempo()}] -> Carregando dataset principal (Kaggle + Dryad train)", flush=True)
classes, itens_treino, itens_val = dividir_por_foto(
    DIR_DIGITS, seed=SEED, fracao_val=0.15,
    caminho_csv=os.path.join(DIR_RELATORIOS, "split_classificador.csv"))
print(f"Classes: {classes}")
print(f"Recortes: treino={len(itens_treino)} validacao={len(itens_val)} (divisao por foto, seed={SEED})", flush=True)


def carregar(caminho, rotulo):
    img = tf.io.decode_png(tf.io.read_file(caminho), channels=1)
    img = tf.ensure_shape(tf.cast(img, tf.float32), (IMG_SIZE[0], IMG_SIZE[1], 1))
    return img / 255.0, rotulo


def montar(itens, embaralhar):
    caminhos = tf.constant([c for c, _ in itens])
    rotulos = tf.constant([r for _, r in itens], dtype=tf.int32)
    ds = tf.data.Dataset.from_tensor_slices((caminhos, rotulos))
    if embaralhar:
        ds = ds.shuffle(len(itens), seed=SEED, reshuffle_each_iteration=True)
    ds = ds.map(carregar, num_parallel_calls=tf.data.AUTOTUNE)
    return ds.batch(BATCH_SIZE).prefetch(tf.data.AUTOTUNE)


ds_train = montar(itens_treino, True)
ds_val = montar(itens_val, False)
PASSOS_POR_EPOCA = int(np.ceil(len(itens_treino) / BATCH_SIZE))

# pesos de classe (digito '0' aparece mais por causa do zero-padding);
# limita o peso maximo pra nao deixar uma classe rara dominar demais o
# gradiente quando o dataset ja e grande (Kaggle + Dryad).
contagens = np.bincount([r for _, r in itens_treino], minlength=len(classes))
print("Contagem por classe (treino):", dict(zip(classes, contagens.tolist())))
total = int(contagens.sum())
peso_max = 3.0
class_weight = {i: min(total / (len(classes) * int(c)), peso_max) for i, c in enumerate(contagens)}
print("Class weight:", {classes[i]: round(w, 2) for i, w in class_weight.items()}, flush=True)

# ==========================================
# 2. AUGMENTACAO (so no treino) simulando a camera do ESP32CAM: baixa
# resolucao nativa, ruido, blur leve, jitter de brilho/contraste, rotacao
# leve.
# ==========================================
def downsample_upsample(x):
    baixa = tf.image.resize(x, (18, 18), method="bilinear")
    return tf.image.resize(baixa, IMG_SIZE, method="bilinear")


augmentacao = models.Sequential([
    layers.RandomRotation(0.035, fill_mode="constant", fill_value=1.0),
    layers.RandomTranslation(0.04, 0.04, fill_mode="constant", fill_value=1.0),
    layers.RandomContrast(0.15),
    layers.GaussianNoise(0.02),
    layers.Lambda(downsample_upsample),
], name="augmentacao_camera")


def com_augmentacao(ds):
    return ds.map(lambda x, y: (augmentacao(x, training=True), y), num_parallel_calls=tf.data.AUTOTUNE)


ds_train_aug = com_augmentacao(ds_train)

# ==========================================
# 3. ARQUITETURA (CNN maior agora que ha bastante dado real - Dryad -
# pra sustentar mais capacidade sem overfitar. Ainda pequena pro padrao de
# CNNs (~60k parametros, dezenas de KB em int8), bem abaixo do orcamento de
# memoria de um ESP32CAM.)
# ==========================================
def construir_modelo(batch_shape=None, input_shape=None):
    if batch_shape is not None:
        inputs = layers.Input(batch_shape=batch_shape)
    else:
        inputs = layers.Input(shape=input_shape)
    x = layers.Conv2D(16, 3, activation="relu", padding="same")(inputs)
    x = layers.Conv2D(16, 3, activation="relu", padding="same")(x)
    x = layers.MaxPooling2D(2)(x)
    x = layers.Conv2D(32, 3, activation="relu", padding="same")(x)
    x = layers.Conv2D(32, 3, activation="relu", padding="same")(x)
    x = layers.MaxPooling2D(2)(x)
    x = layers.Conv2D(64, 3, activation="relu", padding="same")(x)
    x = layers.MaxPooling2D(2)(x)
    x = layers.Flatten()(x)
    x = layers.Dense(64, activation="relu")(x)
    x = layers.Dropout(0.3)(x)
    outputs = layers.Dense(10, activation="softmax")(x)
    return models.Model(inputs, outputs)


modelo = construir_modelo(input_shape=(28, 28, 1))
modelo.compile(optimizer=tf.keras.optimizers.Adam(5e-4),
               loss="sparse_categorical_crossentropy", metrics=["accuracy"])
modelo.summary()


class Progresso(tf.keras.callbacks.Callback):
    """Uma linha por época (com tempo e estimativa) e uma a cada `a_cada` passos, no console e no .log."""

    def __init__(self, rotulo, passos, a_cada=100):
        super().__init__()
        self.rotulo, self.passos, self.a_cada = rotulo, passos, a_cada

    def on_train_begin(self, logs=None):
        self.t0 = time.time()
        self.epoca = 0

    def on_epoch_begin(self, epoch, logs=None):
        self.epoca = epoch
        self.t_epoca = time.time()

    def on_train_batch_end(self, batch, logs=None):
        if (batch + 1) % self.a_cada == 0:
            print(f"[{tempo()}]   {self.rotulo} época {self.epoca + 1}: passo {batch + 1}/{self.passos} "
                  f"loss={logs['loss']:.4f} acc={logs['accuracy']:.4f}", flush=True)

    def on_epoch_end(self, epoch, logs=None):
        feitas, totais = epoch + 1, self.params["epochs"]
        dur = time.time() - self.t_epoca
        restante = (time.time() - self.t0) / feitas * (totais - feitas)
        print(f"[{tempo()}] {self.rotulo} época {feitas}/{totais} ({dur:.0f}s) "
              f"loss={logs['loss']:.4f} acc={logs['accuracy']:.4f} "
              f"val_loss={logs['val_loss']:.4f} val_acc={logs['val_accuracy']:.4f} "
              f"| no máximo mais ~{restante / 60:.0f} min", flush=True)


# ==========================================
# 4. FASE A - treino principal (Kaggle + Dryad train)
# ==========================================
print(f"\n[{tempo()}] -> Fase A: treino principal (máx. {args.epocas} épocas, parada antecipada com paciência 10)", flush=True)
parada_antecipada = tf.keras.callbacks.EarlyStopping(
    monitor="val_loss", patience=10, restore_best_weights=True)
historico_a = modelo.fit(
    ds_train_aug, validation_data=ds_val, epochs=args.epocas,
    class_weight=class_weight, verbose=0,
    callbacks=[Progresso("Fase A", PASSOS_POR_EPOCA), parada_antecipada,
               tf.keras.callbacks.CSVLogger(os.path.join(DIR_RELATORIOS, "historico_treino_classificador.csv"))],
)
acc_a = max(historico_a.history["val_accuracy"])
epocas_a = len(historico_a.history["loss"])
loss_val_a, acc_val_a_final = modelo.evaluate(ds_val, verbose=0)  # pesos restaurados da melhor época
print(f"[{tempo()}] Fase A - {epocas_a} épocas; melhor val_accuracy: {acc_a:.4f}; "
      f"val_accuracy com os pesos restaurados: {acc_val_a_final:.4f}", flush=True)


def carregar_dominio():
    ds = tf.keras.utils.image_dataset_from_directory(
        DIR_DOMINIO, labels="inferred", label_mode="int", color_mode="grayscale",
        image_size=IMG_SIZE, batch_size=8, shuffle=True, seed=SEED,
    )
    # reindexa os rotulos do dataset de dominio para o mesmo indice de
    # classes do dataset principal (nomes de classe identicos "0".."9", mas
    # o dataset de dominio pode nao conter todas as 10 pastas)
    mapa_dominio_para_principal = [classes.index(c) for c in ds.class_names]

    def remapear(x, y):
        tabela = tf.constant(mapa_dominio_para_principal, dtype=tf.int64)
        return x, tf.cast(tf.gather(tabela, y), tf.int32)

    return ds.map(remapear).map(lambda x, y: (x / 255.0, y))


TEM_DOMINIO = os.path.isdir(DIR_DOMINIO) and any(os.scandir(DIR_DOMINIO))

# ==========================================
# 5. FASE B - fine-tuning de dominio (fotos reais da ESP32CAM)
# ==========================================
acc_val_b = None
if EXECUTAR_FASE_B and TEM_DOMINIO:
    print(f"\n[{tempo()}] -> Fase B: fine-tuning de dominio (ESP32CAM real)", flush=True)
    ds_dominio = carregar_dominio()
    ds_dominio_aug = ds_dominio.map(lambda x, y: (augmentacao(x, training=True), y))
    # repete bastante (poucas fotos reais) + junta uma fatia do treino
    # principal pra nao esquecer o que aprendeu (catastrophic forgetting)
    ds_dominio_aug = ds_dominio_aug.repeat(8)
    ds_reforco = ds_train.take(150)
    ds_fine = ds_dominio_aug.concatenate(ds_reforco).shuffle(600)

    modelo.optimizer.learning_rate.assign(5e-5)
    historico_b = modelo.fit(ds_fine, validation_data=ds_val, epochs=5, verbose=0,
                             callbacks=[Progresso("Fase B", 150 + 24, a_cada=50)])
    acc_val_b = historico_b.history["val_accuracy"][-1]
    print(f"[{tempo()}] Fase B - val_accuracy (dataset principal) apos fine-tuning: {acc_val_b:.4f}", flush=True)
else:
    print(f"\n[{tempo()}] -> Fase B pulada (--sem-fase-b ou dataset/digits_domain vazio)", flush=True)

# ==========================================
# 6. SALVA MODELO FLOAT
# ==========================================
modelo.save(os.path.join(DIR_MODELOS, "modelo_digito.h5"))
print(f"\n[{tempo()}] -> modelo_digito.h5 salvo", flush=True)

# ==========================================
# 7. CONVERSAO E QUANTIZACAO INT8
# (o TFLiteConverter fixa a dimensao de batch em 1 automaticamente, que e o
# que o TFLite Micro precisa; nao ha necessidade de reconstruir o modelo
# com batch_shape estatico. TFLiteConverter.from_keras_model trava com um
# erro do MLIR nesta combinacao de TF/Keras -- exportar como SavedModel e
# converter a partir dele contorna o problema.)
# ==========================================
modelo_estatico = modelo
CAMINHO_SAVEDMODEL = os.path.join(args.saida, "_savedmodel_digito")
modelo_estatico.export(CAMINHO_SAVEDMODEL)
print(f"[{tempo()}] -> Convertendo para INT8", flush=True)
amostras_repr = np.concatenate([x.numpy() for x, _ in ds_train.take(20)], axis=0)


def representative_dataset():
    for i in range(min(300, len(amostras_repr))):
        yield [np.expand_dims(amostras_repr[i], axis=0).astype(np.float32)]


converter = tf.lite.TFLiteConverter.from_saved_model(CAMINHO_SAVEDMODEL)
converter.optimizations = [tf.lite.Optimize.DEFAULT]
converter.representative_dataset = representative_dataset
converter.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
converter.inference_input_type = tf.int8
converter.inference_output_type = tf.int8
tflite_modelo = converter.convert()

caminho_tflite = os.path.join(DIR_MODELOS, "modelo_digito.tflite")
with open(caminho_tflite, "wb") as f:
    f.write(tflite_modelo)
print(f"[{tempo()}] -> {caminho_tflite} gerado ({len(tflite_modelo) / 1024:.1f} KB)", flush=True)

# ==========================================
# 9. VALIDACAO DO MODELO INT8 NO PC (antes de qualquer hardware)
# ==========================================
print(f"\n[{tempo()}] -> Validando modelo INT8 (tf.lite.Interpreter, no PC)", flush=True)
interpretador = tf.lite.Interpreter(model_content=tflite_modelo)
interpretador.allocate_tensors()
entrada = interpretador.get_input_details()[0]
saida = interpretador.get_output_details()[0]
escala_in, zero_in = entrada["quantization"]


def prever_int8(imagem_float):
    imagem_int8 = np.round(imagem_float / escala_in + zero_in).astype(np.int8)
    interpretador.set_tensor(entrada["index"], imagem_int8)
    interpretador.invoke()
    return interpretador.get_tensor(saida["index"])[0]


def avaliar_int8(ds, nome):
    acertos, totais = 0, 0
    for xb, yb in ds:
        for img, rot in zip(xb.numpy(), yb.numpy()):
            pred = np.argmax(prever_int8(np.expand_dims(img, 0)))
            acertos += int(pred == rot)
            totais += 1
    print(f"[{tempo()}] Acuracia INT8 em {nome}: {acertos / max(totais, 1):.4f} ({acertos}/{totais})", flush=True)
    return acertos / max(totais, 1)


acc_int8_val = avaliar_int8(ds_val, "validacao (por foto)")
acc_int8_dominio = avaliar_int8(carregar_dominio(), "dominio (ESP32CAM real, ja visto no fine-tuning)") if TEM_DOMINIO else None

# ==========================================
# 10. ORCAMENTO DE MEMORIA - comparacao com o modelo de segmentacao atual
# ==========================================
caminho_segmentacao = os.path.join(DIR_MODELOS, "modelo_esp32.tflite")
if os.path.exists(caminho_segmentacao):
    tam_seg = os.path.getsize(caminho_segmentacao) / 1024
    print(f"\nComparacao de tamanho: modelo_digito.tflite = {len(tflite_modelo)/1024:.1f} KB "
          f"| modelo_esp32.tflite (segmentacao) = {tam_seg:.1f} KB")

print(f"\nParametros do classificador: {modelo_estatico.count_params()}")

with open(os.path.join(DIR_RELATORIOS, "treino_classificador.json"), "w", encoding="utf-8") as f:
    json.dump({
        "seed": SEED, "divisao": "por foto (15 % das fotos para validacao)",
        "recortes_treino": len(itens_treino), "recortes_validacao": len(itens_val),
        "fase_a_epocas": epocas_a, "fase_a_val_accuracy_float": round(float(acc_val_a_final), 4),
        "fase_b_executada": bool(EXECUTAR_FASE_B and TEM_DOMINIO),
        "fase_b_val_accuracy_float": None if acc_val_b is None else round(float(acc_val_b), 4),
        "int8_val_accuracy": round(float(acc_int8_val), 4),
        "int8_dominio_accuracy_ja_visto": None if acc_int8_dominio is None else round(float(acc_int8_dominio), 4),
        "tflite_kb": round(len(tflite_modelo) / 1024, 1), "parametros": int(modelo_estatico.count_params()),
        "duracao_s": int(time.time() - T_INICIO),
    }, f, indent=2, ensure_ascii=False)
print(f"[{tempo()}] FIM", flush=True)
