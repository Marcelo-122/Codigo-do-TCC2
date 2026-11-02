import os
os.environ['TF_USE_LEGACY_KERAS'] = '1'

import cv2
import numpy as np
import pandas as pd
import tensorflow as tf
import tensorflow_model_optimization as tfmot
from tensorflow.keras.utils import load_img, img_to_array
from config_detector import (IMG_SIZE, NOME_MODELO, KERNEL_CLOSE, AREA_MIN, carregar_imagem)
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
    bce = tf.keras.losses.binary_crossentropy(y_true, y_pred)
    bce = tf.reduce_mean(bce)
    return bce + dice_loss(y_true, y_pred)

# ==========================================
# 1. CONFIGURAÇÕES E DIRETÓRIOS
# ==========================================
DIRETORIO_ATUAL = os.path.dirname(os.path.abspath(__file__))

DIR_MODELOS = os.path.join(DIRETORIO_ATUAL, "Modelos")
DIR_IMG_REAIS = os.path.join(DIRETORIO_ATUAL, "dataset", "imagens_reais")
DIR_CSVS = os.path.join(DIRETORIO_ATUAL, "CSVs")
ARQUIVO_TXT = os.path.join(DIR_CSVS, "leituras_ctc.txt")
ARQUIVO_CSV = os.path.join(DIR_CSVS, "leituras_ctc.csv")

# Gabarito OPCIONAL: CSV com as colunas "Arquivo" e "Leitura" (ex.: foto1.jpg,0001013).
ARQUIVO_GABARITO = os.path.join(DIR_CSVS, "gabarito.csv")
DIR_RECORTES = os.path.join(DIRETORIO_ATUAL, "resultados_visuais", "recortes_ctc")

ARQ_UNET = f"{NOME_MODELO}.h5"
ARQ_CTC = "modelo_digitos_ctc.h5"

# --- Dimensões de entrada ---
UNET_SIZE = IMG_SIZE[0]       
CTC_H, CTC_W = 48, 224        
BLANK = 10                    # classe 10 = blank no CTC

NORMALIZAR_CONTRASTE = True
INTERPOLACAO = cv2.INTER_LINEAR

os.makedirs(DIR_CSVS, exist_ok=True)
os.makedirs(DIR_RECORTES, exist_ok=True)

# ==========================================
# 2. CARREGAMENTO DOS MODELOS
# ==========================================
print("-> Carregando redes (U-Net e CTC)...")
custom_objects = {
    'dice_coef': dice_coef,
    'dice_loss': dice_loss,
    'bce_dice_loss': bce_dice_loss
}

with tfmot.quantization.keras.quantize_scope():
    unet_model = tf.keras.models.load_model(
        os.path.join(DIR_MODELOS, ARQ_UNET), custom_objects=custom_objects, compile=False)
    ctc_model = tf.keras.models.load_model(
        os.path.join(DIR_MODELOS, ARQ_CTC), compile=False)

