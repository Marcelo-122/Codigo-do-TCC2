"""Lê o conjunto físico (`dados/teste/`) com a ROI calibrada UMA VEZ por posição de câmera: o pipeline adotado.

É o modo `roi` do `transmissor_ocr_esp32cam`: a caixa, o número de dígitos e a face da roda vêm da calibração feita
com o `calibrar_roi_esp32cam` antes das fotos (`dados/teste/roi_calibrada.csv`, uma linha por foto, apontando para o
JSON da calibração), não de uma marcação foto a foto (`avaliar_roi_manual.py`) nem do modelo de segmentação
(`avaliar_pipeline.py --conjunto fisico`). Sem rotação: a câmera foi montada com a fileira reta e o firmware não gira
o quadro. Só as fotos com ROI calibrada entram (as da bancada de 2026-11-18, medidor `fisico_1`).

Fluxos, como nos outros scripts: borda = quadro direto; nuvem = o mesmo quadro depois do JPEG q90. Variantes: fatias
da caixa sem votação (o que o firmware faz) e com votação entre 5 caixas deslocadas (±2 px em x, ±1 px em y).

Saídas (na raiz do repositório):
  medicoes/ocr_teste.csv                               linhas `fisico_roi_calibrada` e `fisico_roi_calibrada_votacao`
                                                       (borda e nuvem); as dos outros conjuntos ficam;
  medicoes/ocr_teste_por_imagem_fisico_roi_calibrada.csv  uma linha por (foto, fluxo, variante).

Uso:  python ocr/avaliar_roi_calibrada.py
"""
import csv
import datetime
import os
import sys

import cv2
import numpy as np

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
from avaliar_pipeline import CAMPOS_RESUMO, SAIDA_RESUMO, _hash_arquivo, distancia_edicao  # noqa: E402
from avaliar_roi_fixa import DESLOCAMENTOS  # noqa: E402
from pipeline_nuvem import MODELO_DIGITO, LeitorB, para_quadro_camera, transmitir_como_jpeg  # noqa: E402

RAIZ = os.path.dirname(AQUI)
DIR_TESTE = os.path.join(RAIZ, "dados", "teste")
SAIDA_POR_IMAGEM = os.path.join(RAIZ, "medicoes", "ocr_teste_por_imagem_fisico_roi_calibrada.csv")
VARIANTES = (("fisico_roi_calibrada", ((0, 0),)), ("fisico_roi_calibrada_votacao", DESLOCAMENTOS))


def carregar():
    with open(os.path.join(DIR_TESTE, "rotulos.csv"), encoding="utf-8") as f:
        rotulos = {l["arquivo"]: l for l in csv.DictReader(f)}
    with open(os.path.join(DIR_TESTE, "roi_calibrada.csv"), encoding="utf-8") as f:
        rois = list(csv.DictReader(f))
    itens = []
    for r in rois:
        l = rotulos.get(r["arquivo"])
        if l is None:
            sys.exit(f"{r['arquivo']} está em roi_calibrada.csv mas não em rotulos.csv")
        fa, fb = (int(v) for v in r["face_pct"].split("-"))
        itens.append({"arquivo": r["arquivo"], "leitura": l["leitura"].strip(), "n": int(r["n_digitos"]),
                      "caixa": tuple(int(v) for v in r["caixa"].split(",")), "face": (fa, fb), "realce": int(r["realce"]),
                      "posicao": r["posicao"], "independente": int(l["leitura"].strip() != r["leitura_calibracao"])})
    return itens


def main():
    sys.stdout.reconfigure(errors="replace")
    itens = carregar()
    leitor = LeitorB()
    por_imagem = []
    for it in itens:
        bruto = cv2.imdecode(np.fromfile(os.path.join(DIR_TESTE, "imagens", it["arquivo"]), np.uint8), cv2.IMREAD_COLOR)
        quadro = para_quadro_camera(bruto)
        for fluxo in ("borda", "nuvem"):
            q = quadro if fluxo == "borda" else transmitir_como_jpeg(quadro)[0]
            for variante, desl in VARIANTES:
                lido = leitor.ler(q, it["n"], caixa=it["caixa"], deslocamentos=desl, face=it["face"],
                                  realce=it["realce"])["leitura"]
                real = it["leitura"]
                por_imagem.append({"conjunto": variante, "arquivo": it["arquivo"], "fluxo": fluxo, "leitura_real": real,
                                   "leitura_lida": lido, "exato": int(lido == real),
                                   "digitos_certos": sum(a == b for a, b in zip(real, lido)), "n_digitos": it["n"],
                                   "erros_edicao": distancia_edicao(real, lido),
                                   "caixa": "{},{},{},{}".format(*it["caixa"]),
                                   "face_pct": "{}-{}".format(*it["face"]), "realce": it["realce"],
                                   "posicao": it["posicao"], "independente_da_calibracao": it["independente"]})

    modelo_digito = _hash_arquivo(MODELO_DIGITO)
    resumo = []
    for variante, _ in VARIANTES:
        for fluxo in ("borda", "nuvem"):
            ls = [l for l in por_imagem if l["conjunto"] == variante and l["fluxo"] == fluxo]
            exatas = sum(l["exato"] for l in ls)
            dig_ok, dig_tot = sum(l["digitos_certos"] for l in ls), sum(l["n_digitos"] for l in ls)
            resumo.append({
                "conjunto": variante, "origem": "fisico", "fluxo": fluxo, "n_imagens": len(ls),
                "leituras_exatas": exatas, "taxa_leitura_exata": round(exatas / len(ls), 4),
                "digitos_certos": dig_ok, "digitos_total": dig_tot, "acuracia_digito": round(dig_ok / dig_tot, 4),
                "cer": round(sum(l["erros_edicao"] for l in ls) / dig_tot, 4), "n_com_caixa_real": len(ls),
                "dice_mascara": "", "iou_mascara": "", "iou_caixa": "", "sem_caixa_prevista": "",
                "modelo_segmentacao": "", "modelo_digito": modelo_digito,   # sem segmentação
                "data": datetime.date.today().isoformat(),
            })
            ind = [l for l in ls if l["independente_da_calibracao"]]
            print(f"{variante} {fluxo}: leitura exata {exatas}/{len(ls)} ({exatas / len(ls):.0%}), dígitos "
                  f"{dig_ok}/{dig_tot} ({dig_ok / dig_tot:.1%}), CER {resumo[-1]['cer']}; sem as fotos da leitura "
                  f"da calibração: {sum(l['exato'] for l in ind)}/{len(ind)}")

    with open(SAIDA_POR_IMAGEM, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(por_imagem[0].keys()))
        w.writeheader()
        w.writerows(por_imagem)
    existentes = []
    if os.path.exists(SAIDA_RESUMO):
        with open(SAIDA_RESUMO, encoding="utf-8") as f:
            existentes = [l for l in csv.DictReader(f) if l["conjunto"] not in {v[0] for v in VARIANTES}]
    with open(SAIDA_RESUMO, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CAMPOS_RESUMO)
        w.writeheader()
        w.writerows(existentes + resumo)
    print(f"gravado em {os.path.relpath(SAIDA_POR_IMAGEM, RAIZ)} e {os.path.relpath(SAIDA_RESUMO, RAIZ)}")


if __name__ == "__main__":
    main()
