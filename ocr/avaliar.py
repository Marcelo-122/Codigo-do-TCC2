"""Avalia o Pipeline B nos dois fluxos (borda emulada e nuvem) sobre o conjunto de teste comum.

Lê `ocr/teste_comum/gabarito.csv` (imagem, leitura real, número de rodinhas, altura da janela) e,
para cada imagem de `ocr/teste_comum/imagens/` (fotos tiradas com a ESP32-CAM de um monitor mostrando o
medidor; EXIF 8, chegam em retrato 480×640), recorta uma faixa 4:3 em torno da janela dos dígitos,
reduz para 160×120 em cinza e roda:

  borda : quadro 160×120 cinza lido direto (o que o firmware veria);
  nuvem : o mesmo quadro depois de JPEG q90 (o que o servidor recebe pelo enlace), mesma leitura.

Os dois usam os mesmos modelos e a mesma lógica (`ocr/pipeline_nuvem.py`). A "borda" aqui é uma
EMULAÇÃO em Python: o quadro 160×120 vem da redução da foto 640×480, não do sensor, e os kernels
são os de referência do TFLite, não a TFLM do ESP32. O enquadramento (`centro_y` do gabarito) foi
escolhido à mão, como o ajuste físico da câmera que o firmware de debug serve para fazer. Serve para
comparar os dois fluxos entre si, não para medir a acurácia absoluta no hardware.

Há ainda dois modos de DIAGNÓSTICO (`*_caixa_manual`) que pulam a segmentação e usam a caixa da janela
marcada à mão (`caixa_manual` do gabarito): mostram quanto o fatiamento + classificador acertariam se a
segmentação acertasse a janela.

Saída em `ocr/teste_comum/resultados/`: resultados.csv, RESULTADOS.md e folhas JPEG com a caixa e as fatias
desenhadas (`caixas_nuvem_NN.jpg`: segmentação do modelo; `caixas_nuvem_alinhada_caixa_manual_NN.jpg`: caixa manual
sobre o quadro endireitado).

Uso (na raiz do repositório):  python ocr/avaliar.py
"""
import csv
import math
import os
import sys

import cv2
import numpy as np

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
from pipeline_nuvem import (LeitorB, alinhar, desenhar, girar_caixa, para_quadro_camera,  # noqa: E402
                            transmitir_como_jpeg)

try:
    sys.path.insert(0, os.path.dirname(AQUI))
    from enlace import CHUNK_DATA_SIZE
except Exception:  # enlace.py puxa configuração do .env; se faltar, usa o valor do firmware
    CHUNK_DATA_SIZE = 175

DIR_TESTE = os.path.join(AQUI, "teste_comum")
DIR_SAIDA = os.path.join(DIR_TESTE, "resultados")
MODOS = ("borda", "nuvem", "borda_caixa_manual", "nuvem_caixa_manual", "nuvem_alinhada", "nuvem_alinhada_caixa_manual")


def ler_gabarito():
    with open(os.path.join(DIR_TESTE, "gabarito.csv"), encoding="utf-8") as f:
        return list(csv.DictReader(f))


def digitos_certos(real, lido):
    return sum(a == b for a, b in zip(real, lido))


def montar_folhas(blocos, destino_base, por_folha=12, colunas=4):
    for i in range(0, len(blocos), por_folha):
        parte = blocos[i:i + por_folha]
        while len(parte) % colunas:
            parte.append(np.zeros_like(parte[0]))
        folha = np.vstack([np.hstack(parte[j:j + colunas]) for j in range(0, len(parte), colunas)])
        cv2.imencode(".jpg", folha, [cv2.IMWRITE_JPEG_QUALITY, 85])[1].tofile(f"{destino_base}_{i // por_folha + 1:02d}.jpg")


