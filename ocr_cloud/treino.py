import os
from pathlib import Path
import numpy as np
import tensorflow as tf
from tensorflow import keras, io
from tensorflow.keras import layers

# --- 1. PARÂMETROS E CONFIGURAÇÕES ---
IMG_WIDTH = 64
IMG_HEIGHT = 64
VOCAB = "0123456789"  # Suas 10 classes

# Mapeamento do caractere para o número da classe (0 a 9)
char_to_num = layers.StringLookup(
    vocabulary=list(VOCAB), 
    mask_token=None, 
    oov_token=None,
    num_oov_indices=0
)

# --- 2. CONSTRUÇÃO DO MODELO CNN SIMPLES ---
def build_single_char_model():
    inputs = layers.Input(shape=(IMG_HEIGHT, IMG_WIDTH, 1), name="image")

    # Extração de Características
    x = layers.Conv2D(32, (3, 3), activation="relu", padding="same")(inputs)
    x = layers.MaxPooling2D((2, 2))(x)
    
    x = layers.Conv2D(64, (3, 3), activation="relu", padding="same")(x)
    x = layers.MaxPooling2D((2, 2))(x)
    
    x = layers.Conv2D(128, (3, 3), activation="relu", padding="same")(x)
    x = layers.MaxPooling2D((2, 2))(x)

    # Classificação
    x = layers.Flatten()(x)
    x = layers.Dense(128, activation="relu")(x)
    x = layers.Dropout(0.3)(x)
    
    # Camada de saída com 10 classes e Softmax
    outputs = layers.Dense(len(VOCAB), activation="softmax", name="classification")(x)

    model = keras.models.Model(inputs=inputs, outputs=outputs, name="single_char_cnn")
    
    # Compilação clássica de classificação
    model.compile(
        optimizer="adam",
        loss="sparse_categorical_crossentropy",
        metrics=["accuracy"]
    )
    return model

# --- 3. PRÉ-PROCESSAMENTO DAS IMAGENS ---
def encode_single_sample(img_path: str):
    label_char = tf.strings.split(img_path, os.sep)[-2]    
    
    img = io.read_file(img_path)
    img = tf.io.decode_image(img, channels=1, expand_animations=False)
    img = tf.image.convert_image_dtype(img, tf.float32)
    img = tf.image.resize(img, [IMG_HEIGHT, IMG_WIDTH])
    
    # Converte o caractere do nome para o índice numérico da classe (0, 1, 2...)
    label = char_to_num(label_char)
    return img, label

# --- 4. CARREGAMENTO DOS DADOS ---
path_file = Path(__file__).resolve().parent
dataset_dir = path_file / 'num_dataset'

imgs_paths = []
for paste in os.listdir(dataset_dir):
    pasta_path = dataset_dir / paste
    if pasta_path.is_dir():
        for nm_file_img in os.listdir(pasta_path):
            imgs_paths.append(str(pasta_path / nm_file_img))

np.random.seed(42)
np.random.shuffle(imgs_paths)

split_idx = int(0.8 * len(imgs_paths))
train_paths = imgs_paths[:split_idx]
val_paths = imgs_paths[split_idx:]
train_ds = tf.data.Dataset.from_tensor_slices(train_paths)
val_ds = tf.data.Dataset.from_tensor_slices(val_paths)

train_ds = train_ds.map(encode_single_sample, num_parallel_calls=tf.data.AUTOTUNE)
val_ds = val_ds.map(encode_single_sample, num_parallel_calls=tf.data.AUTOTUNE)

BATCH_SIZE = 32

# Como cada imagem tem exatamente 1 rótulo, usa-se batch simples (sem padded_batch)
train_ds = train_ds.batch(BATCH_SIZE).prefetch(buffer_size=tf.data.AUTOTUNE)
val_ds = val_ds.batch(BATCH_SIZE).prefetch(buffer_size=tf.data.AUTOTUNE)

# --- 5. TREINAMENTO ---
model = build_single_char_model()
model.summary()

model.fit(
    train_ds,
    validation_data=val_ds,
    epochs=20
)

# Salvar modelo pronto para uso
model.save('modelo_ocr.keras')
