"""
Mede o tempo de inferencia do OCR no servidor (fluxo em nuvem), que a latencia ponta a
ponta nao inclui: o OCR da nuvem roda depois, sobre as imagens salvas pelo reconstrutor.py.

Roda o ocr/pipeline_nuvem.py (mesmos .tflite INT8 do firmware, LiteRT sem XNNPACK) em
cada imagem completa de medicoes/imagens/ (as ..._parcial.jpg ficam de fora), --repeticoes
vezes por imagem, e imprime mediana, minimo e maximo de:
  leitura completa   decodificacao do JPEG + segmentacao + digitos
  segmentacao        so o modelo de localizacao (t_seg_ms do LeitorB)
  ROI fixa           decodificacao + digitos, com a caixa prevista na mesma imagem
                     (o caso da instalacao com a janela calibrada, sem segmentacao)

  python medicoes/tempo_inferencia_nuvem.py
  python medicoes/tempo_inferencia_nuvem.py --digitos 6 --repeticoes 5

Medido em 2026-11-01 (Ryzen 5 5600GT, WSL, Python 3.14, ai-edge-litert 2.3.0), 21 imagens
x 5 repeticoes: leitura completa 6,25 ms, segmentacao 4,30 ms, ROI fixa 1,91 ms (medianas).
O tempo depende da maquina: rode de novo e registre a CPU junto com o resultado.
"""
import argparse
import glob
import os
import platform
import statistics as st
import sys
import time

import cv2
import numpy as np

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(AQUI)
sys.path.insert(0, os.path.join(RAIZ, "ocr"))
from pipeline_nuvem import LeitorB  # noqa: E402


def resumo(nome, v):
    print(f"{nome:<18} mediana {st.median(v):7.2f} ms   min {min(v):7.2f}   max {max(v):7.2f}   n={len(v)}")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--imagens", default=os.path.join(AQUI, "imagens"), help="pasta com os JPEGs recebidos")
    p.add_argument("--digitos", type=int, default=6, help="numero de roletes (N_FATIAS do firmware)")
    p.add_argument("--repeticoes", type=int, default=5)
    a = p.parse_args()

    arquivos = sorted(f for f in glob.glob(os.path.join(a.imagens, "*.jpg")) if "parcial" not in f)
    if not arquivos:
        sys.exit(f"Nenhuma imagem completa em {a.imagens}")

    leitor = LeitorB()
    t_completa, t_seg, t_roi = [], [], []
    for f in arquivos:
        dados = np.fromfile(f, np.uint8)
        for _ in range(a.repeticoes):
            t0 = time.perf_counter()
            quadro = cv2.imdecode(dados, cv2.IMREAD_GRAYSCALE)
            r = leitor.ler(quadro, a.digitos)
            t_completa.append((time.perf_counter() - t0) * 1e3)
            t_seg.append(r["t_seg_ms"])
            if r["caixa"] is None:  # sem caixa prevista nao ha ROI para cronometrar
                continue
            t0 = time.perf_counter()
            quadro = cv2.imdecode(dados, cv2.IMREAD_GRAYSCALE)
            leitor.ler(quadro, a.digitos, caixa=r["caixa"])
            t_roi.append((time.perf_counter() - t0) * 1e3)

    print(f"{len(arquivos)} imagens x {a.repeticoes} repeticoes; {platform.processor() or platform.machine()}, "
          f"Python {platform.python_version()}")
    resumo("leitura completa", t_completa)
    resumo("segmentacao", t_seg)
    if t_roi:
        resumo("ROI fixa", t_roi)


if __name__ == "__main__":
    main()
