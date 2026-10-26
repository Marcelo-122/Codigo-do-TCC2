"""Gera, para cada foto de `dados/teste/imagens/`, o quadro 160×120 que o pipeline vê, ampliado e com uma
grade de coordenadas, para ler a olho a `caixa` (x0,y0,x1,y1) da janela dos dígitos. Se a foto já tem `caixa`
em `rotulos.csv`, o retângulo aparece em verde (conferência). Saída em `dados/teste/grades/`.

Uso (na raiz do repositório):  python dados/gerar_grades.py
"""
import csv
import os
import sys

import cv2
import numpy as np

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(AQUI), "ocr"))
from pipeline_nuvem import CAM_H, CAM_W, para_quadro_camera  # noqa: E402

DIR_TESTE = os.path.join(AQUI, "teste")
SAIDA = os.path.join(DIR_TESTE, "grades")
ESCALA = 6
PASSO = 10  # pixels do quadro entre linhas da grade


def main():
    os.makedirs(SAIDA, exist_ok=True)
    with open(os.path.join(DIR_TESTE, "rotulos.csv"), encoding="utf-8") as f:
        linhas = [l for l in csv.DictReader(f) if l["arquivo"].strip()]
    for l in linhas:
        bruto = cv2.imdecode(np.fromfile(os.path.join(DIR_TESTE, "imagens", l["arquivo"]), np.uint8), cv2.IMREAD_COLOR)
        centro_y = int(l["centro_y"]) if l["centro_y"].strip() else None
        quadro = para_quadro_camera(bruto, centro_y)
        img = cv2.cvtColor(cv2.resize(quadro, None, fx=ESCALA, fy=ESCALA, interpolation=cv2.INTER_NEAREST),
                           cv2.COLOR_GRAY2BGR)
        for x in range(0, CAM_W, PASSO):
            cv2.line(img, (x * ESCALA, 0), (x * ESCALA, CAM_H * ESCALA), (255, 160, 0), 1)
            cv2.putText(img, str(x), (x * ESCALA + 2, 11), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 220, 255), 1)
        for y in range(0, CAM_H, PASSO):
            cv2.line(img, (0, y * ESCALA), (CAM_W * ESCALA, y * ESCALA), (255, 160, 0), 1)
            cv2.putText(img, str(y), (2, y * ESCALA + 11), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 220, 255), 1)
        if l["caixa"].strip():
            x0, y0, x1, y1 = (int(v) * ESCALA for v in l["caixa"].split(","))
            cv2.rectangle(img, (x0, y0), (x1 + ESCALA - 1, y1 + ESCALA - 1), (0, 255, 0), 1)
        destino = os.path.join(SAIDA, os.path.splitext(l["arquivo"])[0] + ".png")
        cv2.imencode(".png", img)[1].tofile(destino)
    print(f"{len(linhas)} grades em {os.path.relpath(SAIDA, os.path.dirname(AQUI))}")


if __name__ == "__main__":
    main()
