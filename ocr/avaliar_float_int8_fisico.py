"""H1 no conjunto físico: classificador em ponto flutuante (modelo_digito.h5) × INT8 (modelo_digito.tflite).

Mesmas fotos, mesma ROI calibrada e mesmo recorte da face da roda do `avaliar_roi_calibrada.py` (as 30 fotos da
bancada em `dados/teste/`): só muda o classificador. Pergunta da H1: a quantização INT8, necessária para caber na
ESP32-CAM, custa acurácia na leitura do medidor?

- Float: inferência em numpy com os pesos do .h5 (`ModeloEDataset/comparar_float_int8.rede_float`, sem TensorFlow),
  entrada pixel / 255, como no treino.
- INT8: `pipeline_nuvem.LeitorB` (ai-edge-litert sem XNNPACK), entrada pixel - 128, como o firmware.
- Pareado: teste exato de McNemar sobre os dígitos (e as leituras) em que só um dos dois acerta.
- Fluxos borda (quadro direto) e nuvem (JPEG q90). No servidor, o float poderia ser usado no lugar do INT8.

Saídas (na raiz do repositório):
  medicoes/ocr_teste.csv                                     linhas `fisico_roi_calibrada_float` (borda e nuvem);
  medicoes/ocr_teste_por_imagem_fisico_roi_calibrada_float.csv  uma linha por (foto, fluxo), float e INT8 lado a lado;
  ModeloEDataset/relatorios/comparacao_float_int8_fisico.json  acurácias e McNemar.

Uso:  python ocr/avaliar_float_int8_fisico.py   (precisa de h5py, além das dependências do ocr/)
"""
import csv
import datetime
import json
import os
import sys

import cv2
import h5py
import numpy as np

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(AQUI)
sys.path.insert(0, AQUI)
sys.path.insert(0, os.path.join(RAIZ, "ModeloEDataset"))
from avaliar_pipeline import CAMPOS_RESUMO, SAIDA_RESUMO, _hash_arquivo, distancia_edicao  # noqa: E402
from avaliar_roi_calibrada import DIR_TESTE, carregar  # noqa: E402
from comparar_float_int8 import mcnemar_exato, rede_float  # noqa: E402
from pipeline_nuvem import LeitorB, entrada_fatia, para_quadro_camera, transmitir_como_jpeg  # noqa: E402

MODELO_FLOAT = os.path.join(RAIZ, "ModeloEDataset", "modelos", "modelo_digito.h5")
CONJUNTO = "fisico_roi_calibrada_float"
SAIDA_POR_IMAGEM = os.path.join(RAIZ, "medicoes", f"ocr_teste_por_imagem_{CONJUNTO}.csv")
SAIDA_JSON = os.path.join(RAIZ, "ModeloEDataset", "relatorios", "comparacao_float_int8_fisico.json")


