import os
os.environ['TF_USE_LEGACY_KERAS'] = '1'

import cv2
import numpy as np
import tensorflow as tf
import tensorflow_model_optimization as tfmot
from tensorflow.keras.utils import load_img, img_to_array
import tensorflow.keras.backend as K

# ==========================================
# 0. FUNÇÕES CUSTOMIZADAS DA U-NET
# ==========================================
def dice_coef(y_true, y_pred, smooth=1e-6):
    y_true_f = K.flatten(tf.cast(y_true, tf.float32))
    y_pred_f = K.flatten(y_pred)
    intersection = K.sum(y_true_f * y_pred_f)
    return (2. * intersection + smooth) / (K.sum(y_true_f) + K.sum(y_pred_f) + smooth)

def dice_loss(y_true, y_pred):
    return 1.0 - dice_coef(y_true, y_pred)

def bce_dice_loss(y_true, y_pred):
    bce = tf.reduce_mean(tf.keras.losses.binary_crossentropy(y_true, y_pred))
    return bce + dice_loss(y_true, y_pred)

# ==========================================
# 1. CONFIGURAÇÕES
# ==========================================
DIRETORIO_ATUAL = os.path.dirname(os.path.abspath(__file__))
DIR_MODELOS = os.path.join(DIRETORIO_ATUAL, "Modelos")
DIR_DS_IMG = os.path.join(DIRETORIO_ATUAL, "dataset", "images")
DIR_DS_MASK = os.path.join(DIRETORIO_ATUAL, "dataset", "masks")
DIR_IMG_REAIS = os.path.join(DIRETORIO_ATUAL, "dataset", "imagens_reais")
DIR_DIAG = os.path.join(DIRETORIO_ATUAL, "resultados_visuais", "diagnostico_detector")

UNET_SIZE = 384
KERNEL_CLOSE = 15          # mesmo valor usado no simulador
AREA_MIN = 80              # mesma área mínima do simulador
LIMIARES = [0.5, 0.7, 0.9]

os.makedirs(DIR_DIAG, exist_ok=True)

custom_objects = {'dice_coef': dice_coef, 'dice_loss': dice_loss, 'bce_dice_loss': bce_dice_loss}
with tfmot.quantization.keras.quantize_scope():
    unet = tf.keras.models.load_model(os.path.join(DIR_MODELOS, "modelo_medidor.h5"),
                                      custom_objects=custom_objects, compile=False)

# ==========================================
# 2. FUNÇÕES AUXILIARES
# ==========================================
def prever_prob(caminho):
    """Retorna (imagem cinza uint8 384x384, mapa de probabilidade 384x384)."""
    img = img_to_array(load_img(caminho, color_mode="grayscale",
                                target_size=(UNET_SIZE, UNET_SIZE))) / 255.0
    prob = unet(np.expand_dims(img, axis=0), training=False).numpy()[0, ..., 0]
    return (img[..., 0] * 255).astype(np.uint8), prob

def bbox_da_prob(prob, limiar, kernel=KERNEL_CLOSE):
    """Mesmo pós-processamento do simulador. kernel=0 desliga o fechamento.
    Retorna (bbox ou None, número de contornos)."""
    mask = (prob > limiar).astype(np.uint8) * 255
    if kernel:
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE,
                                cv2.getStructuringElement(cv2.MORPH_RECT, (kernel, kernel)))
    contornos, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contornos:
        return None, 0
    maior = max(contornos, key=cv2.contourArea)
    if cv2.contourArea(maior) < AREA_MIN:
        return None, len(contornos)
    return cv2.boundingRect(maior), len(contornos)

def iou_bbox(a, b):
    if a is None or b is None:
        return 0.0
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    x1, y1 = max(ax, bx), max(ay, by)
    x2, y2 = min(ax + aw, bx + bw), min(ay + ah, by + bh)
    inter = max(0, x2 - x1) * max(0, y2 - y1)
    uniao = aw * ah + bw * bh - inter
    return inter / uniao if uniao else 0.0

def dice_np(a, b, smooth=1e-6):
    a, b = a.astype(np.float32).ravel(), b.astype(np.float32).ravel()
    return (2 * (a * b).sum() + smooth) / (a.sum() + b.sum() + smooth)

# ==========================================
# 3. PARTE A — DETECTOR NA VALIDAÇÃO DO DATASET
# ==========================================
# Usa a mesma divisão do treino (últimos 20% da lista ordenada).
# Responde: o detector é bom no próprio dataset? As máscaras são justas?
print("=" * 70)
print("PARTE A — Validação no dataset (mesma divisão 80/20 do treino)")
print("=" * 70)

