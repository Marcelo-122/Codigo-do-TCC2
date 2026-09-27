import os
import csv
import cv2
import numpy as np

DIRETORIO_ATUAL = os.path.dirname(os.path.abspath(__file__))
DIR_DRYAD = os.path.join(
    DIRETORIO_ATUAL, "dataset", "Word-Wheel_Water_Meter_Dataset",
    "Word-Wheel_Water_Meter_Dataset", "recognition",
)
DIR_OUT = os.path.join(DIRETORIO_ATUAL, "dataset", "digits")

# (subpasta, prefixo do nome do arquivo no csv/imagens, numero de digitos)
CONJUNTOS = [
    ("recognition_5-digit/train", "5-digit_train", 5),
    ("recognition_5-digit/test", "5-digit_test", 5),
    ("recognition_6-digit/train", "6-digit_train", 6),
    ("recognition_6-digit/test", "6-digit_test", 6),
]


def segment_cells_iguais(strip_bgr, n):
    gray = cv2.cvtColor(strip_bgr, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    return [gray[:, int(w * i / n):int(w * (i + 1) / n)] for i in range(n)]


def main():
    os.makedirs(DIR_OUT, exist_ok=True)
    aceitas = 0
    rejeitadas_halfword = 0
    rejeitadas_leitura = 0
    contagem_classes = {str(d): 0 for d in range(10)}

    for subpasta, prefixo, n_digitos in CONJUNTOS:
        base = os.path.join(DIR_DRYAD, subpasta)
        csv_path = os.path.join(base, f"{prefixo}_rec_label_CSV.csv")
        img_dir = os.path.join(base, f"{prefixo}_img")

        with open(csv_path, newline="", encoding="utf-8") as f:
            linhas = list(csv.reader(f))

        for linha in linhas:
            nome_img, rotulo, reversed_flag, halfword_flag = linha[0], linha[1], linha[2], linha[3]

            if halfword_flag == "1":
                rejeitadas_halfword += 1
                continue
            if len(rotulo) != n_digitos:
                rejeitadas_leitura += 1
                continue

            caminho = os.path.join(img_dir, nome_img)
            img = cv2.imread(caminho)
            if img is None:
                rejeitadas_leitura += 1
                continue

            if reversed_flag == "1":
                # a imagem foi capturada/recortada espelhada horizontalmente
                # (ordem E desenho dos digitos invertidos); espelhar de volta
                # resolve as duas coisas de uma vez.
                img = cv2.flip(img, 1)

            celulas = segment_cells_iguais(img, n_digitos)
            prefixo_arquivo = f"dryad_{prefixo.replace('/', '_')}_{os.path.splitext(nome_img)[0]}"
            for i, (celula, digito) in enumerate(zip(celulas, rotulo)):
                pasta_classe = os.path.join(DIR_OUT, digito)
                os.makedirs(pasta_classe, exist_ok=True)
                redimensionada = cv2.resize(celula, (28, 28), interpolation=cv2.INTER_AREA)
                cv2.imwrite(os.path.join(pasta_classe, f"{prefixo_arquivo}_{i}.png"), redimensionada)
                contagem_classes[digito] += 1
            aceitas += 1

    print(f"Imagens aceitas (halfword=0): {aceitas}")
    print(f"Rejeitadas por halfword=1: {rejeitadas_halfword}")
    print(f"Rejeitadas por leitura/tamanho: {rejeitadas_leitura}")
    print("Recortes de digito gerados por classe:")
    for d in sorted(contagem_classes):
        print(f"  {d}: {contagem_classes[d]}")
    print(f"Total de recortes: {sum(contagem_classes.values())}")


if __name__ == "__main__":
    main()
