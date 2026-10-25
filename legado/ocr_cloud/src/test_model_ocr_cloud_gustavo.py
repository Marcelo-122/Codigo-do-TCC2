import os
from pathlib import Path
import cv2
import numpy as np
import tensorflow as tf
from ai_edge_litert.compiled_model import CompiledModel, HardwareAccelerator
from tensorflow.keras.utils import img_to_array, load_img
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'
os.environ['LITERT_LOG_LEVEL'] = 'ERROR'  # Ou 'FATAL' para silenciar tudo
PROJECT_PATH = Path(__file__).resolve().parent.parent

# ==========================================
# 1. CONFIGURAÇÕES DOS MODELOS
# ==========================================
# Segmentação (INT8)
SEG_IMG_HEIGHT, SEG_IMG_WIDTH = 384, 384

# OCR CTC (Float32) - Conforme script de treinamento
OCR_IMG_HEIGHT = 48
OCR_IMG_WIDTH = 224
BLANK_INDEX = 10  # BLANK na classe 10 (classes 0-9 para dígitos)

# ==========================================
# 2. CARREGAMENTO DOS MODELOS
# ==========================================
seg_model_path = str(PROJECT_PATH / "models" / "modelo_medidor.tflite")
model_seg = CompiledModel.from_file(seg_model_path, HardwareAccelerator.CPU)

ocr_model_path = str(PROJECT_PATH / "models" / "modelo_digitos_float_ctc_sint.tflite")
model_ocr = CompiledModel.from_file(ocr_model_path, HardwareAccelerator.CPU)

# Buffers independentes para evitar conflitos de execução
seg_input_buffers = model_seg.create_input_buffers(0)
seg_output_buffers = model_seg.create_output_buffers(0)

ocr_input_buffers = model_ocr.create_input_buffers(0)
ocr_output_buffers = model_ocr.create_output_buffers(0)

# ==========================================
# 3. FUNÇÕES AUXILIARES
# ==========================================
def process_seg_image(img_path):
    """Pré-processamento para o modelo de segmentação INT8."""
    img = img_to_array(load_img(
        img_path,
        color_mode="grayscale",
        target_size=(SEG_IMG_HEIGHT, SEG_IMG_WIDTH),
    )) / 255.0
    img_int8 = (img * 255.0 - 128.0).astype(np.int8)
    img_batch = np.expand_dims(img_int8, axis=0)
    return np.ascontiguousarray(img_batch, dtype=np.int8)

def preprocess_crop_for_ocr(crop_np):
    """
    Pré-processa a ROI (região do visor cortada) preservando a razão de aspecto
    com padding, idêntico à função `carregar` e `normalizar` do treinamento:
      - Resizing proporcional
      - Padding com zeros
      - Normalização [0.0, 1.0] float32
      - Formato final: (1, 48, 224, 1) float32
    """
    if crop_np.ndim == 2:
        crop_np = np.expand_dims(crop_np, axis=-1)

    h_orig, w_orig = crop_np.shape[:2]
    
    # Redimensionamento proporcional
    escala = min(float(OCR_IMG_HEIGHT) / h_orig, float(OCR_IMG_WIDTH) / w_orig)
    nova_h = max(1, int(round(h_orig * escala)))
    nova_w = max(1, int(round(w_orig * escala)))

    crop_resized = cv2.resize(crop_np, (nova_w, nova_h), interpolation=cv2.INTER_LINEAR)
    if crop_resized.ndim == 2:
        crop_resized = np.expand_dims(crop_resized, axis=-1)

    # Padding à direita e abaixo
    pad_h = OCR_IMG_HEIGHT - nova_h
    pad_w = OCR_IMG_WIDTH - nova_w
    crop_padded = np.pad(crop_resized, ((0, pad_h), (0, pad_w), (0, 0)), mode='constant', constant_values=0)

    # Normalização float32 (0.0 a 1.0)
    img_float = crop_padded.astype(np.float32) / 255.0
    img_batch = np.expand_dims(img_float, axis=0)
    
    return np.ascontiguousarray(img_batch, dtype=np.float32)

