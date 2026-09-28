import numpy as np
import tensorflow as tf
from pathlib import Path
from PIL import Image

MODEL_PATH = "modelo_ocr.keras"  # Seu modelo salvo
IMAGE_PATH = str(Path(__file__).resolve().parent / 'num_dataset' / '1'/ 'img002-001.png')
IMAGE_PATH_TO_DIVIDE = str(Path(__file__).resolve().parent / 'sintetico_97202.jpg')
CHUNK_IMAGE = 6

IMG_WIDTH = 24
IMG_HEIGHT = 48

IMG_WIDTH = 64
IMG_HEIGHT = 64
VOCAB = "0123456789"  # Vocabulário das classes


def divide_image_pil(img_path):
    imgs = []
    pil_img = Image.open(img_path).convert("L")
    width, height = pil_img.size
    step_x = width / CHUNK_IMAGE
    for i in range(CHUNK_IMAGE):
        left = int(i * step_x)
        top = 0
        right = int((i + 1) * step_x) if i < 5 else width  # Garante que pega até o último pixel
        bottom = height
        crop_pil = pil_img.crop((left, top, right, bottom))
        crop_pil.save(f'img_{i}.jpg')
        crop_np = np.array(crop_pil, dtype=np.uint8)
        crop_tensor = tf.expand_dims(crop_np, axis=-1)
        crop_tensor = tf.image.convert_image_dtype(crop_tensor, tf.float32)
        crop_tensor = tf.image.resize(crop_tensor, [IMG_HEIGHT, IMG_WIDTH])
        crop_tensor = tf.expand_dims(crop_tensor, axis=0)
        imgs.append(crop_tensor)
    return imgs

def process_image(img_path):
    img = tf.io.read_file(img_path)
    img = tf.io.decode_image(img, channels=1, expand_animations=False)
    img = tf.image.convert_image_dtype(img, tf.float32)
    img = tf.image.resize(img, [IMG_HEIGHT, IMG_WIDTH])
    img = tf.expand_dims(img, axis=0)
    return img

model = tf.keras.models.load_model(MODEL_PATH)

# img_tensor = process_image(IMAGE_PATH)
# predictions = model.predict(img_tensor)
# predicted_index = np.argmax(predictions[0])
# confidence = predictions[0][predicted_index] * 100
# predicted_char = VOCAB[predicted_index]

# print(f"\n--- Resultado da Predição ---")
# print(f"Caractere reconhecido: '{predicted_char}'")
# print(f"Confiança: {confidence:.2f}%")

texto_reconhecido = ""

# Fazer a predição para cada uma das 6 partes
for idx, tensor_img in enumerate(divide_image_pil(IMAGE_PATH_TO_DIVIDE)):
    preds = model.predict(tensor_img, verbose=0)
    classe = np.argmax(preds[0])
    caractere = VOCAB[classe]
    texto_reconhecido += caractere
    confianca = preds[0][classe] * 100
    print(f"Parte {idx + 1}: Caractere '{caractere}' (Confiança: {confianca:.1f}%)")

print(f"\nResultado final reconstruído: {texto_reconhecido}")