import os
os.environ['TF_USE_LEGACY_KERAS'] = '1'

import cv2
import random
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import tensorflow as tf
import tensorflow_model_optimization as tfmot
from PIL import Image, ImageOps
from tensorflow.keras.utils import img_to_array
import tensorflow.keras.backend as K

# Fixar sementes para reprodutibilidade
SEED = 42
random.seed(SEED)
np.random.seed(SEED)
tf.random.set_seed(SEED)

# ==========================================
# FUNÇÕES PERSONALIZADAS DOS MODELOS (.h5)
# ==========================================
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
# MÉTRICAS DE AVALIAÇÃO
# ==========================================
def calcular_iou(y_true, y_pred):
    intersection = np.logical_and(y_true, y_pred).sum()
    union = np.logical_or(y_true, y_pred).sum()
    return (intersection / union) * 100 if union > 0 else 0.0

def calcular_dice(y_true, y_pred):
    intersection = np.logical_and(y_true, y_pred).sum()
    soma = y_true.sum() + y_pred.sum()
    return (2. * intersection / soma) * 100 if soma > 0 else 0.0

def recortar_regiao_original(imagem_original_gray, mascara_binaria):
    mask_u8 = (mascara_binaria * 255).astype(np.uint8)
    contours, _ = cv2.findContours(mask_u8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    if not contours:
        return None
        
    maior_contorno = max(contours, key=cv2.contourArea)
    x, y, w, h = cv2.boundingRect(maior_contorno)
    
    if w < 5 or h < 5:
        return None
        
    # Realiza o recorte na imagem original redimensionada (384x384)
    recorte = imagem_original_gray[y:y+h, x:x+w]
    return recorte

# ==========================================
# CONFIGURAÇÕES E DIRETÓRIOS
# ==========================================
DIRETORIO_ATUAL = os.path.dirname(os.path.abspath(__file__))

DIR_MODELO_PRINCIPAL = os.path.join(DIRETORIO_ATUAL, "Modelos", "modelo_medidor.h5")
DIR_MODELO_COMPACTO = os.path.join(DIRETORIO_ATUAL, "Modelos", "modelo_medidor_compacto_160.h5")

DIR_IMG = os.path.join(DIRETORIO_ATUAL, "dataset", "images")
DIR_MASK = os.path.join(DIRETORIO_ATUAL, "dataset", "masks")

# Diretórios de saída para visualização e recortes na imagem original
DIR_RESULTADOS = os.path.join(DIRETORIO_ATUAL, "resultados_visuais_comparacao")
DIR_RECORTES_GABARITO = os.path.join(DIR_RESULTADOS, "recortes_imagem_gabarito")
DIR_RECORTES_PRINCIPAL = os.path.join(DIR_RESULTADOS, "recortes_imagem_principal_384")
DIR_RECORTES_COMPACTO = os.path.join(DIR_RESULTADOS, "recortes_imagem_compacto_160")

for d in [DIR_RESULTADOS, DIR_RECORTES_GABARITO, DIR_RECORTES_PRINCIPAL, DIR_RECORTES_COMPACTO]:
    os.makedirs(d, exist_ok=True)

IMG_SIZE = (384, 384)
COMPACT_SIZE = (160, 160)

# ==========================================
# CARREGAMENTO DOS DOIS MODELOS (.h5)
# ==========================================
custom_objects = {
    'dice_coef': dice_coef,
    'dice_loss': dice_loss,
    'bce_dice_loss': bce_dice_loss
}

print("-> A carregar o modelo principal (.h5)...")
with tfmot.quantization.keras.quantize_scope():
    model_principal = tf.keras.models.load_model(DIR_MODELO_PRINCIPAL, custom_objects=custom_objects)

print("-> A carregar o segundo modelo compacto (.h5)...")
with tfmot.quantization.keras.quantize_scope():
    model_compacto = tf.keras.models.load_model(DIR_MODELO_COMPACTO, custom_objects=custom_objects)

# ==========================================
# EXECUÇÃO E SALVAMENTO (20 AMOSTRAS)
# ==========================================
print("-> A iniciar testes, a gerar gráficos e a extrair recortes reais da imagem...")
arquivos_validos = sorted([f for f in os.listdir(DIR_IMG) if f.endswith(('.png', '.jpg', '.jpeg'))])
amostras = random.sample(arquivos_validos, min(20, len(arquivos_validos)))

resultados = []

for i, arquivo in enumerate(amostras):
    caminho_img = os.path.join(DIR_IMG, arquivo)
    caminho_mask = os.path.join(DIR_MASK, arquivo)
    
    if not os.path.exists(caminho_mask):
        continue
        
    # --- CORREÇÃO EXIF: Carrega a imagem e endireita-a automaticamente ---
    img_pil_raw = Image.open(caminho_img)
    img_pil_raw = ImageOps.exif_transpose(img_pil_raw)
    
    # 1. Preparação para o modelo principal (384x384) em escala de cinza (0 a 255)
    img_pil_384 = img_pil_raw.convert("L").resize(IMG_SIZE)
    img_array_uint8 = np.array(img_pil_384)
    img_array = img_array_uint8 / 255.0
    img_input = np.expand_dims(img_array, axis=0)
    
    # Carregamento do Gabarito (Máscara) correspondente
    mask_pil = Image.open(caminho_mask).convert("L").resize(IMG_SIZE)
    mask_array = img_to_array(mask_pil) / 255.0
    mask_binaria = np.where(mask_array > 0.5, 1.0, 0.0).squeeze()
    
    # Recorte ideal na imagem original usando o Gabarito (como seria se o modelo acertasse 100%)
    recorte_gabarito = recortar_regiao_original(img_array_uint8, mask_binaria)
    if recorte_gabarito is not None and recorte_gabarito.size > 0:
        cv2.imwrite(os.path.join(DIR_RECORTES_GABARITO, arquivo), recorte_gabarito)
    
    # Inferência Modelo Principal
    pred_principal = model_principal.predict(img_input, verbose=0)[0]
    pred_bin_princ = np.where(pred_principal > 0.5, 1.0, 0.0).squeeze()
    
    iou_princ = calcular_iou(mask_binaria, pred_bin_princ)
    dice_princ = calcular_dice(mask_binaria, pred_bin_princ)
    
    # Recorte na imagem original usando a predição do Modelo Principal
    recorte_principal = recortar_regiao_original(img_array_uint8, pred_bin_princ)
    if recorte_principal is not None and recorte_principal.size > 0:
        cv2.imwrite(os.path.join(DIR_RECORTES_PRINCIPAL, arquivo), recorte_principal)
    
    # 2. Preparação para o modelo compacto (160x160)
    img_pil_160 = img_pil_raw.convert("L").resize(COMPACT_SIZE)
    img_array_160 = img_to_array(img_pil_160) / 255.0
    img_input_160 = np.expand_dims(img_array_160, axis=0)
    
    # Inferência Modelo Compacto
    pred_compacto_nativo = model_compacto.predict(img_input_160, verbose=0)[0].squeeze()
    pred_bin_comp_nativo = np.where(pred_compacto_nativo > 0.5, 1.0, 0.0)
    
    # Recorte na imagem original usando a predição do Modelo Compacto (redimensionado para 384x384 para alinhar coordenadas)
    pred_compacto_resized = cv2.resize(pred_compacto_nativo, IMG_SIZE)
    pred_bin_comp_resized = np.where(pred_compacto_resized > 0.5, 1.0, 0.0)
    
    recorte_compacto = recortar_regiao_original(img_array_uint8, pred_bin_comp_resized)
    if recorte_compacto is not None and recorte_compacto.size > 0:
        cv2.imwrite(os.path.join(DIR_RECORTES_COMPACTO, arquivo), recorte_compacto)
    
    iou_comp = calcular_iou(mask_binaria, pred_bin_comp_resized)
    dice_comp = calcular_dice(mask_binaria, pred_bin_comp_resized)
    
    # 3. Geração do painel visual lado a lado
    fig, axs = plt.subplots(1, 4, figsize=(16, 4))
    
    axs[0].imshow(img_array, cmap='gray')
    axs[0].set_title('Original', fontsize=10)
    
    axs[1].imshow(mask_binaria, cmap='gray')
    axs[1].set_title('Gabarito (Mask)', fontsize=10)
    
    axs[2].imshow(pred_bin_princ, cmap='jet', alpha=0.8)
    axs[2].set_title(f'Principal (384)\nIoU: {iou_princ:.1f}%', fontsize=9)
    
    axs[3].imshow(pred_bin_comp_resized, cmap='jet', alpha=0.8)
    axs[3].set_title(f'Compacto (160)\nIoU: {iou_comp:.1f}%', fontsize=9)
    
    for ax in axs:
        ax.axis('off')
        
    plt.suptitle(f"Ficheiro: {arquivo}", fontsize=12, fontweight='bold', y=1.02)
    plt.tight_layout()
    
    caminho_saida = os.path.join(DIR_RESULTADOS, f"comp_{i+1}_{arquivo}.png")
    plt.savefig(caminho_saida, dpi=150, bbox_inches='tight')
    plt.close(fig)
    
    resultados.append({
        "Ficheiro": arquivo,
        "IoU Principal (%)": round(iou_princ, 2),
        "Dice Principal (%)": round(dice_princ, 2),
        "IoU Compacto (%)": round(iou_comp, 2),
        "Dice Compacto (%)": round(dice_comp, 2)
    })

df_res = pd.DataFrame(resultados)
print("\n--- RESUMO DA COMPARAÇÃO DOS MODELOS (.h5) ---")
print(df_res.to_markdown(index=False))
print(f"\n-> Gráficos comparativos salvos em: '{DIR_RESULTADOS}'")
print(f"-> Recortes reais ideais (Gabarito) salvos em: '{DIR_RECORTES_GABARITO}'")
print(f"-> Recortes reais do Modelo Principal salvos em: '{DIR_RECORTES_PRINCIPAL}'")
print(f"-> Recortes reais do Modelo Compacto salvos em: '{DIR_RECORTES_COMPACTO}'")