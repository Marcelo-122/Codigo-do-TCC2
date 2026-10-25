"""Cenário de enquadramento físico fixo: a janela dos dígitos fica numa região conhecida, sem segmentação.

Numa instalação real a câmera fica parada diante do medidor, então a janela cai sempre mais ou menos no mesmo
lugar do quadro 160×120. Este script mede a leitura nesse cenário SEM usar a caixa de cada foto:

  1. por medidor (`branco5`, `tianjin6`) o recorte da foto em retrato é FIXO (mesma faixa 4:3 para todas as
     fotos do medidor, a mediana dos `centro_y` do gabarito);
  2. a região da janela (ROI) é calibrada UMA vez, com as fotos de uma leitura (o "grupo de calibração"), e
     usada em todas as fotos das OUTRAS leituras do mesmo medidor;
  3. repete-se com cada leitura como grupo de calibração e reporta-se a média, o pior e o melhor caso.

Como a foto do monitor muda de zoom e de posição de uma leitura para outra, o erro da ROI aqui é maior do que
numa câmera realmente parada: os números são um cenário pessimista para o enquadramento fixo, e um limite
inferior do que uma montagem mecânica boa daria. O erro médio da ROI é impresso junto.

Variantes: sem alinhar / alinhada (Hough, no servidor) e, com ou sem votação entre 5 caixas deslocadas.
Todas passam pelo JPEG q90 (fluxo nuvem).

Como as fotos não vêm de uma montagem fixa, o script também mede a TOLERÂNCIA: parte da caixa verdadeira de cada
foto (quadro alinhado) e soma um erro aleatório uniforme de ±d px a cada coordenada, com e sem votação. A curva
diz quanto erro de posição da ROI a leitura aguenta, isto é, que precisão a montagem precisa ter.

Saída: ocr/teste_comum/resultados/ROI_FIXA.md. Uso (na raiz do repositório):  python ocr/avaliar_roi_fixa.py
"""
import csv
import os
import sys
from collections import defaultdict

import cv2
import numpy as np

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
from pipeline_nuvem import (CAM_W, LeitorB, alinhar, girar_caixa, para_quadro_camera, topo_da_faixa,  # noqa: E402
                            transmitir_como_jpeg)

DIR_TESTE = os.path.join(AQUI, "teste_comum")
DESLOCAMENTOS = ((0, 0), (-2, 0), (2, 0), (0, -1), (0, 1))
VARIANTES = (("sem alinhar", False, False), ("alinhada", True, False), ("alinhada + votação", True, True))