def main():
    sys.stdout.reconfigure(errors="replace")
    itens = carregar()
    leitor = LeitorB()
    with h5py.File(MODELO_FLOAT, "r") as f:
        prever_float = rede_float(f["model_weights"])

        linhas, digitos = [], []   # digitos: (fluxo, real, float, int8) por dígito
        for it in itens:
            bruto = cv2.imdecode(np.fromfile(os.path.join(DIR_TESTE, "imagens", it["arquivo"]), np.uint8),
                                 cv2.IMREAD_COLOR)
            quadro = para_quadro_camera(bruto)
            x0, y0, x1, y1 = it["caixa"]
            larg = x1 - x0
            for fluxo in ("borda", "nuvem"):
                q = quadro if fluxo == "borda" else transmitir_como_jpeg(quadro)[0]
                entradas = [entrada_fatia(q, x0 + larg * i // it["n"], y0, x0 + larg * (i + 1) // it["n"], y1,
                                          it["face"], it["realce"]) for i in range(it["n"])]
                lido_q = "".join(str(int(np.argmax(leitor.pontuacoes_entrada(e)))) for e in entradas)
                lote = np.stack(entradas).astype(np.float32)[..., None] / 255.0
                lido_f = "".join(str(int(d)) for d in prever_float(lote))
                real = it["leitura"]
                digitos += [(fluxo, r, a, b) for r, a, b in zip(real, lido_f, lido_q)]
                linhas.append({"arquivo": it["arquivo"], "fluxo": fluxo, "leitura_real": real,
                               "lido_float": lido_f, "lido_int8": lido_q,
                               "exato_float": int(lido_f == real), "exato_int8": int(lido_q == real),
                               "digitos_certos_float": sum(a == b for a, b in zip(real, lido_f)),
                               "digitos_certos_int8": sum(a == b for a, b in zip(real, lido_q)), "n_digitos": it["n"],
                               "erros_edicao_float": distancia_edicao(real, lido_f),
                               "erros_edicao_int8": distancia_edicao(real, lido_q),
                               "independente_da_calibracao": it["independente"]})

    resumo, rel = [], {"fotos": len(itens), "data": datetime.date.today().isoformat(),
                       "modelo_float": os.path.basename(MODELO_FLOAT), "fluxos": {}}
    for fluxo in ("borda", "nuvem"):
        ls = [l for l in linhas if l["fluxo"] == fluxo]
        ds = [d for d in digitos if d[0] == fluxo]
        n_dig = sum(l["n_digitos"] for l in ls)
        b_dig = sum(1 for _, r, f_, q in ds if f_ == r and q != r)
        c_dig = sum(1 for _, r, f_, q in ds if q == r and f_ != r)
        b_lei = sum(1 for l in ls if l["exato_float"] and not l["exato_int8"])
        c_lei = sum(1 for l in ls if l["exato_int8"] and not l["exato_float"])
        rel["fluxos"][fluxo] = {
            "leituras_exatas_float": sum(l["exato_float"] for l in ls),
            "leituras_exatas_int8": sum(l["exato_int8"] for l in ls), "leituras": len(ls),
            "digitos_certos_float": sum(l["digitos_certos_float"] for l in ls),
            "digitos_certos_int8": sum(l["digitos_certos_int8"] for l in ls), "digitos": n_dig,
            "cer_float": round(sum(l["erros_edicao_float"] for l in ls) / n_dig, 4),
            "cer_int8": round(sum(l["erros_edicao_int8"] for l in ls) / n_dig, 4),
            "digitos_iguais_float_int8": sum(1 for _, _, f_, q in ds if f_ == q),
            "digitos_so_float_acerta": b_dig, "digitos_so_int8_acerta": c_dig,
            "mcnemar_exato_p_digitos": round(mcnemar_exato(b_dig, c_dig), 4),
            "leituras_so_float_acerta": b_lei, "leituras_so_int8_acerta": c_lei,
            "mcnemar_exato_p_leituras": round(mcnemar_exato(b_lei, c_lei), 4),
        }
        exatas = rel["fluxos"][fluxo]["leituras_exatas_float"]
        dig_ok = rel["fluxos"][fluxo]["digitos_certos_float"]
        resumo.append({
            "conjunto": CONJUNTO, "origem": "fisico", "fluxo": fluxo, "n_imagens": len(ls),
            "leituras_exatas": exatas, "taxa_leitura_exata": round(exatas / len(ls), 4),
            "digitos_certos": dig_ok, "digitos_total": n_dig, "acuracia_digito": round(dig_ok / n_dig, 4),
            "cer": rel["fluxos"][fluxo]["cer_float"], "n_com_caixa_real": len(ls),
            "dice_mascara": "", "iou_mascara": "", "iou_caixa": "", "sem_caixa_prevista": "",
            "modelo_segmentacao": "", "modelo_digito": _hash_arquivo(MODELO_FLOAT),
            "data": rel["data"],
        })
        r = rel["fluxos"][fluxo]
        print(f"{fluxo}: float {r['leituras_exatas_float']}/{len(ls)} leituras, {r['digitos_certos_float']}/{n_dig} "
              f"dígitos, CER {r['cer_float']} | INT8 {r['leituras_exatas_int8']}/{len(ls)}, "
              f"{r['digitos_certos_int8']}/{n_dig}, CER {r['cer_int8']} | dígitos iguais "
              f"{r['digitos_iguais_float_int8']}/{n_dig}; só float acerta {b_dig}, só INT8 {c_dig}, "
              f"McNemar p = {r['mcnemar_exato_p_digitos']}")

    with open(SAIDA_POR_IMAGEM, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(linhas[0].keys()))
        w.writeheader()
        w.writerows(linhas)
    with open(SAIDA_RESUMO, encoding="utf-8") as f:
        existentes = [l for l in csv.DictReader(f) if l["conjunto"] != CONJUNTO]
    with open(SAIDA_RESUMO, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CAMPOS_RESUMO)
        w.writeheader()
        w.writerows(existentes + resumo)
    with open(SAIDA_JSON, "w", encoding="utf-8") as f:
        json.dump(rel, f, indent=2, ensure_ascii=False)
    print(f"gravado em {os.path.relpath(SAIDA_POR_IMAGEM, RAIZ)}, {os.path.relpath(SAIDA_RESUMO, RAIZ)} e "
          f"{os.path.relpath(SAIDA_JSON, RAIZ)}")


if __name__ == "__main__":
    main()
