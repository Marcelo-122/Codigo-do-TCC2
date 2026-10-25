import os
import cv2
import random
import numpy as np

# ==========================================
# 1. CONFIGURAÇÕES E DIRETÓRIOS
# ==========================================
DIRETORIO_ATUAL = os.path.dirname(os.path.abspath(__file__))

DIR_IMG = os.path.join(DIRETORIO_ATUAL, "dataset", "images")
DIR_MASK = os.path.join(DIRETORIO_ATUAL, "dataset", "masks")
DIR_SAIDA = os.path.join(DIRETORIO_ATUAL, "dataset", "visores_blackout")

LIMITE_IMAGENS = 1244   # máximo disponível com máscara no dataset de origem
SEED = 42

MARGEM_PX = 6             # folga ao redor do visor já endireitado
DILATACAO_MASCARA = 15    # cresce a máscara antes do blackout, para não
                          # cortar a ponta de dígitos por imprecisão da
                          # segmentação perto da borda do visor
APAGAR_FUNDO = True       # False = só recorta e endireita, sem zerar o fundo
                          # (útil para testar se o blackout está ajudando ou
                          # atrapalhando o treino do reconhecedor)

os.makedirs(DIR_SAIDA, exist_ok=True)

# ==========================================
# 2. MAPEAMENTO E EXTRAÇÃO DO RÓTULO DO NOME
# ==========================================
print(f"-> Procurando imagens em: {DIR_IMG}")
arquivos_validos = [f for f in sorted(os.listdir(DIR_IMG)) if f.lower().endswith(('.png', '.jpg', '.jpeg'))]

if not arquivos_validos:
    raise ValueError("Nenhuma imagem encontrada na pasta de origem.")

amostras_com_rotulo = []

for arquivo in arquivos_validos:
    nome_sem_ext = os.path.splitext(arquivo)[0]
    nome_lower = nome_sem_ext.lower()
    if "value" in nome_lower:
        rotulo = nome_lower.split("value")[-1]
        rotulo = rotulo.replace("_", "").replace("-", "").strip().upper().zfill(7)
        if rotulo:
            amostras_com_rotulo.append((rotulo, arquivo))

if not amostras_com_rotulo:
    raise ValueError("Não foi possível localizar o padrão 'value' nos nomes dos ficheiros.")

# ==========================================
# 3. SORTEIO DAS IMAGENS
# ==========================================
random.seed(SEED)
if len(amostras_com_rotulo) > LIMITE_IMAGENS:
    amostras_selecionadas = random.sample(amostras_com_rotulo, LIMITE_IMAGENS)
else:
    amostras_selecionadas = amostras_com_rotulo

print(f"-> {len(amostras_selecionadas)} imagens selecionadas. Iniciando Blackout e Crop...")

# ==========================================
# 4. PROCESSAMENTO (RECORTE ALINHADO + BLACKOUT)
# ==========================================
sucessos = 0
falhas = 0
kernel_dilatacao = cv2.getStructuringElement(cv2.MORPH_ELLIPSE,
                                             (DILATACAO_MASCARA, DILATACAO_MASCARA))

for rotulo, arquivo in amostras_selecionadas:
    caminho_img = os.path.join(DIR_IMG, arquivo)
    caminho_mask = os.path.join(DIR_MASK, arquivo)

    if not os.path.exists(caminho_mask):
        falhas += 1
        continue

    img = cv2.imread(caminho_img, cv2.IMREAD_GRAYSCALE)
    mask = cv2.imread(caminho_mask, cv2.IMREAD_GRAYSCALE)
    if img is None or mask is None:
        falhas += 1
        continue

    _, mask_binaria = cv2.threshold(mask, 127, 255, cv2.THRESH_BINARY)
    contornos, _ = cv2.findContours(mask_binaria, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contornos:
        falhas += 1
        continue

    maior_contorno = max(contornos, key=cv2.contourArea)
    if cv2.contourArea(maior_contorno) < 80:
        falhas += 1
        continue

    # Cresce a máscara para absorver a imprecisão normal da segmentação nas
    # bordas. Sem isso, qualquer pixel de dígito que o U-Net deixou de fora
    # por pouco vira preto no blackout.
    mask_dilatada = cv2.dilate(mask_binaria, kernel_dilatacao)

    # Retângulo ROTACIONADO ao redor do visor inteiro (não um bbox reto).
    # O visor quase sempre está um pouco inclinado na foto; um bbox reto
    # sobre um contorno inclinado deixa cantos pretos que cortam dígitos
    # nas pontas — foi isso que apareceu nas miniaturas.
    (cx, cy), (w, h), angulo = cv2.minAreaRect(maior_contorno)
    if w < h:               # garante que o retângulo fique "deitado"
        w, h = h, w
        angulo += 90.0
    w += 2 * MARGEM_PX
    h += 2 * MARGEM_PX

    # Borda de segurança ANTES de rotacionar: garante que o visor nunca
    # "saia" da imagem durante o giro, o que criaria preto de verdade
    # (BORDER_REFLECT evita introduzir preto artificial nessa margem)
    borda = int(np.ceil(max(w, h)))
    img_pad = cv2.copyMakeBorder(img, borda, borda, borda, borda, cv2.BORDER_REFLECT)
    mask_pad = cv2.copyMakeBorder(mask_dilatada, borda, borda, borda, borda,
                                  cv2.BORDER_CONSTANT, value=0)
    cx, cy = cx + borda, cy + borda

    matriz_rot = cv2.getRotationMatrix2D((cx, cy), angulo, 1.0)
    img_rot = cv2.warpAffine(img_pad, matriz_rot, (img_pad.shape[1], img_pad.shape[0]),
                             flags=cv2.INTER_LINEAR)
    mask_rot = cv2.warpAffine(mask_pad, matriz_rot, (mask_pad.shape[1], mask_pad.shape[0]),
                              flags=cv2.INTER_NEAREST)

    x0, y0 = int(round(cx - w / 2)), int(round(cy - h / 2))
    x1, y1 = int(round(cx + w / 2)), int(round(cy + h / 2))
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(img_rot.shape[1], x1), min(img_rot.shape[0], y1)

    recorte = img_rot[y0:y1, x0:x1]
    mascara_recorte = mask_rot[y0:y1, x0:x1]

    if recorte.size == 0 or recorte.shape[0] < 10 or recorte.shape[1] < 20:
        falhas += 1
        continue

    recorte_final = cv2.bitwise_and(recorte, recorte, mask=mascara_recorte) \
        if APAGAR_FUNDO else recorte

    pasta_destino = os.path.join(DIR_SAIDA, rotulo)
    os.makedirs(pasta_destino, exist_ok=True)

    cv2.imwrite(os.path.join(pasta_destino, arquivo), recorte_final)
    sucessos += 1

print(f"\n-> Concluído! {sucessos} recortes salvos em: {DIR_SAIDA}")
if falhas > 0:
    print(f"-> {falhas} imagens ignoradas (falta de máscara, visor não detetado ou recorte inválido).")
