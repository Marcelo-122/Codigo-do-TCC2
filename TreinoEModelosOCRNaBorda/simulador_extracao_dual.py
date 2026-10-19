import os
os.environ['TF_USE_LEGACY_KERAS'] = '1'

import cv2
import numpy as np
import pandas as pd
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

ARQUIVO_CSV = os.path.join(DIR_CSVS, "leituras_comparacao_tflite.csv")
ARQUIVO_GABARITO = os.path.join(DIR_CSVS, "gabarito.csv")
DIR_RECORTES = os.path.join(DIRETORIO_ATUAL, "resultados_visuais", "recortes_dual")

ARQ_UNET = "modelo_medidor.h5"
ARQ_CTC_TFLITE = "modelo_digitos_ctc.tflite"
ARQ_CTC_SINT_TFLITE = "modelo_digitos_ctc_sint.tflite"

UNET_SIZE = 384
CTC_H, CTC_W = 48, 224        
BLANK = 10                    

NORMALIZAR_CONTRASTE = True
INTERPOLACAO = cv2.INTER_LINEAR

os.makedirs(DIR_CSVS, exist_ok=True)
os.makedirs(DIR_RECORTES, exist_ok=True)

# ==========================================
# 2. INTERPRETADOR TFLITE (Simulação de Hardware)
# ==========================================
class LeitorTFLite:
    def __init__(self, caminho_modelo):
        self.interpreter = tf.lite.Interpreter(model_path=caminho_modelo)
        self.interpreter.allocate_tensors()
        self.det_in = self.interpreter.get_input_details()[0]
        self.det_out = self.interpreter.get_output_details()[0]
        self.escala_in, self.zero_in = self.det_in['quantization']
        self.escala_out, self.zero_out = self.det_out['quantization']

    def prever(self, tensor_img):
        img = tensor_img[0]
        q = np.clip(np.round(img / self.escala_in + self.zero_in), -128, 127).astype(np.int8)
        self.interpreter.set_tensor(self.det_in['index'], q[np.newaxis, ...])
        self.interpreter.invoke()
        
        bruto = self.interpreter.get_tensor(self.det_out['index'])[0].astype(np.float32)
        logits = (bruto - self.zero_out) * self.escala_out
        return logits

# ==========================================
# 3. CARREGAMENTO DOS MODELOS
# ==========================================
print("-> Carregando redes (U-Net H5 e CTCs em TFLite INT8)...")
with tfmot.quantization.keras.quantize_scope():
    unet_model = tf.keras.models.load_model(
        os.path.join(DIR_MODELOS, ARQ_UNET), 
        custom_objects={'dice_coef': dice_coef, 'dice_loss': dice_loss, 'bce_dice_loss': bce_dice_loss}, 
        compile=False
    )

leitor_ctc_orig = LeitorTFLite(os.path.join(DIR_MODELOS, ARQ_CTC_TFLITE))
leitor_ctc_sint = LeitorTFLite(os.path.join(DIR_MODELOS, ARQ_CTC_SINT_TFLITE))

