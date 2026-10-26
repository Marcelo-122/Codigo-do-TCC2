"""Avalia o pipeline COMPLETO do Pipeline B (segmentação → fatias → dígitos), em INT8, sem caixa manual.

Diferente de `ocr/avaliar.py` (que também roda modos de diagnóstico com a caixa marcada à mão) e de
`ModeloEDataset/testar_imagens_novas.py` (que recorta à mão), aqui a caixa vem SEMPRE do modelo de
segmentação, como no firmware. Para cada foto, nos dois fluxos (borda: quadro 160×120 direto; nuvem: o mesmo
quadro depois do JPEG q90), mede:

  - taxa de leitura exata (a string inteira bate com o rótulo);
  - acurácia por dígito (posição a posição, sobre o total de dígitos do conjunto);
  - CER (taxa de erro de caracteres: distância de edição / total de caracteres do rótulo);
  - Dice e IoU da máscara de segmentação (192×192) contra a janela marcada à mão, e IoU da caixa. Só entram as
    fotos que têm a caixa de referência (coluna `caixa`/`caixa_manual`).

Conjuntos (`--conjunto`):
  fisico : `dados/teste/` (fotos da ESP32-CAM de um hidrômetro físico; rótulos em `dados/teste/rotulos.csv`).
           É o conjunto que a issue pede; ver `dados/teste/README.md`.
  comum  : `ocr/teste_comum/` (fotos da ESP32-CAM de um MONITOR exibindo medidores). Não é medidor físico:
           serve de referência e para exercitar o código enquanto o conjunto físico não existe.

Saídas, na raiz do repositório:
  medicoes/ocr_teste.csv                        uma linha por (conjunto, fluxo); substitui só as linhas do
                                                conjunto avaliado e mantém as dos outros;
  medicoes/ocr_teste_por_imagem_<conjunto>.csv  uma linha por (foto, fluxo), para achar onde errou.

A "borda" é uma EMULAÇÃO em Python (kernels de referência do TFLite INT8, quadro 160×120 reduzido da foto);
não é a acurácia medida na ESP32-CAM. Uso (na raiz do repositório):

    python ocr/avaliar_pipeline.py --conjunto comum
    python ocr/avaliar_pipeline.py --conjunto fisico
"""
import argparse
import csv
import datetime
import hashlib
import os
import sys

import cv2
import numpy as np

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
from pipeline_nuvem import (CAM_H, CAM_W, MODEL_H, MODEL_W, MODELO_DIGITO, MODELO_SEGMENTACAO,  # noqa: E402
                            LeitorB, para_quadro_camera, transmitir_como_jpeg)

RAIZ = os.path.dirname(AQUI)
DIR_MEDICOES = os.path.join(RAIZ, "medicoes")
SAIDA_RESUMO = os.path.join(DIR_MEDICOES, "ocr_teste.csv")
FLUXOS = ("borda", "nuvem")

CAMPOS_RESUMO = ["conjunto", "origem", "fluxo", "n_imagens", "leituras_exatas", "taxa_leitura_exata",
                 "digitos_certos", "digitos_total", "acuracia_digito", "cer",
                 "n_com_caixa_real", "dice_mascara", "iou_mascara", "iou_caixa", "sem_caixa_prevista",
                 "modelo_segmentacao", "modelo_digito", "data"]


def distancia_edicao(a, b):
    """Distância de Levenshtein entre duas strings."""
    anterior = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        atual = [i]
        for j, cb in enumerate(b, 1):
            atual.append(min(anterior[j] + 1, atual[j - 1] + 1, anterior[j - 1] + (ca != cb)))
        anterior = atual
    return anterior[-1]


def mascara_da_caixa(caixa):
    """Máscara 192×192 da janela (x0, y0, x1, y1) do quadro 160×120, inclusive nas bordas.

    Usa o mesmo mapeamento do firmware (`x * CAM_W // MODEL_W`), o inverso do que `achar_caixa` faz."""
    x0, y0, x1, y1 = caixa
    xs = (np.arange(MODEL_W) * CAM_W) // MODEL_W
    ys = (np.arange(MODEL_H) * CAM_H) // MODEL_H
    return ((ys >= y0) & (ys <= y1))[:, None] & ((xs >= x0) & (xs <= x1))[None, :]


