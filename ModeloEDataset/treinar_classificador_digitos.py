import os
import numpy as np
import tensorflow as tf
from tensorflow.keras import layers, models

DIRETORIO_ATUAL = os.path.dirname(os.path.abspath(__file__))
DIR_DIGITS = os.path.join(DIRETORIO_ATUAL, "dataset", "digits")
DIR_DOMINIO = os.path.join(DIRETORIO_ATUAL, "dataset", "digits_domain")
IMG_SIZE = (28, 28)
SEED = 42

# A Fase B (fine-tuning com fotos reais da ESP32CAM) so compensava quando o
# modelo base era fraco (com o dataset pequeno pre-Dryad ela piorava tudo).
# Com o modelo atual (Kaggle+Dryad, ~58k crops) testei 3 intensidades e o
# fine-tuning agora ajuda bastante no dominio real por um custo pequeno na
# acuracia geral -- ver historico do commit/conversa pros numeros.
EXECUTAR_FASE_B = True

# ==========================================
# 1. DATASETS
# ==========================================
print("-> Carregando dataset principal (Kaggle + Dryad)")
BATCH_SIZE = 128
ds_train = tf.keras.utils.image_dataset_from_directory(
    DIR_DIGITS, labels="inferred", label_mode="int", color_mode="grayscale",
    image_size=IMG_SIZE, batch_size=BATCH_SIZE, validation_split=0.15, subset="training",
    seed=SEED, shuffle=True,
)
ds_val = tf.keras.utils.image_dataset_from_directory(
    DIR_DIGITS, labels="inferred", label_mode="int", color_mode="grayscale",
    image_size=IMG_SIZE, batch_size=BATCH_SIZE, validation_split=0.15, subset="validation",
    seed=SEED, shuffle=False,
)
classes = ds_train.class_names
print("Classes:", classes)

# pesos de classe (digito '0' aparece mais por causa do zero-padding);
# limita o peso maximo pra nao deixar uma classe rara dominar demais o
# gradiente quando o dataset ja e grande (Kaggle + Dryad).
contagens = [len(os.listdir(os.path.join(DIR_DIGITS, c))) for c in classes]
print("Contagem por classe:", dict(zip(classes, contagens)))
total = sum(contagens)
class_weight_bruto = {i: total / (len(classes) * c) for i, c in enumerate(contagens)}
peso_max = 3.0
class_weight = {i: min(w, peso_max) for i, w in class_weight_bruto.items()}
print("Class weight:", {classes[i]: round(w, 2) for i, w in class_weight.items()})

NORM = layers.Rescaling(1.0 / 255)


def preparar(ds, treino):
    ds = ds.map(lambda x, y: (NORM(x), y), num_parallel_calls=tf.data.AUTOTUNE)
    return ds.prefetch(tf.data.AUTOTUNE)


ds_train = preparar(ds_train, True)
ds_val = preparar(ds_val, False)

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

# ==========================================
# 4. FASE A - treino principal (dataset Kaggle)
# ==========================================
print("\n-> Fase A: treino principal")
parada_antecipada = tf.keras.callbacks.EarlyStopping(
    monitor="val_loss", patience=10, restore_best_weights=True)
historico_a = modelo.fit(
    ds_train_aug, validation_data=ds_val, epochs=60,
    class_weight=class_weight, callbacks=[parada_antecipada], verbose=2,
)
acc_a = max(historico_a.history["val_accuracy"])
print(f"Fase A - melhor val_accuracy: {acc_a:.4f}")

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

    return ds.map(remapear).map(lambda x, y: (NORM(x), y))


TEM_DOMINIO = os.path.isdir(DIR_DOMINIO) and any(os.scandir(DIR_DOMINIO))

# ==========================================
# 5. FASE B - fine-tuning de dominio (fotos reais da ESP32CAM)
# ==========================================
if EXECUTAR_FASE_B and TEM_DOMINIO:
    print("\n-> Fase B: fine-tuning de dominio (ESP32CAM real)")
    ds_dominio = carregar_dominio()
    ds_dominio_aug = ds_dominio.map(lambda x, y: (augmentacao(x, training=True), y))
    # repete bastante (poucas fotos reais) + junta uma fatia do treino
    # principal pra nao esquecer o que aprendeu (catastrophic forgetting)
    ds_dominio_aug = ds_dominio_aug.repeat(8)
    ds_reforco = ds_train.take(150)
    ds_fine = ds_dominio_aug.concatenate(ds_reforco).shuffle(600)

    modelo.optimizer.learning_rate.assign(5e-5)
    historico_b = modelo.fit(ds_fine, validation_data=ds_val, epochs=5, verbose=2)
    acc_b = historico_b.history["val_accuracy"][-1]
    print(f"Fase B - val_accuracy (dataset principal) apos fine-tuning: {acc_b:.4f}")
else:
    print("\n-> Fase B pulada (EXECUTAR_FASE_B=False ou dataset/digits_domain vazio)")

# ==========================================
# 6. SALVA MODELO FLOAT
# ==========================================
modelo.save(os.path.join(DIRETORIO_ATUAL, "modelo_digito.h5"))
print("\n-> modelo_digito.h5 salvo")

# ==========================================
# 7. CONVERSAO E QUANTIZACAO INT8
# (o TFLiteConverter fixa a dimensao de batch em 1 automaticamente, que e o
# que o TFLite Micro precisa; nao ha necessidade de reconstruir o modelo
# com batch_shape estatico. TFLiteConverter.from_keras_model trava com um
# erro do MLIR nesta combinacao de TF/Keras -- exportar como SavedModel e
# converter a partir dele contorna o problema.)
# ==========================================
modelo_estatico = modelo
CAMINHO_SAVEDMODEL = os.path.join(DIRETORIO_ATUAL, "_savedmodel_digito")
modelo_estatico.export(CAMINHO_SAVEDMODEL)
print("\n-> Convertendo para INT8")
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

caminho_tflite = os.path.join(DIRETORIO_ATUAL, "modelo_digito.tflite")
with open(caminho_tflite, "wb") as f:
    f.write(tflite_modelo)
print(f"-> {caminho_tflite} gerado ({len(tflite_modelo) / 1024:.1f} KB)")

# ==========================================
# 9. VALIDACAO DO MODELO INT8 NO PC (antes de qualquer hardware)
# ==========================================
print("\n-> Validando modelo INT8 (tf.lite.Interpreter, no PC)")
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
    print(f"Acuracia INT8 em {nome}: {acertos / max(totais,1):.4f} ({acertos}/{totais})")


avaliar_int8(ds_val, "validacao (Kaggle)")
if TEM_DOMINIO:
    avaliar_int8(carregar_dominio(), "dominio (ESP32CAM real)")

# ==========================================
# 10. ORCAMENTO DE MEMORIA - comparacao com o modelo de segmentacao atual
# ==========================================
caminho_segmentacao = os.path.join(DIRETORIO_ATUAL, "modelo_esp32.tflite")
if os.path.exists(caminho_segmentacao):
    tam_seg = os.path.getsize(caminho_segmentacao) / 1024
    print(f"\nComparacao de tamanho: modelo_digito.tflite = {len(tflite_modelo)/1024:.1f} KB "
          f"| modelo_esp32.tflite (segmentacao) = {tam_seg:.1f} KB")

print(f"\nParametros do classificador: {modelo_estatico.count_params()}")
