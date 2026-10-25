import os
from pathlib import Path
import numpy as np
import tensorflow as tf
from ai_edge_litert.compiled_model import CompiledModel, HardwareAccelerator
from tensorflow.keras.utils import img_to_array, load_img
from PIL import Image

PROJECT_PATH = Path(__file__).resolve().parent.parent

# Configurações do modelo TFLite de Segmentação
IMG_HEIGHT, IMG_WIDTH = 384, 384         # Dimensão Imagens Dataset - Máscara
CROP_WIDTH, CROP_HEIGHT = 68, 68        # Dimensões de cada pedaço cortado
# Configurações do modelo OCR
CHUNK_IMAGE = 6
VOCAB = "0123456789"

# Carrega o modelo TFLite quantizado (INT8)
model_path = str(PROJECT_PATH / "models" / "modelo_medidor.tflite")
model = CompiledModel.from_file(model_path, HardwareAccelerator.CPU)

# Carrega o modelo OCR Keras fora do loop
ocr_model_path = PROJECT_PATH / "models" / "modelo_ocr.keras"
model_ocr = tf.keras.models.load_model(str(ocr_model_path))

input_buffers = model.create_input_buffers(0)
output_buffers = model.create_output_buffers(0)


def process_image(img_path):
    img = (
        img_to_array(
            load_img(
                img_path,
                color_mode="grayscale",
                target_size=(IMG_HEIGHT, IMG_WIDTH),
            )
        )
        / 255.0
    )
    img_int8 = (img * 255.0 - 128.0).astype(np.int8)
    img_batch = np.expand_dims(img_int8, axis=0)
    return np.ascontiguousarray(img_batch, dtype=np.int8)


def divide_image_pil(img: Image.Image):
    imgs = []

    # 1. Pré-processamento e Redimensionamento Global
    pil_img = img.convert("L")
    pil_img.save("imagem_pre_cortada_redimensionada.jpg")
    width, height = pil_img.size
    step_x = width / CHUNK_IMAGE

    # Margem extra de 3 pixels para cada pedaço
    chunk_margin = 2

    # 2. Divisão e padronização dos cortes com margem
    for i in range(CHUNK_IMAGE):
        # Limites base sem margem
        base_left = int(i * step_x)
        base_right = int((i + 1) * step_x) if i < (CHUNK_IMAGE - 1) else width

        # Aplica a margem de 3px garantindo que permaneça dentro dos limites da imagem
        left = max(0, base_left - chunk_margin)
        top = 0  # Se desejar margem vertical também: max(0, 0 - chunk_margin)
        right = min(width, base_right + chunk_margin)
        bottom = height  # Se desejar margem vertical também: min(height, height + chunk_margin)

        # Faz o corte do trecho expandido
        crop_pil = pil_img.crop((left, top, right, bottom))

        # Redimensiona cada pedaço especificamente para CROP_WIDTH x CROP_HEIGHT (68x68 px)
        crop_pil = crop_pil.resize(
            (CROP_WIDTH, CROP_HEIGHT), Image.Resampling.BILINEAR
        )
        crop_pil.save(f"img_{i}.jpg")

        # Converte para Tensor (1, 68, 68, 1) com valores entre 0.0 e 1.0
        crop_np = np.array(crop_pil, dtype=np.uint8)
        crop_tensor = tf.expand_dims(crop_np, axis=-1)
        crop_tensor = tf.image.convert_image_dtype(crop_tensor, tf.float32)
        crop_tensor = tf.expand_dims(crop_tensor, axis=0)

        imgs.append(crop_tensor)

    return imgs

output_dir = PROJECT_PATH / "output_dataset"
output_dir.mkdir(exist_ok=True)
dataset_path = PROJECT_PATH / "metering_dataset"

for img_name in os.listdir(dataset_path):
    if not img_name.lower().endswith((".png", ".jpg", ".jpeg")):
        continue

    img_abs_path = str(dataset_path / img_name)
    input_data = process_image(img_abs_path)
    
    # Execução da segmentação
    input_buffers[0].write(input_data)
    model.run_by_index(0, input_buffers, output_buffers)
    output_raw = output_buffers[0].read(IMG_HEIGHT * IMG_WIDTH * 1, np.int8)
    output_image = output_raw.reshape((IMG_HEIGHT, IMG_WIDTH, 1))
    
    # Pós-processamento da máscara
    mask_binary = np.where(output_image > 0, 255, 0).astype(np.uint8)

    orig_img_bytes = tf.io.read_file(img_abs_path)
    orig_img = tf.io.decode_image(orig_img_bytes, channels=1)
    orig_img_np = orig_img.numpy()  # Formato (H_orig, W_orig, 1)

    orig_h, orig_w = orig_img_np.shape[:2]
    mask_resized = tf.image.resize(
        mask_binary, 
        [orig_h, orig_w], 
        method="nearest"
    ).numpy()

    pontos = np.where(mask_resized > 0)
    if len(pontos[0]) > 0:
        # Folga (padding) em pixels para expandir o corte
        margin = 7

        # Pega os limites do bounding box e aplica a margem
        ymin = max(0, np.min(pontos[0]) - margin)
        ymax = min(orig_h, np.max(pontos[0]) + 1 + margin)
        xmin = max(0, np.min(pontos[1]) - margin)
        xmax = min(orig_w, np.max(pontos[1]) + 1 + margin)
        
        # Extrai a ROI cortada com a nova área expandida
        crop_np = orig_img_np[ymin:ymax, xmin:xmax]
        if crop_np.ndim == 3 and crop_np.shape[-1] == 1:
            crop_np = crop_np.squeeze(axis=-1)

        # Converte para PIL Image para passar para divide_image_pil
        crop_pil = Image.fromarray(crop_np)

        texto_reconhecido = ""
        for idx, tensor_img in enumerate(divide_image_pil(crop_pil)):
            preds = model_ocr.predict(tensor_img, verbose=0)
            classe = np.argmax(preds[0])
            caractere = VOCAB[classe]
            texto_reconhecido += caractere
            confianca = preds[0][classe] * 100
            print(f"Parte {idx + 1}: Caractere '{caractere}' (Confiança: {confianca:.1f}%)")

        print(f"\nResultado final reconstruído: {texto_reconhecido}")

    break