def main():
    os.makedirs(DIR_SAIDA, exist_ok=True)
    gabarito = ler_gabarito()
    leitor = LeitorB()
    linhas = []
    blocos = {m: [] for m in MODOS}

    for g in gabarito:
        bruto = cv2.imdecode(np.fromfile(os.path.join(DIR_TESTE, "imagens", g["arquivo"]), np.uint8), cv2.IMREAD_COLOR)
        quadro = para_quadro_camera(bruto, int(g["centro_y"]))
        n = int(g["n_digitos"])
        for modo in MODOS:
            entrada, tamanho_jpeg = (quadro, None) if modo.startswith("borda") else transmitir_como_jpeg(quadro)
            manual = tuple(int(v) for v in g["caixa_manual"].split(",")) if modo.endswith("caixa_manual") else None
            if "alinhada" in modo:  # o servidor endireita o quadro recebido (ângulo estimado por Hough, sem a caixa)
                entrada, angulo = alinhar(entrada)
                manual = girar_caixa(manual, angulo) if manual else None
            r = leitor.ler(entrada, n, caixa=manual)
            real = g["leitura"]
            caixa = r["caixa"]
            linhas.append({
                "arquivo": g["arquivo"], "medidor": g["medidor"], "confianca": g["confianca"], "modo": modo,
                "leitura_real": real, "leitura_lida": r["leitura"], "exato": int(r["leitura"] == real),
                "digitos_certos": digitos_certos(real, r["leitura"]), "n_digitos": n,
                "caixa": "" if caixa is None else "{},{},{},{}".format(*caixa),
                "caixa_largura": "" if caixa is None else caixa[2] - caixa[0],
                "caixa_altura": "" if caixa is None else caixa[3] - caixa[1],
                "bytes_jpeg": tamanho_jpeg or "",
                "pacotes_lora": math.ceil(tamanho_jpeg / CHUNK_DATA_SIZE) if tamanho_jpeg else "",
                "t_seg_ms": round(r["t_seg_ms"]), "t_dig_ms": round(r["t_dig_ms"]),
            })
            img = desenhar(entrada, caixa, n, escala=3)
            cor = (0, 200, 0) if r["leitura"] == real else (0, 0, 255)
            cv2.rectangle(img, (0, 0), (img.shape[1], 22), (0, 0, 0), -1)
            cv2.putText(img, f"{g['arquivo'].split('_')[-1][:-4]} {real}>{r['leitura']}", (3, 17),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, cor, 1)
            blocos[modo].append(img)

    campos = list(linhas[0].keys())
    with open(os.path.join(DIR_SAIDA, "resultados.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=campos)
        w.writeheader()
        w.writerows(linhas)
    for modo in ("nuvem", "nuvem_alinhada_caixa_manual"):  # as demais seriam quase idênticas a estas
        montar_folhas(blocos[modo], os.path.join(DIR_SAIDA, f"caixas_{modo}"))

    escrever_resumo(linhas)
    print(open(os.path.join(DIR_SAIDA, "RESULTADOS.md"), encoding="utf-8").read())


def taxa(linhas, campo="exato"):
    return sum(int(l[campo]) for l in linhas), len(linhas)


def escrever_resumo(linhas):
    por_modo = {m: [l for l in linhas if l["modo"] == m] for m in MODOS}
    out = ["# Resultados: Pipeline B, borda emulada × nuvem", "",
           "Gerado por `ocr/avaliar.py`. Conjunto: `ocr/teste_comum/` (fotos da ESP32-CAM de um monitor).",
           "A borda é uma **emulação** em Python (ver o docstring de `ocr/avaliar.py`); os números",
           "comparam os dois fluxos entre si e **não** são a acurácia no hardware.", ""]

    out += ["## Resumo", "",
            "Os fluxos `*_caixa_manual` são **diagnóstico**: pulam a segmentação e usam a caixa marcada à mão. "
            "Os `*_alinhada` endireitam o quadro no servidor antes de ler (ângulo estimado sem a caixa).", "",
            "| Fluxo | Leituras exatas | Dígitos certos | Sem caixa | Caixa mediana (L×A, de 160×120) |", "|---|---|---|---|---|"]
    for m in MODOS:
        ls = por_modo[m]
        ex, n = taxa(ls)
        dc = sum(l["digitos_certos"] for l in ls)
        dt = sum(l["n_digitos"] for l in ls)
        semcx = sum(1 for l in ls if l["caixa"] == "")
        com = [l for l in ls if l["caixa"] != ""]
        cx = (f"{int(np.median([l['caixa_largura'] for l in com]))}×{int(np.median([l['caixa_altura'] for l in com]))}"
              if com else "-")
        out.append(f"| {m} | {ex}/{n} ({100 * ex / n:.0f} %) | {dc}/{dt} ({100 * dc / dt:.0f} %) | {semcx} | {cx} |")

    nuvem = por_modo["nuvem"]
    kb = [l["bytes_jpeg"] for l in nuvem]
    out += ["", "## Custo de transmissão", "",
            f"Imagem JPEG q90 remontada no servidor: mediana {int(np.median(kb))} bytes "
            f"({min(kb)}–{max(kb)}), {int(np.median([l['pacotes_lora'] for l in nuvem]))} pacotes LoRa de "
            f"{CHUNK_DATA_SIZE} bytes. A borda enviaria só a leitura (poucos bytes, 1 pacote).", ""]

    out += ["## Por medidor", "", "| Medidor | Fluxo | Leituras exatas | Dígitos certos |", "|---|---|---|---|"]
    for med in sorted({l["medidor"] for l in linhas}):
        for m in MODOS:
            ls = [l for l in por_modo[m] if l["medidor"] == med]
            ex, n = taxa(ls)
            dc, dt = sum(l["digitos_certos"] for l in ls), sum(l["n_digitos"] for l in ls)
            out.append(f"| {med} | {m} | {ex}/{n} | {dc}/{dt} ({100 * dc / dt:.0f} %) |")

    out += ["", "## Por confiança do gabarito", "", "| Confiança | Fluxo | Leituras exatas |", "|---|---|---|"]
    for conf in ("alta", "media"):
        for m in MODOS:
            ls = [l for l in por_modo[m] if l["confianca"] == conf]
            if ls:
                ex, n = taxa(ls)
                out.append(f"| {conf} | {m} | {ex}/{n} |")

    out += ["", "## Concordância borda × nuvem", ""]
    b, n_ = por_modo["borda"], por_modo["nuvem"]
    igual = sum(1 for x, y in zip(b, n_) if x["leitura_lida"] == y["leitura_lida"])
    out.append(f"Leitura idêntica nos dois fluxos em {igual}/{len(b)} imagens.")

    cm, am = por_modo["nuvem_caixa_manual"], por_modo["nuvem_alinhada_caixa_manual"]
    out += ["", "## Por imagem", "",
            "| Imagem | Real | Lido (borda) | Lido (nuvem) | Caixa da segmentação (nuvem) | Lido (caixa manual) | Lido (alinhada, caixa manual) |",
            "|---|---|---|---|---|---|---|"]
    for x, y, z, w in zip(b, n_, cm, am):
        out.append(f"| {x['arquivo'].split('_')[-1][:-4]} | {x['leitura_real']} | {x['leitura_lida']} | "
                   f"{y['leitura_lida']} | {y['caixa'] or '-'} | {z['leitura_lida']} | {w['leitura_lida']} |")
    out += ["", "As imagens com a caixa e as fatias desenhadas estão em `caixas_nuvem_*.jpg` (segmentação do modelo) e `caixas_nuvem_alinhada_caixa_manual_*.jpg` (caixa manual, quadro endireitado)."]
    with open(os.path.join(DIR_SAIDA, "RESULTADOS.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")


if __name__ == "__main__":
    main()