def dice_iou(prevista, real):
    """Dice e IoU entre duas máscaras booleanas."""
    inter = int(np.logical_and(prevista, real).sum())
    soma = int(prevista.sum()) + int(real.sum())
    uniao = soma - inter
    return (2 * inter / soma if soma else 1.0), (inter / uniao if uniao else 1.0)


def iou_caixas(a, b):
    """IoU de duas caixas (x0, y0, x1, y1) em pixels, bordas inclusivas."""
    ix = min(a[2], b[2]) - max(a[0], b[0]) + 1
    iy = min(a[3], b[3]) - max(a[1], b[1]) + 1
    inter = max(ix, 0) * max(iy, 0)
    area = lambda c: (c[2] - c[0] + 1) * (c[3] - c[1] + 1)  # noqa: E731
    return inter / (area(a) + area(b) - inter)


def _caixa(texto):
    texto = (texto or "").strip()
    return tuple(int(v) for v in texto.split(",")) if texto else None


def carregar_conjunto(nome):
    """Devolve (lista de dicts {arquivo, caminho, leitura, n, medidor, origem, centro_y, caixa}, origem do conjunto)."""
    if nome == "comum":
        base = os.path.join(AQUI, "teste_comum")
        with open(os.path.join(base, "gabarito.csv"), encoding="utf-8") as f:
            linhas = list(csv.DictReader(f))
        return [{"arquivo": l["arquivo"], "caminho": os.path.join(base, "imagens", l["arquivo"]),
                 "leitura": l["leitura"], "n": int(l["n_digitos"]), "medidor": l["medidor"],
                 "centro_y": int(l["centro_y"]), "caixa": _caixa(l["caixa_manual"])} for l in linhas], "monitor"
    if nome == "fisico":
        base = os.path.join(RAIZ, "dados", "teste")
        with open(os.path.join(base, "rotulos.csv"), encoding="utf-8") as f:
            linhas = [l for l in csv.DictReader(f) if l["arquivo"].strip()]
        if not linhas:
            sys.exit("dados/teste/rotulos.csv está vazio: ainda não há fotos do medidor físico (ver dados/teste/README.md)")
        return [{"arquivo": l["arquivo"], "caminho": os.path.join(base, "imagens", l["arquivo"]),
                 "leitura": l["leitura"].strip(), "n": int(l["n_digitos"]), "medidor": l["medidor"],
                 "centro_y": int(l["centro_y"]) if l.get("centro_y", "").strip() else None,
                 "caixa": _caixa(l.get("caixa"))} for l in linhas], "fisico"
    sys.exit(f"conjunto desconhecido: {nome}")


