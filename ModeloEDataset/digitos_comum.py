import os
import cv2
import numpy as np


def imread_unicode(caminho, flags=cv2.IMREAD_COLOR):
    """cv2.imread falha com caminhos com acentos/caracteres especiais no
    Windows; le os bytes manualmente e decodifica."""
    dados = np.fromfile(caminho, dtype=np.uint8)
    if dados.size == 0:
        return None
    return cv2.imdecode(dados, flags)


def _foreground_mask(gray):
    """Tenta as duas polaridades (dígito escuro-no-claro e claro-no-escuro)
    e fica com a que produzir maior variancia na projecao vertical (mais
    provavel de separar celulas de digito)."""
    blur = cv2.GaussianBlur(gray, (3, 3), 0)
    _, mask_dark = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    _, mask_light = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    proj_dark = mask_dark.sum(axis=0)
    proj_light = mask_light.sum(axis=0)
    return mask_dark if proj_dark.std() >= proj_light.std() else mask_light


def segment_cells(strip_bgr, n_expected, min_cell_frac=0.03):
    """Segmenta uma tira horizontal contendo N digitos em N celulas, usando
    projecao vertical (soma de pixels de primeiro-plano por coluna) para
    achar os vaos entre rodinhas. Retorna lista de N recortes (arrays
    grayscale) ordenados da esquerda pra direita, ou None se a contagem de
    celulas encontrada nao bater com n_expected."""
    gray = cv2.cvtColor(strip_bgr, cv2.COLOR_BGR2GRAY) if strip_bgr.ndim == 3 else strip_bgr
    h, w = gray.shape
    mask = _foreground_mask(gray)

    # usa so a faixa central de linhas pra projecao: evita que uma borda
    # horizontal (moldura da caixa dos digitos) preencha a coluna inteira e
    # "cole" todas as celulas numa unica run.
    y0, y1 = int(h * 0.25), int(h * 0.85)
    banda = mask[y0:y1, :] if y1 > y0 else mask
    col_content = banda.sum(axis=0) / 255
    limiar_coluna = max(1, int((y1 - y0) * 0.12))
    col_has_content = col_content > limiar_coluna
    min_gap = max(1, int(w * 0.008))

    # acha runs contiguos de colunas com conteudo (candidatos a celula)
    runs = []
    start = None
    gap = 0
    for x in range(w):
        if col_has_content[x]:
            if start is None:
                start = x
            gap = 0
        else:
            if start is not None:
                gap += 1
                if gap > min_gap:
                    runs.append((start, x - gap))
                    start = None
                    gap = 0
    if start is not None:
        runs.append((start, w - 1))

    # descarta runs muito estreitos (ruido) antes de contar
    min_cell_w = max(2, int(w * min_cell_frac))
    runs = [r for r in runs if (r[1] - r[0]) >= min_cell_w]

    if len(runs) != n_expected:
        return None

    # celulas de digito num contador mecanico tem largura bem parecida entre
    # si; se uma run ficou muito mais larga/estreita que as outras, e sinal
    # de que a projecao colou/partiu digitos errado (mesmo contando o numero
    # certo de runs por coincidencia) -- mais seguro descartar a amostra do
    # que arriscar rotulo errado.
    larguras = [x1 - x0 for (x0, x1) in runs]
    media = sum(larguras) / len(larguras)
    if media <= 0:
        return None
    if max(larguras) / media > 1.6 or min(larguras) / media < 0.6:
        return None

    cells = []
    pad = max(1, int(h * 0.05))
    for (x0, x1) in runs:
        x0p = max(0, x0 - pad)
        x1p = min(w, x1 + pad)
        cell = gray[:, x0p:x1p]
        cells.append(cell)
    return cells


def rectify_from_mask(image_bgr, mask_gray, out_height=64):
    """Usa a mascara (retangulo rotacionado) pra retificar a regiao
    correspondente da imagem original numa tira horizontal. Retorna None se a
    mascara estiver vazia/pequena demais."""
    _, mask_bin = cv2.threshold(mask_gray, 127, 255, cv2.THRESH_BINARY)
    contours, _ = cv2.findContours(mask_bin, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    largest = max(contours, key=cv2.contourArea)
    if cv2.contourArea(largest) < 200:
        return None

    rect = cv2.minAreaRect(largest)
    (cx, cy), (rw, rh), angle = rect
    if rw < rh:
        rw, rh = rh, rw
        angle += 90

    box = cv2.boxPoints(((cx, cy), (rw, rh), angle))
    box = order_points(box)

    out_w = int(round(out_height * (rw / rh))) if rh > 0 else 0
    if out_w < out_height or out_w > out_height * 30:
        return None

    dst = np.array([
        [0, 0],
        [out_w - 1, 0],
        [out_w - 1, out_height - 1],
        [0, out_height - 1],
    ], dtype=np.float32)

    M = cv2.getPerspectiveTransform(box.astype(np.float32), dst)
    strip = cv2.warpPerspective(image_bgr, M, (out_w, out_height))
    return strip


def order_points(pts):
    """Ordena 4 pontos como (top-left, top-right, bottom-right, bottom-left)."""
    pts = np.array(pts, dtype=np.float32)
    s = pts.sum(axis=1)
    diff = np.diff(pts, axis=1).flatten()
    tl = pts[np.argmin(s)]
    br = pts[np.argmax(s)]
    tr = pts[np.argmin(diff)]
    bl = pts[np.argmax(diff)]
    return np.array([tl, tr, br, bl], dtype=np.float32)


def segment_cells_iguais(strip_bgr, n):
    """Divisao em N fatias de largura igual (sem deteccao de vao). Usado
    apenas para as fotos de dominio, onde a caixa ja foi recortada/alinhada
    manualmente e a divisao por projecao se mostrou pouco confiavel nesses
    exemplos ruidosos/rotacionados."""
    gray = cv2.cvtColor(strip_bgr, cv2.COLOR_BGR2GRAY) if strip_bgr.ndim == 3 else strip_bgr
    h, w = gray.shape
    cells = []
    for i in range(n):
        x0 = int(w * i / n)
        x1 = int(w * (i + 1) / n)
        cells.append(gray[:, x0:x1])
    return cells


def save_digit_crops(cells, label, out_dir, prefix, size=(28, 28)):
    """Salva cada celula redimensionada em dataset/digits/<digito>/<prefix>_<i>.png."""
    for i, (cell, ch) in enumerate(zip(cells, label)):
        class_dir = os.path.join(out_dir, ch)
        os.makedirs(class_dir, exist_ok=True)
        resized = cv2.resize(cell, size, interpolation=cv2.INTER_AREA)
        cv2.imwrite(os.path.join(class_dir, f"{prefix}_{i}.png"), resized)
