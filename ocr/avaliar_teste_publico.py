"""Avalia fatiamento + classificador de dígito (INT8) nas pastas `test` do Word-Wheel Water Meter Dataset (Dryad).

Essas pastas ficam FORA do treino (`ModeloEDataset/preparar_dataset_dryad.py` só usa `train`), então este é um
teste independente com dados públicos. Os recortes do Dryad já são a janela dos dígitos (200×60), por isso não há
segmentação aqui: cada recorte é cortado em N fatias iguais e cada fatia vai para o classificador, com o mesmo
pré-processamento do firmware (vizinho mais próximo, entrada int8 = pixel - 128). Mesma limpeza do treino:
descarta `half-word=1` e desespelha `reversed=1`.

ATENÇÃO: o `modelo_digito.tflite` versionado foi treinado ANTES de as pastas `test` saírem do treino, então ele já
viu estes dados. Os números só valem como teste independente depois de re-treinar o classificador com
`preparar_dataset_dryad.py` + `treinar_classificador_digitos.py` (ver ModeloEDataset/README.md).

Grava a linha `dryad_teste` em `medicoes/ocr_teste.csv` (substitui a anterior) e
`medicoes/ocr_teste_por_imagem_dryad_teste.csv`. Com `--rotulo X` o conjunto passa a se chamar `dryad_teste_X`,
e com `--modelo-digito` avalia outro .tflite (comparar variantes de treino). Uso (na raiz do repositório):

    python ocr/avaliar_teste_publico.py [--dryad PASTA_recognition] [--modelo-digito M.tflite --rotulo X]
"""
import argparse
import csv
import datetime
import os
import sys

import cv2
import numpy as np

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(AQUI)
sys.path.insert(0, AQUI)
sys.path.insert(0, os.path.join(RAIZ, "ModeloEDataset"))
from avaliar_pipeline import SAIDA_RESUMO, _hash_arquivo, distancia_edicao, gravar  # noqa: E402
from pipeline_nuvem import MODELO_DIGITO, MODELO_SEGMENTACAO, LeitorB  # noqa: E402
from preparar_dataset_dryad import CONJUNTOS_TESTE, DIR_DRYAD  # noqa: E402

CONJUNTO = "dryad_teste"
FLUXO = "fatias_sem_segmentacao"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dryad", default=DIR_DRYAD, help="pasta `recognition` do dataset (padrão: a de preparar_dataset_dryad.py)")
    ap.add_argument("--modelo-digito", default=MODELO_DIGITO, help="classificador .tflite a avaliar (padrão: o versionado)")
    ap.add_argument("--rotulo", default="", help="sufixo do nome do conjunto (ex.: fase_a), para comparar variantes sem apagar a linha oficial")
    a = ap.parse_args()
    conjunto = CONJUNTO + (f"_{a.rotulo}" if a.rotulo else "")
    if not os.path.isdir(a.dryad):
        sys.exit(f"pasta do Dryad não encontrada: {a.dryad}\nBaixe com: python scripts/download_datasets.py --listar")

    leitor = LeitorB(modelo_digito=a.modelo_digito)
    por_imagem, descartadas = [], 0
    for subpasta, prefixo, n in CONJUNTOS_TESTE:
        base = os.path.join(a.dryad, subpasta)
        with open(os.path.join(base, f"{prefixo}_rec_label_CSV.csv"), newline="", encoding="utf-8") as f:
            for nome, rotulo, invertida, meia in (l[:4] for l in csv.reader(f)):
                img = None
                if meia != "1" and len(rotulo) == n:
                    dados = np.fromfile(os.path.join(base, f"{prefixo}_img", nome), np.uint8)
                    img = cv2.imdecode(dados, cv2.IMREAD_GRAYSCALE) if dados.size else None
                if img is None:
                    descartadas += 1
                    continue
                if invertida == "1":
                    img = cv2.flip(img, 1)
                h, w = img.shape
                lido = "".join(str(leitor.classificar_fatia(img, (w * i) // n, 0, (w * (i + 1)) // n, h)) for i in range(n))
                por_imagem.append({"arquivo": f"{prefixo}/{nome}", "medidor": f"{n}-digit", "fluxo": FLUXO,
                                   "leitura_real": rotulo, "leitura_lida": lido, "exato": int(lido == rotulo),
                                   "digitos_certos": sum(x == y for x, y in zip(rotulo, lido)), "n_digitos": n,
                                   "erros_edicao": distancia_edicao(rotulo, lido)})
    if not por_imagem:
        sys.exit("nenhuma imagem avaliada")

    exatas = sum(l["exato"] for l in por_imagem)
    dig_ok, dig_tot = sum(l["digitos_certos"] for l in por_imagem), sum(l["n_digitos"] for l in por_imagem)
    resumo = [{"conjunto": conjunto, "origem": "publico", "fluxo": FLUXO, "n_imagens": len(por_imagem),
               "leituras_exatas": exatas, "taxa_leitura_exata": round(exatas / len(por_imagem), 4),
               "digitos_certos": dig_ok, "digitos_total": dig_tot, "acuracia_digito": round(dig_ok / dig_tot, 4),
               "cer": round(sum(l["erros_edicao"] for l in por_imagem) / dig_tot, 4),
               "n_com_caixa_real": 0, "dice_mascara": "", "iou_mascara": "", "iou_caixa": "", "sem_caixa_prevista": "",
               "modelo_segmentacao": _hash_arquivo(MODELO_SEGMENTACAO), "modelo_digito": _hash_arquivo(a.modelo_digito),
               "data": datetime.date.today().isoformat()}]
    gravar(por_imagem, resumo, conjunto)
    r = resumo[0]
    print(f"{conjunto}: {len(por_imagem)} recortes ({descartadas} descartados), leitura exata {exatas} "
          f"({100 * r['taxa_leitura_exata']:.1f} %), dígitos {100 * r['acuracia_digito']:.1f} %, CER {r['cer']:.4f}")
    print(f"gravado em {os.path.relpath(SAIDA_RESUMO, RAIZ)}")


if __name__ == "__main__":
    main()