if os.path.isdir(DIR_DS_IMG) and os.path.isdir(DIR_DS_MASK):
    arquivos = sorted(f for f in os.listdir(DIR_DS_IMG)
                      if f.lower().endswith(('.png', '.jpg', '.jpeg')))
    val = arquivos[int(len(arquivos) * 0.8):]

    resultados = []   # (arquivo, dice, iou_bbox, razao_area_bbox_pred_gt)
    for f in val:
        caminho_mask = os.path.join(DIR_DS_MASK, f)
        if not os.path.exists(caminho_mask):
            continue
        _, prob = prever_prob(os.path.join(DIR_DS_IMG, f))
        gt = img_to_array(load_img(caminho_mask, color_mode="grayscale",
                                   target_size=(UNET_SIZE, UNET_SIZE)))[..., 0] / 255.0
        gt = (gt > 0.5).astype(np.float32)

        dice = dice_np(prob > 0.5, gt)
        bbox_pred, _ = bbox_da_prob(prob, 0.5)
        bbox_gt, _ = bbox_da_prob(gt, 0.5, kernel=0)
        iou = iou_bbox(bbox_pred, bbox_gt)
        razao = (bbox_pred[2] * bbox_pred[3]) / (bbox_gt[2] * bbox_gt[3]) \
            if bbox_pred and bbox_gt else float('nan')
        resultados.append((f, dice, iou, razao))

    if resultados:
        dices = np.array([r[1] for r in resultados])
        ious = np.array([r[2] for r in resultados])
        razoes = np.array([r[3] for r in resultados])
        validos = razoes[~np.isnan(razoes)]
        print(f"Imagens de validação: {len(resultados)}")
        print(f"Dice (limiar 0.5):  média {dices.mean():.3f} | mediana {np.median(dices):.3f} "
              f"| mínimo {dices.min():.3f}")
        print(f"IoU do bbox:        média {ious.mean():.3f} | mediana {np.median(ious):.3f}")
        if len(validos):
            print(f"Bbox previsto > 1.5x maior que o real: {(validos > 1.5).sum()}/{len(validos)}"
                  f" | razão de área mediana: {np.median(validos):.2f}")
        print("Piores 5 por IoU do bbox:")
        for f, d, i, r in sorted(resultados, key=lambda t: t[2])[:5]:
            print(f"   {f}: Dice {d:.3f} | IoU bbox {i:.3f} | razão de área {r:.2f}")
    else:
        print("Nenhum par imagem/máscara encontrado na validação.")
else:
    print("dataset/images ou dataset/masks não encontrado: parte A ignorada.")

# ==========================================
# 4. PARTE B — IMAGENS REAIS (OVERLAYS)
# ==========================================
# Painel salvo: [imagem 384x384 | mapa de probabilidade + caixas]
#   verde   = bbox do pipeline atual (limiar 0.5 + fechamento)
#   vermelho= bbox sem fechamento morfológico
#   azul    = bbox com limiar 0.9
print("\n" + "=" * 70)
print("PARTE B — Imagens reais")
print("=" * 70)
print(f"Larguras do bbox (em px de 384) por limiar {LIMIARES}; "
      f"contornos antes/depois do fechamento\n")

def retangulo(img, bbox, cor, espessura):
    if bbox:
        x, y, w, h = bbox
        cv2.rectangle(img, (x, y), (x + w, y + h), cor, espessura)

for arquivo in sorted(os.listdir(DIR_IMG_REAIS)):
    if not arquivo.lower().endswith(('.png', '.jpg', '.jpeg')):
        continue

    gray, prob = prever_prob(os.path.join(DIR_IMG_REAIS, arquivo))

    bbox_atual, n_depois = bbox_da_prob(prob, 0.5)
    bbox_sem_close, n_antes = bbox_da_prob(prob, 0.5, kernel=0)
    bbox_estrito, _ = bbox_da_prob(prob, 0.9)
    larguras = [(bbox_da_prob(prob, lim)[0] or (0, 0, 0, 0))[2] for lim in LIMIARES]

    aviso = ""
    if bbox_atual and bbox_sem_close:
        cresc = (bbox_atual[2] * bbox_atual[3]) / max(1, bbox_sem_close[2] * bbox_sem_close[3])
        if cresc > 1.3:
            aviso = f"  <- fechamento aumentou o bbox em {cresc:.1f}x (regiões fundidas?)"

    print(f"{arquivo}: prob_max={prob.max():.2f} | larguras={larguras} "
          f"| contornos {n_antes}->{n_depois}{aviso}")

    base = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    calor = cv2.applyColorMap((np.clip(prob, 0, 1) * 255).astype(np.uint8), cv2.COLORMAP_JET)
    overlay = cv2.addWeighted(base, 0.55, calor, 0.45, 0)
    retangulo(overlay, bbox_estrito, (255, 0, 0), 1)       # azul (BGR)
    retangulo(overlay, bbox_sem_close, (0, 0, 255), 1)     # vermelho
    retangulo(overlay, bbox_atual, (0, 255, 0), 2)         # verde
    cv2.imwrite(os.path.join(DIR_DIAG, f"diag_{arquivo}.png"), np.hstack([base, overlay]))

print(f"\n-> Painéis salvos em: {DIR_DIAG}")