# ==========================================
# 4. DETECTOR (U-NET) — RECORTE DO VISOR
# ==========================================
def extrair_coordenadas_unet(caminho_img):
    img_pil = load_img(caminho_img, color_mode="grayscale", target_size=(UNET_SIZE, UNET_SIZE))
    img_array = img_to_array(img_pil) / 255.0
    img_input = np.expand_dims(img_array, axis=0)

    predicao = unet_model(img_input, training=False).numpy()[0]
    pred_binaria = np.where(predicao > 0.5, 1.0, 0.0)

    mask_uint8 = (pred_binaria.squeeze() * 255).astype(np.uint8)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 15))
    mask_corrigida = cv2.morphologyEx(mask_uint8, cv2.MORPH_CLOSE, kernel)

    contornos, _ = cv2.findContours(mask_corrigida, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contornos: return None

    maior_contorno = max(contornos, key=cv2.contourArea)
    if cv2.contourArea(maior_contorno) < 80: return None

    return cv2.boundingRect(maior_contorno)

# ==========================================
# 5. PRÉ-PROCESSAMENTO CTC
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
# 6. LEITURA (INFERÊNCIA + DECODIFICAÇÃO)
# ==========================================
def softmax(x):
    e = np.exp(x - x.max(axis=-1, keepdims=True))
    return e / e.sum(axis=-1, keepdims=True)

def ler_ctc_tflite(tensor, leitor):
    logits = leitor.prever(tensor)
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
# 7. GABARITO OPCIONAL
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
    print("-> Sem gabarito (CSVs/gabarito.csv): as leituras serão apenas processadas.")

# ==========================================
# 8. PIPELINE DE EXECUÇÃO
# ==========================================
print("\n-> Iniciando extração (U-Net -> CTC Original [TFLite] vs CTC Sintético [TFLite])...\n")

dados_csv = []

print("Arquivo | CTC Orig (conf) | CTC Sint (conf)")
print("-" * 80)

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
        print(f"{arquivo} | FALHA_LOCALIZACAO")
        dados_csv.append({"Arquivo": arquivo, "Status": "FALHA_LOCALIZACAO"})
        continue

    img_ctc, tensor_ctc = preparar_ctc(recorte_visor)

    cv2.imwrite(os.path.join(DIR_RECORTES, f"visor_original_{arquivo}"), recorte_visor)
    cv2.imwrite(os.path.join(DIR_RECORTES, f"visor_ctc_{arquivo}"), img_ctc)

    leitura_ctc_orig, conf_ctc_orig = ler_ctc_tflite(tensor_ctc, leitor_ctc_orig)
    leitura_ctc_sint, conf_ctc_sint = ler_ctc_tflite(tensor_ctc, leitor_ctc_sint)
    
    linha_csv = {
        "Arquivo": arquivo,
        "Status": "OK",
        "Leitura_CTC_Orig": leitura_ctc_orig,
        "Conf_CTC_Orig": round(conf_ctc_orig, 4),
        "Leitura_CTC_Sint": leitura_ctc_sint,
        "Conf_CTC_Sint": round(conf_ctc_sint, 4)
    }

    extra = ""
    if arquivo in gabarito:
        real = gabarito[arquivo]
        linha_csv["Gabarito"] = real
        linha_csv["Acerto_CTC_Orig"] = leitura_ctc_orig == real
        linha_csv["Acerto_CTC_Sint"] = leitura_ctc_sint == real
        extra = (f" | gabarito={real} "
                 f"CTC-O:{'ok' if leitura_ctc_orig == real else 'ERRO'} "
                 f"CTC-S:{'ok' if leitura_ctc_sint == real else 'ERRO'}")

    print(f"{arquivo} | {leitura_ctc_orig} ({conf_ctc_orig:.2f}) | {leitura_ctc_sint} ({conf_ctc_sint:.2f}){extra}")
    dados_csv.append(linha_csv)

# ==========================================
# 9. RESUMO DA EXTRAÇÃO
# ==========================================
df = pd.DataFrame(dados_csv)
total = len(df)
ok = df[df["Status"] == "OK"] if total else df
falhas = total - len(ok)

print("\n" + "=" * 80)
print("RESUMO DA EXTRAÇÃO (Modelos .tflite)")
print("=" * 80)
print(f"Imagens processadas: {total} | Falhas de localização (U-Net): {falhas}")

if len(ok):
    if "Acerto_CTC_Orig" in ok.columns:
        com_gab = ok.dropna(subset=["Acerto_CTC_Orig"]).copy()
        com_gab["Acerto_CTC_Orig"] = com_gab["Acerto_CTC_Orig"].astype(bool)
        com_gab["Acerto_CTC_Sint"] = com_gab["Acerto_CTC_Sint"].astype(bool)
        n = len(com_gab)
        if n:
            ctc_o = com_gab["Acerto_CTC_Orig"]
            ctc_s = com_gab["Acerto_CTC_Sint"]
            print(f"\nAcurácia com gabarito ({n} imagens localizadas):")
            print(f"  CTC Original:  {ctc_o.sum()}/{n} ({100 * ctc_o.sum() / n:.1f}%)")
            print(f"  CTC Sintético: {ctc_s.sum()}/{n} ({100 * ctc_s.sum() / n:.1f}%)")
            print(f"  Ambos certos: {(ctc_o & ctc_s).sum()} | Ambos errados: {(~ctc_o & ~ctc_s).sum()}")

df.to_csv(ARQUIVO_CSV, index=False)

print(f"\n-> Leituras exportadas para CSV: '{ARQUIVO_CSV}'")
print(f"-> Imagens de depuração salvas em: '{DIR_RECORTES}'")