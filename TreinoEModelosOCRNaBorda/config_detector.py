import cv2
import numpy as np
from tensorflow.keras.utils import load_img, img_to_array

# ==========================================
# RESOLUÇÃO E PERFIL
# ==========================================
IMG_SIZE = (160, 160)            # precisa ser múltiplo de 8
PERFIL_DETECTOR = "compacto"        # "grande" | "medio" | "compacto"

# canais por nível (alta -> baixa resolução), convoluções por bloco nos 2 níveis de
# maior resolução e kernel da convolução transposta (stride 2).
PERFIS = {
    "grande":   dict(canais=(16, 32, 64, 128), convs_alto=2, k_t=3),   # ~ arquitetura anterior (com BN)
    "medio":    dict(canais=(12, 24, 48, 96),  convs_alto=1, k_t=2),
    "compacto": dict(canais=(8, 16, 32, 64),   convs_alto=1, k_t=2),
}

NOME_MODELO = f"modelo_medidor_{PERFIL_DETECTOR}_{IMG_SIZE[0]}"

# ==========================================
# PRÉ-PROCESSAMENTO (idêntico no treino e na inferência)
# ==========================================
# O resize bilinear do PIL faz antialiasing ao reduzir; o 'nearest' (padrão do
# load_img) não faz, e ao reduzir fotos grandes para ~160 px ele serrilha o visor.
INTERP_IMG = "bilinear"
INTERP_MASK = "bilinear"         # a máscara é binarizada em 0.5 depois do resize


def carregar_imagem(caminho):
    """(H, W, 1) float32 em [0, 1]."""
    img = load_img(caminho, color_mode="grayscale", target_size=IMG_SIZE, interpolation=INTERP_IMG)
    return img_to_array(img) / 255.0


def carregar_mascara(caminho):
    """(H, W, 1) float32 binária {0, 1}."""
    m = load_img(caminho, color_mode="grayscale", target_size=IMG_SIZE, interpolation=INTERP_MASK)
    return (img_to_array(m) / 255.0 > 0.5).astype(np.float32)


# ==========================================
# PÓS-PROCESSAMENTO (parâmetros definidos para 384 e reescalados)
# ==========================================
# Um kernel de fechamento de 15 px é ~4% da imagem a 384. A 160 px, os mesmos 15 px
# seriam 9% e fundiriam regiões vizinhas (logo + visor), então o valor é proporcional.
REF = 384
KERNEL_CLOSE = max(3, int(round(15 * IMG_SIZE[0] / REF)))
if KERNEL_CLOSE % 2 == 0:
    KERNEL_CLOSE += 1
AREA_MIN = max(8, int(round(80 * (IMG_SIZE[0] / REF) ** 2)))


def bbox_da_prob(prob, limiar=0.5, kernel=None):
    """Mesmo pós-processamento do simulador. kernel=0 desliga o fechamento.
    Retorna (bbox (x, y, w, h) ou None, número de contornos)."""
    if kernel is None:
        kernel = KERNEL_CLOSE
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
    return float((2 * (a * b).sum() + smooth) / (a.sum() + b.sum() + smooth))