def ctc_greedy_decode(logits):
    """
    Decodificador Greedy para a saída do modelo CTC:
    1. Executa argmax no eixo das classes para obter o caminho de maior probabilidade.
    2. Agrupa repetições consecutivas.
    3. Remove o caractere em branco (BLANK_INDEX = 10).
    """
    ids = np.argmax(logits, axis=-1)  # Formato (TIMESTEPS,)
    saida = []
    anterior = BLANK_INDEX
    
    for i in ids:
        if i != anterior and i != BLANK_INDEX:
            saida.append(str(int(i)))
        anterior = i
        
    return ''.join(saida)

# ==========================================
# 4. EXECUÇÃO DO PIPELINE
# ==========================================
output_dir = PROJECT_PATH / "output_dataset"
output_dir.mkdir(exist_ok=True)
dataset_path = PROJECT_PATH / "metering_dataset"

for img_name in sorted(os.listdir(dataset_path)):
    if not img_name.lower().endswith((".png", ".jpg", ".jpeg")):
        continue

    img_abs_path = str(dataset_path / img_name)
    print(f"\nProcessing image: {img_name}")

    # --------------------------------------
    # ETAPA 1: SEGMENTAÇÃO
    # --------------------------------------
    input_data_seg = process_seg_image(img_abs_path)
    seg_input_buffers[0].write(input_data_seg)
    model_seg.run_by_index(0, seg_input_buffers, seg_output_buffers)
    
    output_raw_seg = seg_output_buffers[0].read(SEG_IMG_HEIGHT * SEG_IMG_WIDTH * 1, np.int8)
    output_image_seg = output_raw_seg.reshape((SEG_IMG_HEIGHT, SEG_IMG_WIDTH, 1))

    # Pós-processamento da máscara
    mask_binary = np.where(output_image_seg > 0, 255, 0).astype(np.uint8)

    orig_img_bytes = tf.io.read_file(img_abs_path)
    orig_img = tf.io.decode_image(orig_img_bytes, channels=1)
    orig_img_np = orig_img.numpy()  # (H_orig, W_orig, 1)

    orig_h, orig_w = orig_img_np.shape[:2]
    mask_resized = tf.image.resize(
        mask_binary,
        [orig_h, orig_w],
        method="nearest"
    ).numpy()

    # --------------------------------------
    # ETAPA 2: RECORTE DA REGIAO DO VISOR (ROI)
    # --------------------------------------
    pontos = np.where(mask_resized > 0)
    if len(pontos[0]) > 0:
        margin = 7
        ymin = max(0, np.min(pontos[0]) - margin)
        ymax = min(orig_h, np.max(pontos[0]) + 1 + margin)
        xmin = max(0, np.min(pontos[1]) - margin)
        xmax = min(orig_w, np.max(pontos[1]) + 1 + margin)

        crop_np = orig_img_np[ymin:ymax, xmin:xmax]

        # --------------------------------------
        # ETAPA 3: RECONHECIMENTO CTC (OCR)
        # --------------------------------------
        ocr_input = preprocess_crop_for_ocr(crop_np)

        ocr_input_buffers[0].write(ocr_input)
        model_ocr.run_by_index(0, ocr_input_buffers, ocr_output_buffers)

        # O modelo float_ctc gera tensor (1, 56, 11) -> 56 timesteps, 11 classes
        # Tamanho total do buffer = 1 * 56 * 11 * 4 bytes (float32)
        logits_raw = ocr_output_buffers[0].read(56 * 11, np.float32)
        logits = logits_raw.reshape((56, 11))

        # Decodificação da sequência pelo algoritmo CTC
        texto_reconhecido = ctc_greedy_decode(logits)
        print(f"Texto Reconhecido pelo modelo CTC: '{texto_reconhecido}'")
    else:
        print("Nenhum visor detectado pela máscara de segmentação.")