def _hash_arquivo(caminho):
    with open(caminho, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()[:12]


def avaliar(conjunto):
    itens, origem = carregar_conjunto(conjunto)
    leitor = LeitorB()
    por_imagem = []
    for it in itens:
        bruto = cv2.imdecode(np.fromfile(it["caminho"], np.uint8), cv2.IMREAD_COLOR)
        if bruto is None:
            sys.exit(f"não consegui abrir {it['caminho']}")
        if len(it["leitura"]) != it["n"] or not it["leitura"].isdigit():
            sys.exit(f"rótulo inválido em {it['arquivo']}: {it['leitura']!r} com n_digitos={it['n']}")
        quadro = para_quadro_camera(bruto, it["centro_y"])
        for fluxo in FLUXOS:
            entrada = quadro if fluxo == "borda" else transmitir_como_jpeg(quadro)[0]
            r = leitor.ler(entrada, it["n"])  # sem caixa: a segmentação do modelo decide
            real, lido = it["leitura"], r["leitura"]
            linha = {"arquivo": it["arquivo"], "medidor": it["medidor"], "fluxo": fluxo, "leitura_real": real,
                     "leitura_lida": lido, "exato": int(lido == real),
                     "digitos_certos": sum(a == b for a, b in zip(real, lido)), "n_digitos": it["n"],
                     "erros_edicao": distancia_edicao(real, lido),
                     "caixa_prevista": "" if r["caixa"] is None else "{},{},{},{}".format(*r["caixa"]),
                     "caixa_real": "" if it["caixa"] is None else "{},{},{},{}".format(*it["caixa"]),
                     "dice_mascara": "", "iou_mascara": "", "iou_caixa": ""}
            if it["caixa"] is not None:
                dice, iou = dice_iou(r["mascara"], mascara_da_caixa(it["caixa"]))
                linha["dice_mascara"], linha["iou_mascara"] = round(dice, 4), round(iou, 4)
                linha["iou_caixa"] = round(iou_caixas(r["caixa"], it["caixa"]), 4) if r["caixa"] else 0.0
            por_imagem.append(linha)
    return por_imagem, origem


def resumir(por_imagem, conjunto, origem):
    modelos = (_hash_arquivo(MODELO_SEGMENTACAO), _hash_arquivo(MODELO_DIGITO))
    linhas = []
    for fluxo in FLUXOS:
        ls = [l for l in por_imagem if l["fluxo"] == fluxo]
        exatas = sum(l["exato"] for l in ls)
        dig_ok, dig_tot = sum(l["digitos_certos"] for l in ls), sum(l["n_digitos"] for l in ls)
        com_caixa = [l for l in ls if l["dice_mascara"] != ""]
        media = lambda campo: round(float(np.mean([l[campo] for l in com_caixa])), 4) if com_caixa else ""  # noqa: E731
        linhas.append({
            "conjunto": conjunto, "origem": origem, "fluxo": fluxo, "n_imagens": len(ls),
            "leituras_exatas": exatas, "taxa_leitura_exata": round(exatas / len(ls), 4),
            "digitos_certos": dig_ok, "digitos_total": dig_tot, "acuracia_digito": round(dig_ok / dig_tot, 4),
            "cer": round(sum(l["erros_edicao"] for l in ls) / dig_tot, 4),
            "n_com_caixa_real": len(com_caixa),
            "dice_mascara": media("dice_mascara"), "iou_mascara": media("iou_mascara"),
            "iou_caixa": media("iou_caixa"),
            "sem_caixa_prevista": sum(1 for l in ls if l["caixa_prevista"] == ""),
            "modelo_segmentacao": modelos[0], "modelo_digito": modelos[1],
            "data": datetime.date.today().isoformat(),
        })
    return linhas


def gravar(por_imagem, resumo, conjunto):
    os.makedirs(DIR_MEDICOES, exist_ok=True)
    with open(os.path.join(DIR_MEDICOES, f"ocr_teste_por_imagem_{conjunto}.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(por_imagem[0].keys()))
        w.writeheader()
        w.writerows(por_imagem)
    existentes = []
    if os.path.exists(SAIDA_RESUMO):
        with open(SAIDA_RESUMO, encoding="utf-8") as f:
            existentes = [l for l in csv.DictReader(f) if l["conjunto"] != conjunto]
    with open(SAIDA_RESUMO, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CAMPOS_RESUMO)
        w.writeheader()
        w.writerows(existentes + resumo)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--conjunto", choices=["fisico", "comum"], required=True)
    a = ap.parse_args()
    por_imagem, origem = avaliar(a.conjunto)
    resumo = resumir(por_imagem, a.conjunto, origem)
    gravar(por_imagem, resumo, a.conjunto)
    for r in resumo:
        print(f"{r['conjunto']} ({r['origem']}) {r['fluxo']:5s}: leitura exata {r['leituras_exatas']}/{r['n_imagens']} "
              f"({100 * r['taxa_leitura_exata']:.0f} %), dígitos {100 * r['acuracia_digito']:.1f} %, CER {r['cer']:.3f}, "
              f"Dice {r['dice_mascara']}, IoU máscara {r['iou_mascara']}, IoU caixa {r['iou_caixa']}")
    print(f"gravado em {os.path.relpath(SAIDA_RESUMO, RAIZ)}")


if __name__ == "__main__":
    main()