# ==========================================
# 3. DETECTOR (U-NET) — RECORTE DO VISOR
# ==========================================
def extrair_coordenadas_unet(caminho_img):
    img_array = carregar_imagem(caminho_img)
    img_input = np.expand_dims(img_array, axis=0)

    predicao = unet_model(img_input, training=False).numpy()[0]
    pred_binaria = np.where(predicao > 0.5, 1.0, 0.0)

    mask_uint8 = (pred_binaria.squeeze() * 255).astype(np.uint8)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (KERNEL_CLOSE, KERNEL_CLOSE))
    mask_corrigida = cv2.morphologyEx(mask_uint8, cv2.MORPH_CLOSE, kernel)

    contornos, _ = cv2.findContours(mask_corrigida, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    if not contornos: return None

    maior_contorno = max(contornos, key=cv2.contourArea)
    if cv2.contourArea(maior_contorno) < AREA_MIN: return None

    return cv2.boundingRect(maior_contorno)

# ==========================================
# 4. PRÉ-PROCESSAMENTO DO EXTRATOR CTC
# ==========================================
def normalizar_contraste(img):
    if not NORMALIZAR_CONTRASTE:
        return img
    return cv2.normalize(img, None, 0, 255, cv2.NORM_MINMAX)

def preparar_ctc(recorte):
    h, w = recorte.shape
    escala = min(CTC_H / h, CTC_W / w)
    nova_h = max(1, int(round(h * escala)))
    nova_w = max(1, int(round(w * escala)))

    img = cv2.resize(recorte.astype(np.float32), (nova_w, nova_h), interpolation=INTERPOLACAO)
    fundo = float(img[:, -1:].mean())

    canvas = np.full((CTC_H, CTC_W), fundo, dtype=np.float32)
    canvas[:nova_h, :nova_w] = img
    canvas = np.clip(np.round(canvas), 0, 255).astype(np.uint8)
    canvas = normalizar_contraste(canvas)

    tensor = np.expand_dims(canvas.astype(np.float32) / 255.0, axis=(0, -1))
    return canvas, tensor

# ==========================================
# 5. LEITURA (INFERÊNCIA + DECODIFICAÇÃO)
# ==========================================
def softmax(x):
    e = np.exp(x - x.max(axis=-1, keepdims=True))
    return e / e.sum(axis=-1, keepdims=True)

def ler_ctc(tensor):
    logits = ctc_model(tensor, training=False).numpy()[0]   
    probs = softmax(logits)
    ids = probs.argmax(axis=-1)

    digitos, confs, anterior = [], [], BLANK
    for t, i in enumerate(ids):
        if i != BLANK:
            p = float(probs[t, i])
            if i != anterior:
                digitos.append(int(i))
                confs.append(p)
            else:
                confs[-1] = max(confs[-1], p)
        anterior = i
    return ''.join(str(d) for d in digitos), (min(confs) if confs else 0.0)

# ==========================================
# 6. GABARITO OPCIONAL
# ==========================================
gabarito = {}
if os.path.exists(ARQUIVO_GABARITO):
    df_gab = pd.read_csv(ARQUIVO_GABARITO, dtype=str).dropna()
    if not {'Arquivo', 'Leitura'} <= set(df_gab.columns):
        raise ValueError("O gabarito precisa ter as colunas 'Arquivo' e 'Leitura'.")
    gabarito = {row['Arquivo'].strip(): row['Leitura'].strip().upper().rstrip('X')
                for _, row in df_gab.iterrows()}
    print(f"-> Gabarito carregado: {len(gabarito)} leituras.")
else:
    print("-> Sem gabarito (CSVs/gabarito.csv): as leituras serão processadas sem cálculo de acurácia.")

# ==========================================
# 7. PIPELINE DE EXECUÇÃO
# ==========================================
print("\n-> Iniciando extração (recorte U-Net -> CTC)...\n")

dados_csv = []

with open(ARQUIVO_TXT, "w", encoding="utf-8") as arquivo_txt:
    def log(linha=""):
        print(linha)
        arquivo_txt.write(linha + "\n")

    log("Arquivo | Leitura CTC (Confiança) | Status")
    log("-" * 60)

    for arquivo in sorted(os.listdir(DIR_IMG_REAIS)):
        if not arquivo.lower().endswith(('.png', '.jpg', '.jpeg')): continue

        caminho_img = os.path.join(DIR_IMG_REAIS, arquivo)
        img_original = cv2.imread(caminho_img, cv2.IMREAD_GRAYSCALE)

        bbox = extrair_coordenadas_unet(caminho_img)
        recorte_visor = None

        if bbox:
            x_unet, y_unet, w_unet, h_unet = bbox
            h_orig, w_orig = img_original.shape

            fator_x = w_orig / float(UNET_SIZE)
            fator_y = h_orig / float(UNET_SIZE)
            x_real, y_real = int(x_unet * fator_x), int(y_unet * fator_y)
            w_real, h_real = int(w_unet * fator_x), int(h_unet * fator_y)

            recorte_visor = img_original[y_real:y_real + h_real, x_real:x_real + w_real]

        if recorte_visor is None or recorte_visor.size == 0:
            log(f"{arquivo} | FALHA_LOCALIZACAO")
            dados_csv.append({"Arquivo": arquivo, "Status": "FALHA_LOCALIZACAO"})
            continue

        img_ctc, tensor_ctc = preparar_ctc(recorte_visor)

        cv2.imwrite(os.path.join(DIR_RECORTES, f"visor_original_{arquivo}"), recorte_visor)
        cv2.imwrite(os.path.join(DIR_RECORTES, f"visor_ctc_{arquivo}"), img_ctc)

        leitura_ctc, conf_ctc = ler_ctc(tensor_ctc)

        linha_csv = {
            "Arquivo": arquivo,
            "Status": "OK",
            "Leitura_CTC": leitura_ctc,
            "Conf_CTC": round(conf_ctc, 4)
        }

        extra = ""
        if arquivo in gabarito:
            real = gabarito[arquivo]
            linha_csv["Gabarito"] = real
            acertou = (leitura_ctc == real)
            linha_csv["Acerto_CTC"] = acertou
            extra = f" | gabarito={real} CTC:{'OK' if acertou else 'ERRO'}"

        log(f"{arquivo} | {leitura_ctc} ({conf_ctc:.2f}) | OK{extra}")
        dados_csv.append(linha_csv)

    # ==========================================
    # 8. RESUMO DA EXECUÇÃO
    # ==========================================
    df = pd.DataFrame(dados_csv)
    total = len(df)
    ok = df[df["Status"] == "OK"] if total else df
    falhas = total - len(ok)

    log()
    log("=" * 60)
    log("RESUMO")
    log("=" * 60)
    log(f"Imagens processadas: {total} | falhas de localização (U-Net): {falhas}")

    if len(ok) and "Acerto_CTC" in ok.columns:
        com_gab = ok.dropna(subset=["Acerto_CTC"]).copy()
        com_gab["Acerto_CTC"] = com_gab["Acerto_CTC"].astype(bool)
        n = len(com_gab)
        if n:
            ctc_acertos = com_gab["Acerto_CTC"].sum()
            log(f"\nAcurácia com gabarito ({n} imagens localizadas):")
            log(f"  CTC: {ctc_acertos}/{n} ({100 * ctc_acertos / n:.1f}%)")

df.to_csv(ARQUIVO_CSV, index=False)
print(f"-> Leituras exportadas para CSV: '{ARQUIVO_CSV}'")
print(f"-> Imagens de depuração salvas em: '{DIR_RECORTES}'")