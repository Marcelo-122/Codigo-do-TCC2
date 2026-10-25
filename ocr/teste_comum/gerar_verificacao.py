"""Gera folhas de conferência do gabarito: o recorte da faixa dos dígitos de cada imagem de
`imagens/`, com a leitura do `gabarito.csv` escrita por cima (verde = confiança alta, laranja =
média). Serve para conferir a olho se o gabarito bate com a foto. Saída em `verificacao/`.

Uso (na raiz do repositório):  python ocr/teste_comum/gerar_verificacao.py
"""
import csv
import os

import cv2
import numpy as np

AQUI = os.path.dirname(os.path.abspath(__file__))
SAIDA = os.path.join(AQUI, "verificacao")
Y0, ALTURA = 150, 190  # faixa vertical (na foto já girada pelo EXIF, 480x640) onde ficam os dígitos
POR_FOLHA = 8

os.makedirs(SAIDA, exist_ok=True)
with open(os.path.join(AQUI, "gabarito.csv"), encoding="utf-8") as f:
    linhas = list(csv.DictReader(f))

blocos = []
for r in linhas:
    caminho = os.path.join(AQUI, "imagens", r["arquivo"])
    img = cv2.imdecode(np.fromfile(caminho, np.uint8), cv2.IMREAD_COLOR)  # o OpenCV aplica o EXIF
    faixa = img[Y0:Y0 + ALTURA].copy()
    cor = (0, 255, 0) if r["confianca"] == "alta" else (0, 140, 255)
    cv2.rectangle(faixa, (0, 0), (400, 34), (0, 0, 0), -1)
    num = r["arquivo"].split("_")[-1][:-4]
    cv2.putText(faixa, f"{num}: {r['leitura']} ({r['confianca']})", (6, 26),
                cv2.FONT_HERSHEY_SIMPLEX, 0.85, cor, 2)
    blocos.append(faixa)

for i in range(0, len(blocos), POR_FOLHA):
    parte = blocos[i:i + POR_FOLHA]
    while len(parte) % 2:
        parte.append(np.zeros_like(parte[0]))
    folha = np.vstack([np.hstack(parte[j:j + 2]) for j in range(0, len(parte), 2)])
    destino = os.path.join(SAIDA, f"folha_{i // POR_FOLHA + 1:02d}.jpg")
    cv2.imencode(".jpg", folha, [cv2.IMWRITE_JPEG_QUALITY, 88])[1].tofile(destino)
    print(destino)
