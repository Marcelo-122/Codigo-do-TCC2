import os
import csv
import cv2
import numpy as np
from PIL import Image

from digitos_comum import segment_cells_iguais, save_digit_crops

DIRETORIO_ATUAL = os.path.dirname(os.path.abspath(__file__))
# pasta pessoal usada nas primeiras fotos de teste (cartaz estatico); nao ha
# nenhuma linha "cartaz" em dominio_labels.csv atualmente, entao isso fica
# sem uso -- ajuste se reativar esse conjunto.
DIR_CARTAZ = r"E:\lição\7° Semestre\TCC I\imagens"
DIR_CAMPO = os.path.join(DIRETORIO_ATUAL, "Imagens")
DIR_OUT = os.path.join(DIRETORIO_ATUAL, "dataset", "digits_domain")
LABELS_CSV = os.path.join(DIRETORIO_ATUAL, "dominio_labels.csv")

# Caixa (x0,y0,x1,y1) no espaco ORIGINAL da foto, angulo de rotacao (graus,
# sentido anti-horario, igual ao PIL Image.rotate) e recorte fino
# (x0,y0,x1,y1) no espaco JA ROTACIONADO -- encontrados manualmente
# conferindo cada foto (fotos reais da ESP32CAM tiradas em angulos
# variados, sem mascara de referencia disponivel). Usa-se PIL (nao cv2) pra
# carregar/recortar/rotacionar, pois foi com PIL que essas coordenadas
# foram calibradas visualmente.
RECORTES_MANUAIS = {
    "imagem_capturada_15.jpg": ((100, 120, 240, 445), 90, (0, 15, 325, 110)),
    "imagem_capturada_16.jpg": ((100, 120, 240, 445), 90, (0, 15, 325, 110)),
    "imagem_capturada_22.jpg": ((285, 100, 460, 460), 90, (0, 90, 360, 150)),
}


def extrair_tira(im_pil, nome_arquivo):
    if nome_arquivo not in RECORTES_MANUAIS:
        return None
    caixa, angulo, caixa_fina = RECORTES_MANUAIS[nome_arquivo]

    recorte = im_pil.crop(caixa)
    if angulo:
        recorte = recorte.rotate(angulo, expand=True)
    recorte = recorte.crop(caixa_fina)

    arr_rgb = np.array(recorte.convert("RGB"))
    return cv2.cvtColor(arr_rgb, cv2.COLOR_RGB2BGR)


def main():
    os.makedirs(DIR_OUT, exist_ok=True)

    with open(LABELS_CSV, newline="", encoding="utf-8") as f:
        linhas = list(csv.DictReader(f))

    aceitas = 0
    rejeitadas = 0
    relatorio = []
    amostras_preview = {}

    for linha in linhas:
        origem = linha["source"]
        nome = linha["filename"]
        rotulo = linha["label"]
        base_dir = DIR_CARTAZ if origem == "cartaz" else DIR_CAMPO
        caminho = os.path.join(base_dir, nome)

        try:
            im_pil = Image.open(caminho)
        except (FileNotFoundError, OSError):
            rejeitadas += 1
            relatorio.append([origem, nome, "rejeitada", "arquivo_nao_lido", rotulo])
            continue

        tira = extrair_tira(im_pil, nome)
        if tira is None or tira.size == 0:
            rejeitadas += 1
            relatorio.append([origem, nome, "rejeitada", "sem_recorte_manual", rotulo])
            continue

        cells = segment_cells_iguais(tira, len(rotulo))
        prefix = f"{origem}_{os.path.splitext(nome)[0]}"
        save_digit_crops(cells, rotulo, DIR_OUT, prefix)
        aceitas += 1
        relatorio.append([origem, nome, "aceita", "", rotulo])

        for ch, cell in zip(rotulo, cells):
            if ch not in amostras_preview:
                amostras_preview[ch] = cv2.resize(cell, (28, 28))

    relatorio_path = os.path.join(DIRETORIO_ATUAL, "dataset", "digits_domain_report.csv")
    with open(relatorio_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["source", "arquivo", "status", "motivo_rejeicao", "rotulo"])
        w.writerows(relatorio)

    if amostras_preview:
        digitos_ordenados = sorted(amostras_preview.keys())
        tiles = [amostras_preview[d] for d in digitos_ordenados]
        preview = cv2.hconcat(tiles)
        cv2.imwrite(os.path.join(DIRETORIO_ATUAL, "dataset", "digits_domain_preview.png"), preview)

    total = aceitas + rejeitadas
    print(f"Total de fotos de dominio processadas: {total}")
    print(f"Aceitas: {aceitas} ({100 * aceitas / max(total, 1):.1f}%)")
    print(f"Rejeitadas: {rejeitadas}")
    print(f"Relatorio: {relatorio_path}")


if __name__ == "__main__":
    main()