def main():
    with open(os.path.join(DIR_TESTE, "gabarito.csv"), encoding="utf-8") as f:
        gab = list(csv.DictReader(f))
    leitor = LeitorB()
    saida = ["# Cenário de enquadramento fixo (sem segmentação)", "",
             "Gerado por `ocr/avaliar_roi_fixa.py`; protocolo no docstring do script. Fluxo nuvem (JPEG q90).", ""]

    familias = defaultdict(list)
    for g in gab:
        familias[g["medidor"]].append(g)

    resumo = []
    for medidor, linhas in sorted(familias.items()):
        centro_fixo = int(np.median([int(g["centro_y"]) for g in linhas]))
        quadros, frames = {}, []
        for g in linhas:
            bruto = cv2.imdecode(np.fromfile(os.path.join(DIR_TESTE, "imagens", g["arquivo"]), np.uint8), cv2.IMREAD_COLOR)
            h, w = bruto.shape[:2]
            esc = w / CAM_W
            topo_g, _ = topo_da_faixa(h, w, int(g["centro_y"]))
            topo_f, _ = topo_da_faixa(h, w, centro_fixo)
            dy = (topo_g - topo_f) / esc                     # a caixa de cada grupo, no quadro de recorte fixo
            x0, y0, x1, y1 = (int(v) for v in g["caixa_manual"].split(","))
            verdadeira = (x0, int(round(y0 + dy)), x1, int(round(y1 + dy)))
            q, _ = transmitir_como_jpeg(para_quadro_camera(bruto, centro_fixo))
            frames.append({"g": g, "q": q, "verdadeira": verdadeira, "n": int(g["n_digitos"])})
        leituras = sorted({f["g"]["leitura"] for f in frames})

        # prepara cada variante: quadro (alinhado ou não), caixa verdadeira nesse quadro
        prep = {}
        for nome, usa_alinhar, _ in VARIANTES:
            prep[nome] = []
            for f in frames:
                if usa_alinhar:
                    q, ang = alinhar(f["q"])
                    prep[nome].append((q, girar_caixa(f["verdadeira"], ang)))
                else:
                    prep[nome].append((f["q"], f["verdadeira"]))

        saida += [f"## Medidor `{medidor}` ({len(frames)} fotos, {len(leituras)} leituras, recorte fixo em y={centro_fixo})", "",
                  "| Variante | ROI | Leituras exatas | Dígitos certos | Pior / melhor calibração (leituras) | Erro médio da ROI (px) |",
                  "|---|---|---|---|---|---|"]
        for nome, _, vota in VARIANTES:
            desl = DESLOCAMENTOS if vota else ((0, 0),)
            # (a) oráculo: a caixa verdadeira de cada foto (limite superior desta variante)
            ex = dg = tot = 0
            for (q, vb), f in zip(prep[nome], frames):
                lido = leitor.ler(q, f["n"], caixa=vb, deslocamentos=desl)["leitura"]
                real = f["g"]["leitura"]
                ex += lido == real
                dg += sum(a == b for a, b in zip(real, lido))
                tot += f["n"]
            saida.append(f"| {nome} | caixa verdadeira de cada foto (oráculo) | {ex}/{len(frames)} ({100 * ex / len(frames):.0f} %) "
                         f"| {dg}/{tot} ({100 * dg / tot:.0f} %) | - | 0 |")
            # (b) ROI única = mediana das caixas verdadeiras da família (calibração com todas as leituras)
            med = tuple(int(round(np.median([vb[k] for _, vb in prep[nome]]))) for k in range(4))
            ex = dg = tot = 0
            erros = []
            for (q, vb), f in zip(prep[nome], frames):
                lido = leitor.ler(q, f["n"], caixa=med, deslocamentos=desl)["leitura"]
                real = f["g"]["leitura"]
                ex += lido == real
                dg += sum(a == b for a, b in zip(real, lido))
                tot += f["n"]
                erros.append(np.mean(np.abs(np.array(vb) - np.array(med))))
            saida.append(f"| {nome} | mediana de todas as leituras {med} | {ex}/{len(frames)} ({100 * ex / len(frames):.0f} %) "
                         f"| {dg}/{tot} ({100 * dg / tot:.0f} %) | - | {np.mean(erros):.1f} |")
            # (c) calibra com UMA leitura e testa nas outras
            taxas, tx_dig, erros = [], [], []
            ex_t = dg_t = tot_t = n_t = 0
            for cal in leituras:
                idx_cal = next(i for i, f in enumerate(frames) if f["g"]["leitura"] == cal)
                roi = prep[nome][idx_cal][1]
                ex = dg = tot = n = 0
                for (q, vb), f in zip(prep[nome], frames):
                    if f["g"]["leitura"] == cal:
                        continue
                    lido = leitor.ler(q, f["n"], caixa=roi, deslocamentos=desl)["leitura"]
                    real = f["g"]["leitura"]
                    ex += lido == real
                    dg += sum(a == b for a, b in zip(real, lido))
                    tot += f["n"]
                    n += 1
                    erros.append(np.mean(np.abs(np.array(vb) - np.array(roi))))
                taxas.append(ex / n)
                tx_dig.append(dg / tot)
                ex_t, dg_t, tot_t, n_t = ex_t + ex, dg_t + dg, tot_t + tot, n_t + n
            saida.append(f"| {nome} | calibrada com UMA leitura, testada nas outras | {ex_t}/{n_t} ({100 * ex_t / n_t:.0f} %) "
                         f"| {dg_t}/{tot_t} ({100 * dg_t / tot_t:.0f} %) | {100 * min(taxas):.0f} % / {100 * max(taxas):.0f} % "
                         f"| {np.mean(erros):.1f} |")
            resumo.append((medidor, nome, ex_t / n_t, dg_t / tot_t))
        saida.append("")
        print(f"{medidor}: ok", flush=True)

    # ---- tolerância ao erro da ROI (todas as fotos, quadro de cada foto alinhado, caixa verdadeira + erro) ----
    saida += ["## Tolerância ao erro da ROI (alinhada, todas as 39 fotos)", "",
              "Erro aleatório uniforme de ±d px somado a cada coordenada da caixa verdadeira (média de 3 sorteios).", "",
              "| d (px) | Leituras exatas, fatias iguais | Dígitos certos | Leituras exatas, votação | Dígitos certos |", "|---|---|---|---|---|"]
    todos = []
    for medidor, linhas in sorted(familias.items()):
        pass
    for g in gab:
        bruto = cv2.imdecode(np.fromfile(os.path.join(DIR_TESTE, "imagens", g["arquivo"]), np.uint8), cv2.IMREAD_COLOR)
        q, _ = transmitir_como_jpeg(para_quadro_camera(bruto, int(g["centro_y"])))
        q, ang = alinhar(q)
        caixa = girar_caixa(tuple(int(v) for v in g["caixa_manual"].split(",")), ang)
        todos.append((q, caixa, g["leitura"], int(g["n_digitos"])))
    for d in (0, 1, 2, 3, 4, 6):
        res = {}
        for vota in (False, True):
            ex = dg = tot = n = 0
            for semente in range(3):
                rng = np.random.default_rng(100 + semente)
                for q, caixa, real, ndig in todos:
                    e = rng.integers(-d, d + 1, 4)
                    c = (max(caixa[0] + e[0], 0), max(caixa[1] + e[1], 0), min(caixa[2] + e[2], CAM_W - 1), min(caixa[3] + e[3], 119))
                    lido = leitor.ler(q, ndig, caixa=c, deslocamentos=DESLOCAMENTOS if vota else ((0, 0),))["leitura"]
                    ex += lido == real
                    dg += sum(a == b for a, b in zip(real, lido))
                    tot += ndig
                    n += 1
            res[vota] = (ex / n, dg / tot)
        saida.append(f"| ±{d} | {100 * res[False][0]:.0f} % | {100 * res[False][1]:.0f} % | {100 * res[True][0]:.0f} % | {100 * res[True][1]:.0f} % |")
        print("tolerância d =", d, flush=True)
    saida.append("")

    saida += ["## Como ler", "",
              "- **Oráculo**: usa a caixa marcada à mão de cada foto (o melhor que a variante daria com a janela perfeita).",
              "- **Mediana**: uma ROI única para o medidor, a mediana das caixas verdadeiras (calibrar com todas as fotos).",
              "- **Uma leitura**: o caso realista de uma calibração de instalação com uma só foto; as taxas somam todas as",
              "  fotos de teste de todas as calibrações possíveis, e a coluna mostra o pior e o melhor grupo de calibração.",
              "- O erro da ROI é a média de |caixa verdadeira - ROI| nas quatro coordenadas, em pixels do quadro 160×120.", ""]
    destino = os.path.join(DIR_TESTE, "resultados", "ROI_FIXA.md")
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    with open(destino, "w", encoding="utf-8") as f:
        f.write("\n".join(saida) + "\n")
    print("\n".join(saida))


if __name__ == "__main__":
    main()
